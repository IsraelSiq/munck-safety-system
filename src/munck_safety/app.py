"""
Ponto de entrada do Munck Safety System — Fase 2.

Fase 1: detecção de intrusão, motor de regras, health monitor.
Fase 2: detecção de EPI, monitor de conformidade, dashboard HTTP, SQLite.

Uso:
    python -m munck_safety.app --config config/example.json
    python -m munck_safety.app --config config/example.json --operation-active --show-preview
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from munck_safety.alarm import AlarmManager
from munck_safety.camera import CameraCapture
from munck_safety.config import CameraConfig, Config
from munck_safety.dashboard import DashboardServer, EventStore
from munck_safety.detector import PersonDetector
from munck_safety.logging_cfg import configure_logging, get_logger
from munck_safety.models import CameraHealth, EventKind, SafetyEvent, Severity
from munck_safety.ppe import PPEDetector, PPEMonitor
from munck_safety.rules import RulesEngine
from munck_safety.utils import HealthMonitor

log = get_logger(__name__)


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Munck Safety System — Fase 2")
    p.add_argument("--config", default="config/example.json")
    p.add_argument("--source", default=None,
                   help="Sobrescreve source da camera 0")
    p.add_argument("--operation-active", action="store_true")
    p.add_argument("--show-preview", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    cfg = Config.from_file(args.config)
    configure_logging(cfg.log_level)

    if args.source is not None and cfg.cameras:
        cfg.cameras[0] = CameraConfig(
            **{**cfg.cameras[0].model_dump(), "source": args.source}
        )

    log.info("system_starting", cameras=len(cfg.cameras), zones=len(cfg.zones),
             ppe_zones=len(cfg.ppe_zones))

    # --- Persistência e Dashboard ---
    store = EventStore(cfg.dashboard.db_path, cfg.dashboard.retention_days)
    store.purge_old()

    dashboard: DashboardServer | None = None
    if cfg.dashboard.enabled:
        dashboard = DashboardServer(store, cfg.dashboard, cfg.alarm.artifacts_dir)
        dashboard.start()

    # --- Alarme (agora com store) ---
    alarm = AlarmManager(cfg.alarm, store=store)
    health_monitor = HealthMonitor(cfg.health, cfg.alarm, on_event=alarm.handle)

    # --- Motor de regras de intrusão ---
    engine = RulesEngine(cfg.rules, cfg.zones, on_event=alarm.handle)
    engine.operation_active = args.operation_active

    # --- Detector de pessoas ---
    detector = PersonDetector(
        model_path=cfg.detector.model_path,
        confidence=cfg.detector.confidence_threshold,
        iou=cfg.detector.iou_threshold,
        device=cfg.detector.device,
    )
    if not detector.available:
        alarm.handle(SafetyEvent(
            kind=EventKind.MODEL_UNAVAILABLE, severity=Severity.CRITICAL,
            camera_id=None, track_id=None, zone_id=None,
            message="Modelo de pessoas nao carregado na inicializacao.",
        ))

    # --- Detector de EPI ---
    ppe_detector = PPEDetector(
        model_path=cfg.ppe_detector.model_path,
        confidence=cfg.ppe_detector.confidence_threshold,
        device=cfg.ppe_detector.device,
    ) if cfg.ppe_detector.enabled else None

    # --- Monitor de EPI ---
    ppe_monitor = PPEMonitor(cfg.ppe_zones, on_event=alarm.handle)

    # --- Câmeras ---
    camera_healths: dict[str, CameraHealth] = {}

    def on_health(h: CameraHealth) -> None:
        camera_healths[h.camera_id] = h
        if not h.online:
            alarm.handle(SafetyEvent(
                kind=EventKind.STREAM_LOST, severity=Severity.WARNING,
                camera_id=h.camera_id, track_id=None, zone_id=None,
                message=f"Stream da camera {h.camera_id} perdido.",
            ))

    captures: list[CameraCapture] = []
    for cam_cfg in cfg.cameras:
        h = CameraHealth(camera_id=cam_cfg.camera_id, online=False, last_frame_ts=0.0)
        camera_healths[cam_cfg.camera_id] = h
        cap = CameraCapture(cam_cfg, on_health_change=on_health)
        captures.append(cap)

    for cap in captures:
        cap.start()

    alarm.handle(SafetyEvent(
        kind=EventKind.SYSTEM_READY, severity=Severity.INFO,
        camera_id=None, track_id=None, zone_id=None,
        message="Sistema inicializado e monitorando.",
    ))

    _running = True

    def _shutdown(sig: int, frame: object) -> None:
        nonlocal _running
        log.info("shutdown_requested", signal=sig)
        _running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    last_health_tick = 0.0
    last_purge_ts = time.monotonic()
    PURGE_INTERVAL_S = 3600.0  # purge de eventos antigos a cada hora

    # Mapa de zonas por câmera para o EPI monitor
    cam_to_zones: dict[str, list[str]] = {}
    for z in cfg.zones:
        cam_to_zones.setdefault(z.camera_id, []).append(z.zone_id)

    try:
        while _running:
            for cap in captures:
                frame = cap.get_frame(timeout=0.1)
                if frame is None:
                    continue

                h = camera_healths[frame.camera_id]
                h.last_frame_ts = frame.timestamp
                h.online = True

                # --- Detecção de pessoas ---
                detections = detector.detect(frame.image, frame.camera_id)

                # --- Motor de intrusão ---
                engine.process(detections, frame.camera_id, frame=frame.image)

                # --- Detecção e monitoramento de EPI ---
                if ppe_detector is not None and detections:
                    ppe_results = ppe_detector.detect(
                        frame.image, detections, frame.camera_id
                    )
                    for zone_id in cam_to_zones.get(frame.camera_id, []):
                        ppe_monitor.process(
                            ppe_results, zone_id, frame.camera_id, frame=frame.image
                        )

                # --- Preview ---
                if args.show_preview:
                    _render_preview(frame, detections, cfg)

            now = time.monotonic()

            # Health tick
            if now - last_health_tick >= cfg.health.heartbeat_interval_s:
                last_health_tick = now
                health_monitor.tick(
                    list(camera_healths.values()),
                    model_available=detector.available,
                    now=now,
                )

            # Purge periódico
            if now - last_purge_ts >= PURGE_INTERVAL_S:
                last_purge_ts = now
                store.purge_old()

    finally:
        log.info("shutting_down")
        for cap in captures:
            cap.stop()
        if dashboard:
            dashboard.stop()
        if args.show_preview:
            try:
                import cv2  # type: ignore[import-untyped]
                cv2.destroyAllWindows()
            except Exception:
                pass

    log.info("system_stopped")
    return 0


def _render_preview(frame, detections: list, cfg: Config) -> None:
    try:
        import cv2  # type: ignore[import-untyped]
        import numpy as np
        from munck_safety.camera.capture import Frame as CamFrame

        if not isinstance(frame, CamFrame):
            return
        img = frame.image.copy()
        h, w = img.shape[:2]

        for det in detections:
            if det.camera_id != frame.camera_id:
                continue
            x1, y1 = int(det.bbox.x1 * w), int(det.bbox.y1 * h)
            x2, y2 = int(det.bbox.x2 * w), int(det.bbox.y2 * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(img, f"#{det.track_id} {det.confidence:.2f}",
                        (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.circle(img, (int(det.bbox.foot_x * w), int(det.bbox.foot_y * h)),
                       5, (0, 0, 255), -1)

        for z in cfg.zones:
            if z.camera_id != frame.camera_id:
                continue
            pts = np.array([(int(p.x * w), int(p.y * h)) for p in z.points], np.int32)
            cv2.polylines(img, [pts], True, (255, 0, 0), 2)
            cx = int(sum(p.x for p in z.points) / len(z.points) * w)
            cy = int(sum(p.y for p in z.points) / len(z.points) * h)
            cv2.putText(img, z.label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        cv2.imshow(f"Munck Safety — {frame.camera_id}", img)
        cv2.waitKey(1)
    except Exception as exc:
        log.warning("preview_error", error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
