"""
Monitor de conformidade de EPI — Fase 2.

Responsabilidade: receber PPEDetection, cruzar com requisitos da zona,
confirmar ausência por janela temporal e emitir PPE_NON_COMPLIANT.

Decisões de design:
  - PPE_NON_COMPLIANT NÃO dispara sirene — apenas evidência e log.
  - Confirmação por janela temporal (não por frames) porque EPI pode
    desaparecer momentaneamente por oclusão sem ser violação real.
  - Cooldown por (track_id, zone_id) evita flooding de eventos.
  - Inconclusivo (modelo indisponível) → não gera evento (fail-safe).
  - Retorno à conformidade emite PPE_COMPLIANT para fechar o ciclo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from munck_safety.config import PPEZoneConfig
from munck_safety.logging_cfg import get_logger
from munck_safety.models import (
    EventKind, PPEDetection, PPEItem, PPEViolation,
    SafetyEvent, Severity,
)

log = get_logger(__name__)

EventCallback = Callable[[SafetyEvent], None]


@dataclass(slots=True)
class _PPETrackState:
    """Estado de conformidade de EPI de um track numa zona."""
    track_id: int
    zone_id: str
    # Quando a ausência de EPI foi vista pela primeira vez (monotonic)
    first_missing_ts: Optional[float] = None
    # EPIs ausentes confirmados no último ciclo
    current_missing: frozenset[PPEItem] = field(default_factory=frozenset)
    # Violação ativa (evento já emitido)
    violation_active: bool = False
    # Timestamp do último evento emitido
    last_event_ts: float = -999999.0  # valor antigo o suficiente para nunca bloquear o primeiro evento


class PPEMonitor:
    """
    Monitor de conformidade de EPI por zona.

    Uso:
        monitor = PPEMonitor(ppe_zone_cfgs, on_event=callback)
        # a cada frame com detecções de EPI:
        monitor.process(ppe_detections, zone_id, camera_id, frame)
        # quando track sai da câmera/zona:
        monitor.clear_track(track_id, zone_id)
    """

    def __init__(
        self,
        ppe_zones: list[PPEZoneConfig],
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self._on_event = on_event
        # zone_id → {required: frozenset, cooldown_s, window_s}
        self._zone_cfg: dict[str, PPEZoneConfig] = {z.zone_id: z for z in ppe_zones}
        self._required: dict[str, frozenset[PPEItem]] = {
            z.zone_id: frozenset(PPEItem(p) for p in z.required_ppe)
            for z in ppe_zones
        }
        # (track_id, zone_id) → _PPETrackState
        self._states: dict[tuple[int, str], _PPETrackState] = {}

    def process(
        self,
        ppe_detections: list[PPEDetection],
        zone_id: str,
        camera_id: str,
        frame: Optional[object] = None,
        now: Optional[float] = None,
    ) -> None:
        """
        Avalia conformidade de EPI para as pessoas numa zona.

        ppe_detections: saída do PPEDetector para o frame atual.
        zone_id: zona onde as pessoas estão.
        """
        if zone_id not in self._zone_cfg:
            return  # zona sem requisito de EPI

        required = self._required[zone_id]
        if not required:
            return

        cfg = self._zone_cfg[zone_id]
        ts = now if now is not None else time.monotonic()

        present_track_ids = {d.track_id for d in ppe_detections}

        # Tracks que saíram da zona → limpar estado
        stale = [k for k in self._states if k[1] == zone_id and k[0] not in present_track_ids]
        for key in stale:
            self._resolve_if_active(self._states[key], zone_id, camera_id, frame)
            del self._states[key]

        for det in ppe_detections:
            if det.camera_id != camera_id:
                continue

            key = (det.track_id, zone_id)
            state = self._states.setdefault(
                key, _PPETrackState(track_id=det.track_id, zone_id=zone_id)
            )

            # Se o modelo não retornou itens (inconclusivo), não processa
            if not det.detected and not det.confidence:
                # Detector indisponível — mantém estado atual, não acusa
                continue

            missing = det.missing(required)

            if not missing:
                # Em conformidade — encerra violação ativa se havia
                state.first_missing_ts = None
                state.current_missing = frozenset()
                if state.violation_active:
                    state.violation_active = False
                    self._emit(SafetyEvent(
                        kind=EventKind.PPE_COMPLIANT,
                        severity=Severity.INFO,
                        camera_id=camera_id,
                        track_id=det.track_id,
                        zone_id=zone_id,
                        message=(
                            f"Pessoa #{det.track_id} em conformidade de EPI "
                            f"na zona '{zone_id}'."
                        ),
                        frame=frame,
                    ))
            else:
                state.current_missing = missing
                if state.first_missing_ts is None:
                    state.first_missing_ts = ts
                    log.debug("ppe_missing_started",
                              track_id=det.track_id, zone_id=zone_id,
                              missing=[m.value for m in missing])
                    continue

                elapsed = ts - state.first_missing_ts
                if elapsed >= cfg.confirmation_window_s:
                    if not state.violation_active:
                        # Cooldown
                        if ts - state.last_event_ts < cfg.cooldown_s:
                            continue
                        state.violation_active = True
                        state.last_event_ts = ts
                        missing_names = ", ".join(sorted(m.value for m in missing))
                        self._emit(SafetyEvent(
                            kind=EventKind.PPE_NON_COMPLIANT,
                            severity=Severity.WARNING,
                            camera_id=camera_id,
                            track_id=det.track_id,
                            zone_id=zone_id,
                            message=(
                                f"EPI ausente: pessoa #{det.track_id} sem "
                                f"{missing_names} na zona '{zone_id}' "
                                f"ha {elapsed:.1f}s."
                            ),
                            frame=frame,
                        ))

    def clear_track(self, track_id: int, zone_id: str, camera_id: str = "",
                    frame: Optional[object] = None) -> None:
        """Chamado quando um track sai da zona ou câmera."""
        key = (track_id, zone_id)
        if key in self._states:
            self._resolve_if_active(self._states[key], zone_id, camera_id, frame)
            del self._states[key]

    def _resolve_if_active(
        self,
        state: _PPETrackState,
        zone_id: str,
        camera_id: str,
        frame: Optional[object],
    ) -> None:
        if state.violation_active:
            state.violation_active = False
            self._emit(SafetyEvent(
                kind=EventKind.PPE_COMPLIANT,
                severity=Severity.INFO,
                camera_id=camera_id,
                track_id=state.track_id,
                zone_id=zone_id,
                message=f"Pessoa #{state.track_id} saiu da zona '{zone_id}' (EPI: encerrado).",
                frame=frame,
            ))

    def _emit(self, event: SafetyEvent) -> None:
        log.info("ppe_event", kind=event.kind.value, severity=event.severity.value,
                 camera_id=event.camera_id, track_id=event.track_id,
                 zone_id=event.zone_id, message=event.message)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as exc:
                log.exception("ppe_callback_error", error=str(exc))
