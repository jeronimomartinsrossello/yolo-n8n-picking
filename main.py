"""
PoC de visión para celda de picking: YOLO + OpenCV + Webhook n8n.

Flujo por frame:
    cámara -> YOLO -> detecciones (clase, confianza, centro X/Y)
           -> dibujo en pantalla (caja, etiqueta, cruz central)
           -> si clase objetivo y confianza > umbral y fuera de cooldown
              -> POST asíncrono (hilo en segundo plano) al Webhook de n8n

Las coordenadas (x, y) son píxeles de la imagen con origen en la esquina
superior izquierda. En una celda real se transformarían al sistema de
coordenadas del robot/AGV mediante una calibración cámara-robot.

Salir: pulsa 'q' o ESC en la ventana de vídeo.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import cv2
import numpy as np
import requests
from dotenv import load_dotenv
from ultralytics import YOLO

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

load_dotenv()

N8N_WEBHOOK_URL: str = os.getenv("N8N_WEBHOOK_URL", "")
YOLO_MODEL: str = os.getenv("YOLO_MODEL", "yolo11n.pt")
CAMERA_INDEX: int = int(os.getenv("CAMERA_INDEX", "0"))
TARGET_CLASSES: frozenset[str] = frozenset(
    c.strip() for c in os.getenv("TARGET_CLASSES", "cell phone,cup").split(",") if c.strip()
)
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.70"))
COOLDOWN_SECONDS: float = float(os.getenv("COOLDOWN_SECONDS", "5"))

# Confianza mínima para *dibujar* detecciones (más baja que la de disparo,
# así el operador ve lo que el modelo "casi" detecta).
DISPLAY_CONFIDENCE: float = 0.40
HTTP_TIMEOUT_SECONDS: float = 3.0
WINDOW_NAME: str = "PoC Picking - YOLO + n8n"

# Colores BGR
COLOR_TARGET = (0, 200, 0)  # verde: clase objetivo que supera el umbral
COLOR_OTHER = (200, 160, 0)  # azul claro: cualquier otra detección
COLOR_CROSS = (0, 0, 255)  # rojo: cruz de guía en el centro

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s",
)
log = logging.getLogger("picking-poc")


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Detection:
    """Una detección de YOLO ya procesada."""

    class_name: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def center(self) -> tuple[int, int]:
        """Centro geométrico de la bounding box (X_centro, Y_centro) en píxeles."""
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    def is_target(self) -> bool:
        return self.class_name in TARGET_CLASSES and self.confidence > CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class ObjectDetector:
    """Envoltorio fino sobre Ultralytics YOLO."""

    def __init__(self, model_path: str, min_confidence: float) -> None:
        log.info("Cargando modelo %s ...", model_path)
        self.model = YOLO(model_path)
        self.min_confidence = min_confidence
        self._validate_targets()

    def _validate_targets(self) -> None:
        known = set(self.model.names.values())
        unknown = TARGET_CLASSES - known
        if unknown:
            log.warning("Clases objetivo no presentes en el modelo: %s", sorted(unknown))

    def detect(self, frame: np.ndarray) -> list[Detection]:
        result = self.model.predict(frame, conf=self.min_confidence, verbose=False)[0]
        detections: list[Detection] = []
        for box in result.boxes:
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
            detections.append(
                Detection(
                    class_name=self.model.names[int(box.cls[0])],
                    confidence=float(box.conf[0]),
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )
        return detections


# ---------------------------------------------------------------------------
# Notificador n8n (asíncrono + cooldown)
# ---------------------------------------------------------------------------


class WebhookNotifier:
    """
    Envía eventos al Webhook de n8n sin bloquear el bucle de vídeo.

    - Las peticiones se ejecutan en un ThreadPoolExecutor (fire-and-forget).
    - El cooldown es por clase: un 'cup' no bloquea el aviso de un 'cell phone'.
    """

    def __init__(self, url: str, cooldown_s: float, timeout_s: float) -> None:
        self.url = url
        self.cooldown_s = cooldown_s
        self.timeout_s = timeout_s
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="webhook")
        if not url:
            log.warning("N8N_WEBHOOK_URL no configurada: los eventos solo se registrarán en log.")

    def seconds_until_ready(self, class_name: str) -> float:
        with self._lock:
            last = self._last_sent.get(class_name)
        if last is None:
            return 0.0
        return max(0.0, self.cooldown_s - (time.monotonic() - last))

    def try_notify(self, det: Detection) -> bool:
        """Encola el envío si la clase está fuera de cooldown. Devuelve True si se encoló."""
        now = time.monotonic()
        with self._lock:
            last = self._last_sent.get(det.class_name)
            if last is not None and now - last < self.cooldown_s:
                return False
            self._last_sent[det.class_name] = now

        x, y = det.center
        payload = {
            "object": det.class_name,
            "confidence": round(det.confidence, 4),
            "x": x,
            "y": y,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._executor.submit(self._post, payload)
        return True

    def _post(self, payload: dict) -> None:
        if not self.url:
            log.info("[dry-run] %s", payload)
            return
        try:
            resp = self._session.post(self.url, json=payload, timeout=self.timeout_s)
            resp.raise_for_status()
            log.info("Webhook OK (%s): %s", resp.status_code, payload)
        except requests.RequestException as exc:
            log.error("Fallo al enviar al webhook: %s | payload=%s", exc, payload)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._session.close()


# ---------------------------------------------------------------------------
# Visualización
# ---------------------------------------------------------------------------


def draw_detection(frame: np.ndarray, det: Detection, highlight: bool) -> None:
    """Dibuja caja, etiqueta con confianza/centro y cruz de guía (+) en el centro."""
    color = COLOR_TARGET if highlight else COLOR_OTHER
    cx, cy = det.center

    cv2.rectangle(frame, (det.x1, det.y1), (det.x2, det.y2), color, 2)

    label = f"{det.class_name} {det.confidence:.0%} ({cx},{cy})"
    (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    label_y = max(det.y1, th + baseline + 4)
    cv2.rectangle(frame, (det.x1, label_y - th - baseline - 4), (det.x1 + tw + 4, label_y), color, -1)
    cv2.putText(
        frame,
        label,
        (det.x1 + 2, label_y - baseline - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    cv2.drawMarker(
        frame,
        (cx, cy),
        COLOR_CROSS,
        markerType=cv2.MARKER_CROSS,
        markerSize=20,
        thickness=2,
        line_type=cv2.LINE_AA,
    )


def draw_hud(frame: np.ndarray, fps: float, notifier: WebhookNotifier) -> None:
    """Muestra FPS y el estado de cooldown de cada clase objetivo."""
    lines = [f"FPS: {fps:4.1f}"]
    for cls in sorted(TARGET_CLASSES):
        remaining = notifier.seconds_until_ready(cls)
        lines.append(f"{cls}: {'listo' if remaining == 0 else f'cooldown {remaining:.1f}s'}")
    for i, text in enumerate(lines):
        cv2.putText(
            frame, text, (10, 22 + i * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA
        )


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------


def open_camera(index: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir la cámara con índice {index}")
    return cap


def run() -> None:
    log.info(
        "Clases objetivo: %s | umbral > %.2f | cooldown %.1fs",
        sorted(TARGET_CLASSES),
        CONFIDENCE_THRESHOLD,
        COOLDOWN_SECONDS,
    )

    detector = ObjectDetector(YOLO_MODEL, DISPLAY_CONFIDENCE)
    notifier = WebhookNotifier(N8N_WEBHOOK_URL, COOLDOWN_SECONDS, HTTP_TIMEOUT_SECONDS)
    cap = open_camera(CAMERA_INDEX)

    fps = 0.0
    prev_t = time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                log.error("No se pudo leer frame de la cámara; saliendo.")
                break

            detections = detector.detect(frame)

            # Una sola notificación por clase y frame: la de mayor confianza.
            best_per_class: dict[str, Detection] = {}
            for det in detections:
                is_target = det.is_target()
                draw_detection(frame, det, highlight=is_target)
                if is_target:
                    current = best_per_class.get(det.class_name)
                    if current is None or det.confidence > current.confidence:
                        best_per_class[det.class_name] = det

            for det in best_per_class.values():
                notifier.try_notify(det)

            now = time.perf_counter()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_t, 1e-6))
            prev_t = now
            draw_hud(frame, fps, notifier)

            cv2.imshow(WINDOW_NAME, frame)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                break
    except KeyboardInterrupt:
        log.info("Interrumpido por el usuario.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        notifier.close()
        log.info("Recursos liberados. Fin.")


if __name__ == "__main__":
    run()
