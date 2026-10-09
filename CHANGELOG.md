# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Cambiado
- Dependencias actualizadas: `ultralytics` 8.4.173, `opencv-python` 5.0.0.93, `requests` 2.34.2,
  `python-dotenv` 1.2.4, `pytest` 9.1.1, `ruff` 0.16.10 (verificado con cámara real).
- CI: `actions/checkout` y `actions/setup-python` a v7; el job de lint usa la versión de ruff
  fijada en `requirements-dev.txt`.

## [0.1.0] - 2026-10-09

### Añadido
- Detección en tiempo real con Ultralytics YOLO (`yolo11n.pt`) sobre la cámara web.
- Cálculo del centro (X, Y) de cada bounding box y cruz de guía en la visualización OpenCV.
- Notificación asíncrona a un Webhook de n8n para clases objetivo con confianza > 0.70.
- Cooldown configurable por clase (5 s por defecto) y modo *dry-run* sin URL.
- Configuración vía `.env`, tests unitarios y CI en GitHub Actions.
