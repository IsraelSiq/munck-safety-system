"""
Testes do motor de regras de segurança.

Cada teste valida um requisito de comportamento explícito da Fase 1.
Nomenclatura: test_<contexto>_<resultado esperado>
"""
from __future__ import annotations

import time

import pytest

from munck_safety.config import RulesConfig, ZoneConfig
from munck_safety.models import EventKind, SafetyEvent, Severity
from munck_safety.rules.engine import RulesEngine
from tests.conftest import make_detection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_engine(
    rules_cfg: RulesConfig,
    zone_cfg: ZoneConfig,
    events: list[SafetyEvent] | None = None,
) -> RulesEngine:
    captured: list[SafetyEvent] = events if events is not None else []
    return RulesEngine(rules_cfg, [zone_cfg], on_event=captured.append)


def process_n_times(engine: RulesEngine, detections: list, camera_id: str, n: int) -> None:
    for _ in range(n):
        engine.process(detections, camera_id)


# ---------------------------------------------------------------------------
# Estado de operação
# ---------------------------------------------------------------------------

class TestOperationState:
    def test_sem_operacao_ativa_nao_gera_intrusao(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = False

        det = make_detection(foot_x=0.5, foot_y=0.5)  # dentro da zona
        process_n_times(engine, [det], "cam_a", 10)

        intrusions = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert not intrusions, "Não deve gerar intrusão sem operação ativa."

    def test_operacao_ativa_gera_evento_operation_start(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        op_starts = [e for e in events if e.kind == EventKind.OPERATION_START]
        assert len(op_starts) == 1

    def test_operacao_encerrada_gera_evento_operation_end(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True
        engine.operation_active = False

        op_ends = [e for e in events if e.kind == EventKind.OPERATION_END]
        assert len(op_ends) == 1


# ---------------------------------------------------------------------------
# Confirmação temporal
# ---------------------------------------------------------------------------

class TestConfirmation:
    def test_intrusao_confirmada_apos_n_frames(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        det = make_detection(foot_x=0.5, foot_y=0.5)  # dentro

        # N-1 frames: ainda não confirma
        process_n_times(engine, [det], "cam_a", rules_cfg.confirmation_frames - 1)
        intrusions = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert not intrusions, "Não deve confirmar antes de N frames."

        # N-ésimo frame: confirma
        engine.process([det], "cam_a")
        intrusions = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert len(intrusions) == 1, "Deve confirmar exatamente no N-ésimo frame."

    def test_pé_fora_da_zona_nao_gera_intrusao(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        det = make_detection(foot_x=0.05, foot_y=0.05)  # fora da zona
        process_n_times(engine, [det], "cam_a", 10)

        intrusions = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert not intrusions

    def test_frame_vazio_nao_gera_intrusao(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        process_n_times(engine, [], "cam_a", 10)

        intrusions = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert not intrusions


# ---------------------------------------------------------------------------
# Encerramento de evento (histerese)
# ---------------------------------------------------------------------------

class TestHysteresis:
    def test_intrusao_encerrada_apos_m_frames_fora(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        inside = make_detection(foot_x=0.5, foot_y=0.5)
        outside = make_detection(foot_x=0.05, foot_y=0.05)  # fora

        # Confirma intrusão
        process_n_times(engine, [inside], "cam_a", rules_cfg.confirmation_frames)
        assert any(e.kind == EventKind.INTRUSION_START for e in events)

        # M-1 frames fora: ainda ativo
        process_n_times(engine, [outside], "cam_a", rules_cfg.hysteresis_frames - 1)
        ends = [e for e in events if e.kind == EventKind.INTRUSION_END]
        assert not ends, "Não deve encerrar antes de M frames fora."

        # M-ésimo frame fora: encerra
        engine.process([outside], "cam_a")
        ends = [e for e in events if e.kind == EventKind.INTRUSION_END]
        assert len(ends) == 1

    def test_reentrada_antes_de_m_frames_nao_encerra(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        inside = make_detection(foot_x=0.5, foot_y=0.5)
        outside = make_detection(foot_x=0.05, foot_y=0.05)

        process_n_times(engine, [inside], "cam_a", rules_cfg.confirmation_frames)

        # Sai brevemente e volta
        process_n_times(engine, [outside], "cam_a", rules_cfg.hysteresis_frames - 1)
        process_n_times(engine, [inside], "cam_a", 1)

        ends = [e for e in events if e.kind == EventKind.INTRUSION_END]
        assert not ends, "Reentrada antes de M frames deve cancelar encerramento."


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_segundo_evento_bloqueado_durante_cooldown(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        inside = make_detection(foot_x=0.5, foot_y=0.5)
        outside = make_detection(foot_x=0.05, foot_y=0.05)

        # Ciclo completo (entrada → saída)
        process_n_times(engine, [inside], "cam_a", rules_cfg.confirmation_frames)
        process_n_times(engine, [outside], "cam_a", rules_cfg.hysteresis_frames)

        assert len([e for e in events if e.kind == EventKind.INTRUSION_START]) == 1

        # Reentra imediatamente — cooldown ainda ativo
        process_n_times(engine, [inside], "cam_a", rules_cfg.confirmation_frames)

        starts = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert len(starts) == 1, "Segundo INTRUSION_START deve ser bloqueado por cooldown."


# ---------------------------------------------------------------------------
# Múltiplos tracks
# ---------------------------------------------------------------------------

class TestMultipleTracks:
    def test_dois_tracks_independentes(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        d1 = make_detection(track_id=1, foot_x=0.4, foot_y=0.5)
        d2 = make_detection(track_id=2, foot_x=0.6, foot_y=0.5)

        process_n_times(engine, [d1, d2], "cam_a", rules_cfg.confirmation_frames)

        starts = [e for e in events if e.kind == EventKind.INTRUSION_START]
        track_ids = {e.track_id for e in starts}
        assert 1 in track_ids
        assert 2 in track_ids

    def test_track_diferente_nao_interfere_no_cooldown(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        d1 = make_detection(track_id=1, foot_x=0.4, foot_y=0.5)
        d2 = make_detection(track_id=2, foot_x=0.6, foot_y=0.5)

        # Track 1 dispara
        process_n_times(engine, [d1], "cam_a", rules_cfg.confirmation_frames)
        # Track 2 também deve disparar (cooldown é por track)
        process_n_times(engine, [d2], "cam_a", rules_cfg.confirmation_frames)

        starts = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert len(starts) == 2


# ---------------------------------------------------------------------------
# Câmera errada
# ---------------------------------------------------------------------------

class TestCameraScope:
    def test_zona_de_outra_camera_ignorada(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        engine = make_engine(rules_cfg, zone_cfg, events)
        engine.operation_active = True

        # Detecção na cam_b, mas a zona está na cam_a
        det = make_detection(camera_id="cam_b", foot_x=0.5, foot_y=0.5)
        process_n_times(engine, [det], "cam_b", 10)

        intrusions = [e for e in events if e.kind == EventKind.INTRUSION_START]
        assert not intrusions
