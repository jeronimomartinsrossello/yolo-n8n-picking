# PoC Picking: YOLO + OpenCV + n8n

[![CI](https://github.com/jeronimomartinsrossello/yolo-n8n-picking/actions/workflows/ci.yml/badge.svg)](https://github.com/jeronimomartinsrossello/yolo-n8n-picking/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Prueba de concepto para una celda de robótica industrial / picking automatizado.
El script lee la cámara web en tiempo real, detecta objetos con **Ultralytics YOLO**,
calcula el **centro geométrico (X, Y)** de cada bounding box (que simula la consigna
para un brazo robótico o un AGV) y, cuando aparece una **clase objetivo** con confianza
> 0.70, envía un evento **HTTP POST** a un **Webhook de n8n**.

```
Cámara (0) ──► YOLO (yolo11n.pt) ──► Detecciones ──► Ventana OpenCV (caja + etiqueta + cruz +)
                                          │
                                          └─► ¿clase objetivo && conf > 0.70 && sin cooldown?
                                                    └─► POST asíncrono ──► n8n Webhook
```

## Estructura del proyecto

```
yolo-n8n-picking/
├── main.py                 # Aplicación (detector, notificador, visualización, bucle principal)
├── tests/                  # Tests unitarios (pytest), sin cámara ni modelo
├── requirements.txt        # Dependencias de ejecución (versiones fijadas)
├── requirements-dev.txt    # + pytest y ruff
├── pyproject.toml          # Metadatos y configuración de ruff/pytest
├── .env.example            # Plantilla de configuración
├── .github/                # CI (GitHub Actions), Dependabot, plantillas de issues/PR
├── CHANGELOG.md
├── CONTRIBUTING.md
└── LICENSE                 # MIT
```

## Requisitos previos

- Python **3.10+**
- Cámara web conectada (índice `0` por defecto)
- Una instancia de **n8n** (local con Docker/npm o n8n Cloud) con un workflow que empiece por un nodo **Webhook**
- La primera ejecución descarga `yolo11n.pt` (~5,4 MB) automáticamente; requiere conexión a Internet

## Configuración de n8n

1. Crea un workflow nuevo y añade un nodo **Webhook**:
   - **HTTP Method:** `POST`
   - **Path:** p. ej. `picking-detection`
   - **Respond:** `Immediately`
2. Copia la URL:
   - **Test URL** (`.../webhook-test/picking-detection`): solo funciona mientras pulsas *Listen for test event* en el editor.
   - **Production URL** (`.../webhook/picking-detection`): requiere el workflow **activado**.
3. Encadena lo que necesites tras el Webhook (Slack, base de datos, llamada a la API del robot…).
   Los campos llegan en `{{$json.body.object}}`, `{{$json.body.x}}`, etc.

Payload enviado:

```json
{
  "object": "cell phone",
  "confidence": 0.8731,
  "x": 412,
  "y": 255,
  "timestamp": "2026-10-09T10:15:42.123456+00:00"
}
```

`x`, `y` están en **píxeles** con origen en la esquina superior izquierda de la imagen.
Para un robot real habría que transformarlos a su sistema de coordenadas
(calibración cámara-robot / homografía al plano de trabajo).

## Configuración del `.env`

Copia la plantilla y edítala:

```bash
cp .env.example .env
```

| Variable               | Por defecto              | Descripción                                          |
|------------------------|--------------------------|------------------------------------------------------|
| `N8N_WEBHOOK_URL`      | *(vacío)*                | URL del Webhook. Vacía = modo *dry-run* (solo log)   |
| `YOLO_MODEL`           | `yolo11n.pt`             | También vale `yolov8n.pt` o un modelo propio `.pt`   |
| `CAMERA_INDEX`         | `0`                      | Índice de la cámara                                  |
| `TARGET_CLASSES`       | `cell phone,cup`         | Clases COCO separadas por comas                      |
| `CONFIDENCE_THRESHOLD` | `0.70`                   | Se notifica si la confianza es **mayor** que este valor |
| `COOLDOWN_SECONDS`     | `5`                      | Segundos mínimos entre avisos **de la misma clase**  |

## Instalación y ejecución

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # edita N8N_WEBHOOK_URL
python main.py
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # edita N8N_WEBHOOK_URL
python main.py
```

Pulsa **`q`** o **`ESC`** en la ventana de vídeo para salir.

## Comportamiento

- **Verde:** clase objetivo por encima del umbral (dispara webhook).
- **Azul claro:** otras detecciones (confianza ≥ 0.40, solo visual).
- **Cruz roja (+):** centro geométrico de la caja, con sus coordenadas en la etiqueta.
- **HUD:** FPS y estado del cooldown de cada clase objetivo.
- **Asíncrono:** las peticiones van en un `ThreadPoolExecutor`; un n8n lento o caído
  no congela el vídeo (timeout de 3 s, errores registrados en log).
- **Cooldown por clase:** si en un frame hay varias tazas, se envía solo la de mayor confianza,
  y no se vuelve a avisar de `cup` hasta pasados 5 s. Un `cell phone` tiene su propio contador.

## Pruebas rápidas sin n8n

Deja `N8N_WEBHOOK_URL` vacía y verás los payloads en consola como `[dry-run]`.
Para probar el endpoint a mano:

```bash
curl -X POST "$N8N_WEBHOOK_URL" -H "Content-Type: application/json" -d '{"object":"cup","confidence":0.9,"x":320,"y":240,"timestamp":"2026-10-09T10:00:00+00:00"}'
```

## Desarrollo y tests

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest
```

Los tests cubren el cálculo del centro, el filtro clase/umbral, el payload del webhook
y el cooldown por clase usando mocks (no necesitan cámara ni n8n). La CI los ejecuta
en cada push y Pull Request con Python 3.10 y 3.12.

## Limitaciones de la PoC

- Coordenadas en píxeles 2D, sin profundidad ni calibración.
- Modelo COCO preentrenado: para piezas industriales reales, entrenar un modelo propio
  (`yolo train data=piezas.yaml model=yolo11n.pt`) y apuntar `YOLO_MODEL` a su `best.pt`.
- Sin tracking: el cooldown es por clase, no por instancia de objeto.

## Licencia

Distribuido bajo licencia [MIT](LICENSE).
