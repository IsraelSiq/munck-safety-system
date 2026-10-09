"""
Gerenciador de alarmes e evidências.

- Alarme sonoro (arquivo .wav/.ogg ou beep sintético).
- Snapshot do frame no momento da intrusão.
- Log de eventos em JSONL auditável.
"""
from __future__ import annotations

import json
import threading
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

    def __init__(self, cfg: AlarmConfig, store=None) -> None:
        self._cfg = cfg
        self._store = store  # EventStore opcional (Fase 2)
        self._artifacts = Path(cfg.artifacts_dir)
        self._artifacts.mkdir(parents=True, exist_ok=True)
        self._log_path = self._artifacts / "events.jsonl"
        self._sound_backend = self._init_sound()

    def handle(self, event: SafetyEvent) -> None:
        self._log_event(event)
        snapshot_path: str | None = None
        if event.kind in _ALARM_KINDS:
            # Som em thread separada para não bloquear loop principal
            threading.Thread(target=self._play_alarm, daemon=True).start()
        if event.kind in _SNAPSHOT_KINDS and self._cfg.save_snapshots:
            snapshot_path = self._save_snapshot(event)
        if self._store is not None:
            try:
                self._store.save(event, snapshot_path)
            except Exception as exc:
                log.warning("store_save_error", error=str(exc))

    def _play_alarm(self) -> None:
        if self._sound_backend == "pygame":
            self._play_pygame()
        elif self._sound_backend == "winsound":
            self._play_winsound()
        else:
            print("\a", end="", flush=True)

    def _play_pygame(self) -> None:
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

    def _play_winsound(self) -> None:
        try:
            import winsound
            # Beep audível: 1000 Hz por 300ms, 3 vezes
            for _ in range(3):
                winsound.Beep(1000, 300)
        except Exception as exc:
            log.warning("alarm_winsound_error", error=str(exc))
            print("\a", end="", flush=True)

    def _save_snapshot(self, event: SafetyEvent) -> str | None:
        if event.frame is None:
            return None
        try:
            import cv2  # type: ignore[import-untyped]
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            cam = event.camera_id or "unknown"
            name = f"snapshot_{ts}_{cam}_{event.kind.value}.jpg"
            path = self._artifacts / name
            cv2.imwrite(str(path), event.frame)
            log.info("snapshot_saved", path=str(path))
            return name
        except Exception as exc:
            log.warning("snapshot_error", error=str(exc))
        return None

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

    def _init_sound(self) -> str:
        """Detecta o melhor backend de som disponível."""
        # Tenta pygame primeiro
        try:
            import pygame  # type: ignore[import-untyped]
            pygame.mixer.init()
            log.info("sound_backend", backend="pygame")
            return "pygame"
        except Exception:
            pass

        # Fallback: winsound (nativo no Windows, sem pip)
        try:
            import winsound  # type: ignore[import-untyped]
            log.info("sound_backend", backend="winsound")
            return "winsound"
        except ImportError:
            pass

        # Último recurso: beep de terminal
        log.warning("sound_backend", backend="terminal_beep",
                    hint="Instale pygame para alarme sonoro completo.")
        return "beep"
