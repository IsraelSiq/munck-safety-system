"""
Testes do monitor de EPI — Fase 2.

Validam os requisitos de conformidade:
- PPE_NON_COMPLIANT só dispara após janela temporal.
- PPE_NON_COMPLIANT não dispara sirene (severidade WARNING, não CRITICAL).
- PPE_COMPLIANT encerra o ciclo de violação.
- Cooldown evita flooding do mesmo track.
- Modelo indisponível (frozenset vazio) não gera violação (fail-safe).
- Zona sem configuração de EPI é ignorada.
"""
from __future__ import annotations

import time

import pytest

from munck_safety.config import PPEZoneConfig
from munck_safety.models import EventKind, PPEDetection, PPEItem, SafetyEvent, Severity
from munck_safety.ppe.monitor import PPEMonitor


REQUIRED = frozenset([PPEItem.HELMET, PPEItem.VEST])

def make_zone(zone_id="z1", window_s=5.0, cooldown_s=30.0) -> PPEZoneConfig:
    return PPEZoneConfig(
        zone_id=zone_id,
        required_ppe=[p.value for p in REQUIRED],
        confirmation_window_s=window_s,
        cooldown_s=cooldown_s,
    )


def make_ppe_det(
    track_id: int = 1,
    camera_id: str = "cam_a",
    items: frozenset[PPEItem] = REQUIRED,
) -> PPEDetection:
    return PPEDetection(
        camera_id=camera_id,
        track_id=track_id,
        detected=items,
        confidence={p.value: 0.9 for p in items},
    )


def make_monitor(events: list[SafetyEvent]) -> PPEMonitor:
    return PPEMonitor([make_zone()], on_event=events.append)


class TestPPECompliance:
    def test_todos_epis_presentes_sem_evento(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        det = make_ppe_det(items=REQUIRED)
        monitor.process([det], "z1", "cam_a", now=0.0)
        monitor.process([det], "z1", "cam_a", now=3.0)
        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert not ppe

    def test_epi_ausente_antes_da_janela_sem_evento(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        # Sem capacete
        det = make_ppe_det(items=frozenset([PPEItem.VEST]))
        monitor.process([det], "z1", "cam_a", now=0.0)
        monitor.process([det], "z1", "cam_a", now=3.0)  # 3s < 5s window
        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert not ppe, "Nao deve disparar antes da janela de confirmacao."

    def test_epi_ausente_apos_janela_gera_evento(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        det = make_ppe_det(items=frozenset([PPEItem.VEST]))  # sem HELMET
        monitor.process([det], "z1", "cam_a", now=0.0)
        monitor.process([det], "z1", "cam_a", now=6.0)  # 6s > 5s window
        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert len(ppe) == 1
        assert ppe[0].track_id == 1

    def test_violacao_severidade_warning_nao_critical(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        # frozenset vazio MAS com confidence indica modelo rodou sem achar EPI
        det = make_ppe_det(items=frozenset([PPEItem.VEST]))  # sem HELMET
        monitor.process([det], "z1", "cam_a", now=0.0)
        monitor.process([det], "z1", "cam_a", now=10.0)
        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert ppe, "Deve gerar evento de violacao."
        assert all(e.severity == Severity.WARNING for e in ppe), (
            "Violacao de EPI deve ser WARNING, nao CRITICAL (sem sirene)."
        )

    def test_conformidade_encerra_violacao_ativa(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        sem_epi = make_ppe_det(items=frozenset([PPEItem.VEST]))
        com_epi = make_ppe_det(items=REQUIRED)

        # Gera violação
        monitor.process([sem_epi], "z1", "cam_a", now=0.0)
        monitor.process([sem_epi], "z1", "cam_a", now=6.0)
        # Coloca EPI
        monitor.process([com_epi], "z1", "cam_a", now=7.0)

        compliant = [e for e in events if e.kind == EventKind.PPE_COMPLIANT]
        assert len(compliant) == 1

    def test_cooldown_bloqueia_segundo_evento(self):
        events: list[SafetyEvent] = []
        zone = make_zone(window_s=2.0, cooldown_s=30.0)
        monitor = PPEMonitor([zone], on_event=events.append)

        det_sem = make_ppe_det(items=frozenset([PPEItem.VEST]))  # sem HELMET
        det_com = make_ppe_det(items=REQUIRED)

        # Ciclo 1: gera violação
        monitor.process([det_sem], "z1", "cam_a", now=0.0)
        monitor.process([det_sem], "z1", "cam_a", now=3.0)
        # Resolve
        monitor.process([det_com], "z1", "cam_a", now=4.0)
        # Ciclo 2: inicia nova ausência mas cooldown ainda ativo (4s < 30s)
        monitor.process([det_sem], "z1", "cam_a", now=5.0)
        monitor.process([det_sem], "z1", "cam_a", now=8.0)

        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert len(ppe) == 1, "Segundo evento deve ser bloqueado por cooldown."


class TestPPEFailSafe:
    def test_modelo_indisponivel_nao_gera_violacao(self):
        """Detecção inconclusiva (sem items, sem confidence) não acusa."""
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        # Simula modelo indisponível: detected=frozenset(), confidence={}
        det = PPEDetection(
            camera_id="cam_a", track_id=1,
            detected=frozenset(), confidence={},
        )
        monitor.process([det], "z1", "cam_a", now=0.0)
        monitor.process([det], "z1", "cam_a", now=10.0)
        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert not ppe, "Modelo indisponivel nao deve gerar violacao (fail-safe)."

    def test_zona_sem_config_ignorada(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)  # só tem z1
        det = make_ppe_det(items=frozenset())
        monitor.process([det], "zona_inexistente", "cam_a", now=0.0)
        monitor.process([det], "zona_inexistente", "cam_a", now=10.0)
        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert not ppe


class TestPPEMultipleTracks:
    def test_dois_tracks_independentes(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        d1 = make_ppe_det(track_id=1, items=frozenset([PPEItem.VEST]))
        d2 = make_ppe_det(track_id=2, items=frozenset([PPEItem.VEST]))

        monitor.process([d1, d2], "z1", "cam_a", now=0.0)
        monitor.process([d1, d2], "z1", "cam_a", now=6.0)

        ppe = [e for e in events if e.kind == EventKind.PPE_NON_COMPLIANT]
        assert len(ppe) == 2
        assert {e.track_id for e in ppe} == {1, 2}
