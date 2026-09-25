"""
Ponto de entrada da aplicação — Fase 1.

Orquestra:
  - Câmeras (threads independentes)
  - Detector de pessoas (YOLOv8 + tracking)
  - Motor de regras (zonas, confirmação, cooldown)
  - Gerenciador de alarmes (som + evidências)
  - Monitor de saúde (heartbeat, disco, câmeras offline)

Uso:
    python -m munck_safety.app \\
        --config config/example.json \\
        --source 0 \\              # sobrescreve a primeira câmera (opcional)
        --operation-active         # começa com operação ativa
        --show-preview             # exibe janela com anotações (debug)
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from munck_safety.alarm import AlarmManager
from munck_safety.camera import CameraCapture
from munck_safety.config import CameraConfig, Config
from munck_safety.detector import PersonDetector
from munck_safety.logging_cfg import configure_logging, get_logger
from munck_safety.models import CameraHealth, EventKind, SafetyEvent, Severity
from munck_safety.rules import RulesEngine
from munck_safety.utils import HealthMonitor

log = get_logger(__name__)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Munck Safety System — Fase 1")
    p.add_argument("--config", default="config/example.json", help="Caminho para config JSON")
    p.add_argument("--source", default=None, help="Sobrescreve source da câmera 0 (webcam, arquivo, RTSP)")
    p.add_argument("--operation-active", action="store_true", help="Iniciar com operação ativa")
    p.add_argument("--show-preview", action="store_true", help="Exibir preview com anotações (requer display)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    cfg = Config.from_file(args.config)
    configure_logging(cfg.log_level)

    # Sobrescreve source da primeira câmera se passado por CLI
    if args.source is not None and cfg.cameras:
        cfg.cameras[0] = CameraConfig(
            **{**cfg.cameras[0].model_dump(), "source": args.source}
        )

    log.info("system_starting", cameras=len(cfg.cameras), zones=len(cfg.zones))

    # --- Módulos ---
    alarm = AlarmManager(cfg.alarm)
    health_monitor = HealthMonitor(cfg.health, cfg.alarm, on_event=alarm.handle)

    engine = RulesEngine(cfg.rules, cfg.zones, on_event=alarm.handle)
    engine.operation_active = args.operation_active

    detector = PersonDetector(
        model_path=cfg.detector.model_path,
        confidence=cfg.detector.confidence_threshold,
        iou=cfg.detector.iou_threshold,
        device=cfg.detector.device,
    )

    if not detector.available:
        alarm.handle(SafetyEvent(
            kind=EventKind.MODEL_UNAVAILABLE,
            severity=Severity.CRITICAL,
            camera_id=None, track_id=None, zone_id=None,
            message="Modelo não pôde ser carregado na inicialização.",
        ))

    # --- Câmeras ---
    camera_healths: dict[str, CameraHealth] = {}

    def on_health(h: CameraHealth) -> None:
        camera_healths[h.camera_id] = h
        if not h.online:
            alarm.handle(SafetyEvent(
                kind=EventKind.STREAM_LOST,
                severity=Severity.WARNING,
                camera_id=h.camera_id, track_id=None, zone_id=None,
                message=f"Stream da câmera {h.camera_id} perdido.",
            ))

    captures: list[CameraCapture] = []
    for cam_cfg in cfg.cameras:
        h = CameraHealth(camera_id=cam_cfg.camera_id, online=False, last_frame_ts=0.0)
        camera_healths[cam_cfg.camera_id] = h
        cap = CameraCapture(cam_cfg, on_health_change=on_health)
        captures.append(cap)

    for cap in captures:
        cap.start()

    # Emite SYSTEM_READY
    alarm.handle(SafetyEvent(
        kind=EventKind.SYSTEM_READY,
        severity=Severity.INFO,
        camera_id=None, track_id=None, zone_id=None,
        message="Sistema inicializado e monitorando.",
    ))

    # --- Graceful shutdown ---
    _running = True

    def _shutdown(sig: int, frame: object) -> None:
        nonlocal _running
        log.info("shutdown_requested", signal=sig)
        _running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # --- Loop principal ---
    last_health_tick = 0.0
    preview_enabled = args.show_preview

    try:
        while _running:
            # Processa um frame de cada câmera por iteração
            for cap in captures:
                frame = cap.get_frame(timeout=0.1)
                if frame is None:
                    continue

                # Sincroniza health da câmera
                h = camera_healths[frame.camera_id]
                h.last_frame_ts = frame.timestamp
                h.online = True

                # Inferência
                detections = detector.detect(frame.image, frame.camera_id)

                # Motor de regras
                engine.process(detections, frame.camera_id, frame=frame.image)

                # Preview opcional (debug / desenvolvimento)
                if preview_enabled:
                    _render_preview(frame, detections, cfg)

            # Tick de saúde
            now = time.monotonic()
            if now - last_health_tick >= cfg.health.heartbeat_interval_s:
                last_health_tick = now
                health_monitor.tick(
                    list(camera_healths.values()),
                    model_available=detector.available,
                    now=now,
                )

    finally:
        log.info("shutting_down")
        for cap in captures:
            cap.stop()
        if preview_enabled:
            try:
                import cv2  # type: ignore[import-untyped]
                cv2.destroyAllWindows()
            except Exception:
                pass

    log.info("system_stopped")
    return 0


def _render_preview(frame: object, detections: list, cfg: Config) -> None:
    """Desenha bounding boxes e zonas no frame (apenas para debug)."""
    try:
        import cv2  # type: ignore[import-untyped]
        import numpy as np
        from munck_safety.camera.capture import Frame as CamFrame

        if not isinstance(frame, CamFrame):
            return
        img = frame.image.copy()
        h, w = img.shape[:2]

        # Bounding boxes
        for det in detections:
            if det.camera_id != frame.camera_id:
                continue
            x1 = int(det.bbox.x1 * w)
            y1 = int(det.bbox.y1 * h)
            x2 = int(det.bbox.x2 * w)
            y2 = int(det.bbox.y2 * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                img, f"#{det.track_id} {det.confidence:.2f}",
                (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
            )
            # Ponto dos pés
            fx = int(det.bbox.foot_x * w)
            fy = int(det.bbox.foot_y * h)
            cv2.circle(img, (fx, fy), 5, (0, 0, 255), -1)

        # Zonas
        for z_cfg in cfg.zones:
            if z_cfg.camera_id != frame.camera_id:
                continue
            pts = np.array(
                [(int(p.x * w), int(p.y * h)) for p in z_cfg.points],
                dtype=np.int32,
            )
            cv2.polylines(img, [pts], isClosed=True, color=(255, 0, 0), thickness=2)
            cx = int(sum(p.x for p in z_cfg.points) / len(z_cfg.points) * w)
            cy = int(sum(p.y for p in z_cfg.points) / len(z_cfg.points) * h)
            cv2.putText(img, z_cfg.label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        cv2.imshow(f"Munck Safety — {frame.camera_id}", img)
        cv2.waitKey(1)

    except Exception as exc:
        log.warning("preview_error", error=str(exc))


if __name__ == "__main__":
    sys.exit(main())
