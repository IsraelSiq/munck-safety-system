"""
Motor de regras de segurança — Fase 1.

Separa completamente a IA (detector) da lógica de segurança.
O detector informa o que vê; o motor decide o que fazer.

Mecanismos:
  1. Teste de ponto dos pés dentro de zona poligonal (Shapely).
  2. Confirmação temporal: N frames consecutivos antes de disparar.
  3. Cooldown: evita flooding do mesmo track_id.
  4. Histerese: M frames fora da zona antes de encerrar evento.
  5. Estado de operação: intrusão só é relevante com operação ativa.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from shapely.geometry import Point, Polygon

from munck_safety.config import RulesConfig, ZoneConfig
from munck_safety.logging_cfg import get_logger
from munck_safety.models import (
    Detection, EventKind, SafetyEvent, Severity, Zone,
)

log = get_logger(__name__)

EventCallback = Callable[[SafetyEvent], None]


@dataclass(slots=True)
class _TrackState:
    track_id: int
    zone_id: str
    confirm_count: int = 0
    outside_count: int = 0
    active: bool = False
    last_event_ts: float = 0.0


class RulesEngine:
    """Motor de regras determinístico e testável."""

    def __init__(
        self,
        cfg: RulesConfig,
        zones: list[ZoneConfig],
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self._cfg = cfg
        self._on_event = on_event
        self._zones: list[Zone] = self._build_zones(zones)
        self._polygons: dict[str, Polygon] = {
            z.zone_id: Polygon(z.points) for z in self._zones
        }
        self._states: dict[tuple[int, str], _TrackState] = {}
        self._operation_active: bool = False

    @property
    def operation_active(self) -> bool:
        return self._operation_active

    @operation_active.setter
    def operation_active(self, value: bool) -> None:
        if value != self._operation_active:
            self._operation_active = value
            kind = EventKind.OPERATION_START if value else EventKind.OPERATION_END
            self._emit(SafetyEvent(
                kind=kind, severity=Severity.INFO,
                camera_id=None, track_id=None, zone_id=None,
                message="Operacao iniciada." if value else "Operacao encerrada.",
            ))
            if not value:
                self._clear_all_active()

    def process(
        self,
        detections: list[Detection],
        camera_id: str,
        frame: Optional[object] = None,
    ) -> None:
        """
        Processa detecções de um frame de uma câmera.

        Deve ser chamado a cada frame mesmo se detections estiver vazio.
        """
        if not self._operation_active:
            return

        relevant_zones = [z for z in self._zones if z.camera_id == camera_id]
        if not relevant_zones:
            return

        for zone in relevant_zones:
            poly = self._polygons[zone.zone_id]
            tracks_in_zone = {
                d.track_id
                for d in detections
                if d.camera_id == camera_id and self._foot_in_zone(d, poly)
            }

            known_keys = [k for k in self._states if k[1] == zone.zone_id]
            for key in known_keys:
                if key[0] not in tracks_in_zone:
                    self._handle_exit(self._states[key], zone, camera_id, frame)

            for tid in tracks_in_zone:
                key = (tid, zone.zone_id)
                state = self._states.setdefault(
                    key, _TrackState(track_id=tid, zone_id=zone.zone_id)
                )
                self._handle_entry(state, zone, camera_id, frame)

    def _handle_entry(
        self,
        state: _TrackState,
        zone: Zone,
        camera_id: str,
        frame: Optional[object],
    ) -> None:
        state.outside_count = 0
        state.confirm_count += 1
        if state.active:
            return
        if state.confirm_count >= self._cfg.confirmation_frames:
            now = time.monotonic()
            if now - state.last_event_ts < self._cfg.cooldown_s:
                return
            state.active = True
            state.last_event_ts = now
            self._emit(SafetyEvent(
                kind=EventKind.INTRUSION_START,
                severity=Severity.CRITICAL,
                camera_id=camera_id,
                track_id=state.track_id,
                zone_id=zone.zone_id,
                message=(
                    f"Intrusao detectada: pessoa #{state.track_id} "
                    f"na zona '{zone.label}' (camera {camera_id})."
                ),
                frame=frame,
            ))

    def _handle_exit(
        self,
        state: _TrackState,
        zone: Zone,
        camera_id: str,
        frame: Optional[object],
    ) -> None:
        state.confirm_count = 0
        if not state.active:
            return
        state.outside_count += 1
        if state.outside_count >= self._cfg.hysteresis_frames:
            state.active = False
            state.outside_count = 0
            self._emit(SafetyEvent(
                kind=EventKind.INTRUSION_END,
                severity=Severity.INFO,
                camera_id=camera_id,
                track_id=state.track_id,
                zone_id=zone.zone_id,
                message=(
                    f"Intrusao encerrada: pessoa #{state.track_id} "
                    f"saiu da zona '{zone.label}' (camera {camera_id})."
                ),
                frame=frame,
            ))

    def _clear_all_active(self) -> None:
        for state in self._states.values():
            state.active = False
            state.confirm_count = 0
            state.outside_count = 0

    @staticmethod
    def _foot_in_zone(det: Detection, poly: Polygon) -> bool:
        fx, fy = det.foot_point()
        return bool(poly.contains(Point(fx, fy)))

    def _emit(self, event: SafetyEvent) -> None:
        log.info(
            "safety_event", kind=event.kind.value, severity=event.severity.value,
            camera_id=event.camera_id, track_id=event.track_id,
            zone_id=event.zone_id, message=event.message,
        )
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as exc:
                log.exception("event_callback_error", error=str(exc))

    @staticmethod
    def _build_zones(cfgs: list[ZoneConfig]) -> list[Zone]:
        zones = []
        for z in cfgs:
            points = tuple((p.x, p.y) for p in z.points)
            zones.append(Zone(
                zone_id=z.zone_id, camera_id=z.camera_id,
                points=points, label=z.label,
            ))
        return zones
