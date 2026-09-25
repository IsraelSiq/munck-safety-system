"""
Gerenciador de alarmes e evidências.

- Alarme sonoro (arquivo .wav/.ogg ou beep sintético).
- Snapshot do frame no momento da intrusão.
- Log de eventos em JSONL auditável.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from munck_safety.config import AlarmConfig
from munck_safety.logging_cfg import get_logger
from munck_safety.models import EventKind, SafetyEvent

log = get_logger(__name__)

_ALARM_KINDS = {EventKind.INTRUSION_START}
_SNAPSHOT_KINDS = {EventKind.INTRUSION_START, EventKind.MODEL_UNAVAILABLE}


class AlarmManager:
    """Processa SafetyEvent e executa resposta (som + evidência)."""

    def __init__(self, cfg: AlarmConfig) -> None:
        self._cfg = cfg
        self._artifacts = Path(cfg.artifacts_dir)
        self._artifacts.mkdir(parents=True, exist_ok=True)
        self._log_path = self._artifacts / "events.jsonl"
        self._pygame_ready = self._init_pygame()

    def handle(self, event: SafetyEvent) -> None:
        self._log_event(event)
        if event.kind in _ALARM_KINDS:
            self._play_alarm()
        if event.kind in _SNAPSHOT_KINDS and self._cfg.save_snapshots:
            self._save_snapshot(event)

    def _play_alarm(self) -> None:
        if self._pygame_ready:
            self._play_file_alarm()
        else:
            print("\a", end="", flush=True)

    def _play_file_alarm(self) -> None:
        try:
            import pygame  # type: ignore[import-untyped]
            if self._cfg.sound_file and Path(self._cfg.sound_file).exists():
                sound = pygame.mixer.Sound(self._cfg.sound_file)
                sound.set_volume(self._cfg.volume)
                sound.play()
            else:
                print("\a", end="", flush=True)
        except Exception as exc:
            log.warning("alarm_sound_error", error=str(exc))

    def _save_snapshot(self, event: SafetyEvent) -> None:
        if event.frame is None:
            return
        try:
            import cv2  # type: ignore[import-untyped]
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            cam = event.camera_id or "unknown"
            fname = self._artifacts / f"snapshot_{ts}_{cam}_{event.kind.value}.jpg"
            cv2.imwrite(str(fname), event.frame)
            log.info("snapshot_saved", path=str(fname))
        except Exception as exc:
            log.warning("snapshot_error", error=str(exc))

    def _log_event(self, event: SafetyEvent) -> None:
        record = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "kind": event.kind.value,
            "severity": event.severity.value,
            "camera_id": event.camera_id,
            "track_id": event.track_id,
            "zone_id": event.zone_id,
            "message": event.message,
        }
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.warning("event_log_error", error=str(exc))

    def _init_pygame(self) -> bool:
        try:
            import pygame  # type: ignore[import-untyped]
            pygame.mixer.init()
            return True
        except Exception:
            log.warning("pygame_unavailable",
                        hint="Alarme sonoro degradado para beep de terminal.")
            return False
