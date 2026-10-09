# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[Semantic Versioning](https://semver.org/lang/es/).

## [0.1.0] - 2026-10-09

### Añadido
- Detección en tiempo real con Ultralytics YOLO (`yolo11n.pt`) sobre la cámara web.
- Cálculo del centro (X, Y) de cada bounding box y cruz de guía en la visualización OpenCV.
- Notificación asíncrona a un Webhook de n8n para clases objetivo con confianza > 0.70.
- Cooldown configurable por clase (5 s por defecto) y modo *dry-run* sin URL.
- Configuración vía `.env`, tests unitarios y CI en GitHub Actions.
