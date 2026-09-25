"""
Monitor de saúde do sistema.

Falha técnica NUNCA é silenciosa:
- CAMERA_OFFLINE por timeout de frame.
- MODEL_UNAVAILABLE se o detector falhar.
- STORAGE_FULL antes de esgotar o disco.
- HEARTBEAT periódico confirmando que o sistema está vivo.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import psutil

from munck_safety.config import AlarmConfig, HealthConfig
from munck_safety.logging_cfg import get_logger
from munck_safety.models import (
    CameraHealth, EventKind, HealthStatus,
    SafetyEvent, Severity, SystemHealth,
)

log = get_logger(__name__)

EventCallback = Callable[[SafetyEvent], None]


class HealthMonitor:
    """Monitoramento de saúde chamado periodicamente pelo loop principal."""

    def __init__(
        self,
        cfg: HealthConfig,
        alarm_cfg: AlarmConfig,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self._cfg = cfg
        self._alarm_cfg = alarm_cfg
        self._on_event = on_event
        self._last_heartbeat_ts: float = 0.0
        self._storage_warning_sent: bool = False

    def tick(
        self,
        cameras: list[CameraHealth],
        model_available: bool,
        now: Optional[float] = None,
    ) -> SystemHealth:
        ts = now if now is not None else time.monotonic()

        for cam in cameras:
            if cam.online and (ts - cam.last_frame_ts) > self._cfg.camera_timeout_s:
                cam.online = False
                self._emit(SafetyEvent(
                    kind=EventKind.CAMERA_OFFLINE, severity=Severity.WARNING,
                    camera_id=cam.camera_id, track_id=None, zone_id=None,
                    message=(f"Camera {cam.camera_id} sem frames ha "
                             f"{self._cfg.camera_timeout_s:.0f}s."),
                ))

        if not model_available:
            self._emit(SafetyEvent(
                kind=EventKind.MODEL_UNAVAILABLE, severity=Severity.CRITICAL,
                camera_id=None, track_id=None, zone_id=None,
                message="Modelo de deteccao indisponivel.",
            ))

        disk_bytes = self._free_disk_bytes()
        min_bytes = self._alarm_cfg.disk_min_free_mb * 1024 * 1024
        if disk_bytes < min_bytes:
            if not self._storage_warning_sent:
                self._storage_warning_sent = True
                self._emit(SafetyEvent(
                    kind=EventKind.STORAGE_FULL, severity=Severity.WARNING,
                    camera_id=None, track_id=None, zone_id=None,
                    message=(f"Espaco em disco critico: "
                             f"{disk_bytes / (1024**2):.0f} MB livres."),
                ))
        else:
            self._storage_warning_sent = False

        if ts - self._last_heartbeat_ts >= self._cfg.heartbeat_interval_s:
            self._last_heartbeat_ts = ts
            n_online = sum(1 for c in cameras if c.online)
            self._emit(SafetyEvent(
                kind=EventKind.HEARTBEAT, severity=Severity.INFO,
                camera_id=None, track_id=None, zone_id=None,
                message=f"Sistema operacional. Cameras online: {n_online}/{len(cameras)}.",
            ))

        status = self._compute_status(cameras, model_available)
        return SystemHealth(
            status=status, cameras=cameras,
            disk_free_bytes=disk_bytes, model_available=model_available,
        )

    @staticmethod
    def _free_disk_bytes() -> int:
        try:
            return psutil.disk_usage("/").free
        except Exception:
            return 0

    @staticmethod
    def _compute_status(cameras: list[CameraHealth], model_available: bool) -> HealthStatus:
        if not model_available:
            return HealthStatus.FAILED
        all_offline = all(not c.online for c in cameras) if cameras else True
        if all_offline:
            return HealthStatus.FAILED
        if any(not c.online for c in cameras):
            return HealthStatus.DEGRADED
        return HealthStatus.OK

    def _emit(self, event: SafetyEvent) -> None:
        log.info("health_event", kind=event.kind.value,
                 severity=event.severity.value, message=event.message)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as exc:
                log.exception("health_callback_error", error=str(exc))
