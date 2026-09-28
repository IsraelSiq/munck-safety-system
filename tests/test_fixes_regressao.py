"""Regressoes dos bugs corrigidos (engine, EPI, health, web, alarme)."""
from __future__ import annotations

import time

import pytest

from munck_safety.config import (
    AlarmConfig,
    CameraConfig,
    Config,
    HealthConfig,
    PPEZoneConfig,
)
from munck_safety.models import (
    EventKind,
    PPEDetection,
    PPEItem,
    SafetyEvent,
    Severity,
)
from munck_safety.ppe import PPEMonitor
from munck_safety.rules import RulesEngine
from munck_safety.rules import engine as engine_mod
from munck_safety.utils import HealthMonitor
from tests.conftest import make_detection


def _engine(rules_cfg, zone_cfg, events):
    eng = RulesEngine(rules_cfg, [zone_cfg], on_event=events.append)
    eng.operation_active = True
    return eng


class TestRulesEngineEstado:
    def test_estados_de_tracks_antigos_sao_descartados(
        self, rules_cfg, zone_cfg, monkeypatch
    ):
        events: list[SafetyEvent] = []
        eng = _engine(rules_cfg, zone_cfg, events)

        for tid in range(200):
            eng.process([make_detection(track_id=tid)], "cam_a")

        monkeypatch.setattr(engine_mod, "STATE_TTL_S", -1.0)
        eng.process([], "cam_a")

        assert eng._states[zone_cfg.zone_id] == {}

    def test_fim_de_operacao_emite_intrusion_end(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        eng = _engine(rules_cfg, zone_cfg, events)

        det = make_detection(track_id=7)
        for _ in range(rules_cfg.confirmation_frames):
            eng.process([det], "cam_a")
        assert any(e.kind == EventKind.INTRUSION_START for e in events)

        eng.operation_active = False

        kinds = [e.kind for e in events]
        assert EventKind.INTRUSION_END in kinds
        assert kinds.index(EventKind.INTRUSION_END) < kinds.index(
            EventKind.OPERATION_END
        ) + 2  # encerrada junto com o fim da operacao

    def test_process_retorna_ocupacao_por_zona(self, rules_cfg, zone_cfg):
        events: list[SafetyEvent] = []
        eng = _engine(rules_cfg, zone_cfg, events)

        dentro = make_detection(track_id=1, foot_x=0.5, foot_y=0.5)
        fora = make_detection(track_id=2, foot_x=0.05, foot_y=0.05)
        occ = eng.process([dentro, fora], "cam_a")

        assert occ == {zone_cfg.zone_id: {1}}


@pytest.fixture
def ppe_zone() -> PPEZoneConfig:
    return PPEZoneConfig(
        zone_id="z1", required_ppe=["HELMET"],
        confirmation_window_s=5.0, cooldown_s=30.0,
    )


def _ppe_det(track_id: int, camera_id: str = "cam_a") -> PPEDetection:
    return PPEDetection(
        camera_id=camera_id, track_id=track_id,
        detected=frozenset(), confidence={PPEItem.HELMET.value: 0.1},
    )


class TestPPEFiltragem:
    def test_ignora_deteccoes_de_outra_camera(self, ppe_zone):
        events: list[SafetyEvent] = []
        monitor = PPEMonitor([ppe_zone], on_event=events.append)

        outra = _ppe_det(1, camera_id="cam_b")
        monitor.process([outra], "z1", "cam_a", now=0.0)
        monitor.process([outra], "z1", "cam_a", now=10.0)

        assert events == []

    def test_so_avalia_tracks_dentro_da_zona(self, ppe_zone):
        events: list[SafetyEvent] = []
        monitor = PPEMonitor([ppe_zone], on_event=events.append)

        det = _ppe_det(1)
        monitor.process([det], "z1", "cam_a", now=0.0, track_ids=set())
        monitor.process([det], "z1", "cam_a", now=10.0, track_ids=set())
        assert events == []

        monitor.process([det], "z1", "cam_a", now=11.0, track_ids={1})
        monitor.process([det], "z1", "cam_a", now=20.0, track_ids={1})
        assert [e.kind for e in events] == [EventKind.PPE_NON_COMPLIANT]


class TestHealthDeduplicacao:
    def test_model_unavailable_nao_repete(self):
        events: list[SafetyEvent] = []
        monitor = HealthMonitor(
            HealthConfig(heartbeat_interval_s=60.0),
            AlarmConfig(),
            on_event=events.append,
        )
        now = time.monotonic()
        for i in range(5):
            monitor.tick([], model_available=False, now=now + i)

        model_events = [e for e in events if e.kind == EventKind.MODEL_UNAVAILABLE]
        assert len(model_events) == 1

        # Recuperou e caiu de novo → novo evento
        monitor.tick([], model_available=True, now=now + 10)
        monitor.tick([], model_available=False, now=now + 11)
        model_events = [e for e in events if e.kind == EventKind.MODEL_UNAVAILABLE]
        assert len(model_events) == 2


class TestConfigPPEZones:
    def _base(self) -> dict:
        return {
            "cameras": [{"camera_id": "cam_a", "source": "0"}],
            "zones": [{
                "zone_id": "z1", "camera_id": "cam_a",
                "points": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1},
                           {"x": 0.9, "y": 0.9}],
            }],
        }

    def test_ppe_zone_desconhecida_e_rejeitada(self):
        data = self._base()
        data["ppe_zones"] = [{"zone_id": "inexistente", "required_ppe": ["HELMET"]}]
        with pytest.raises(ValueError, match="EPI"):
            Config.from_dict(data)

    def test_ppe_zone_valida_e_aceita(self):
        data = self._base()
        data["ppe_zones"] = [{"zone_id": "z1", "required_ppe": ["HELMET"]}]
        assert Config.from_dict(data).ppe_zones[0].zone_id == "z1"


class TestWebServerNormalizacao:
    def test_normaliza_schema_canonico_e_legado(self):
        pytest.importorskip("flask")
        from munck_safety.web_server import normalize_event

        canonico = normalize_event({
            "ts": "2024-01-01T00:00:00Z", "kind": "INTRUSION_START",
            "zone_id": "z1", "camera_id": "cam_a", "message": "m",
        })
        assert canonico["event_type"] == "INTRUSION_START"
        assert canonico["zone"] == "z1"
        assert canonico["timestamp"] == "2024-01-01T00:00:00Z"

        legado = normalize_event({
            "timestamp": "t", "event_type": "HEARTBEAT", "zone": "z9",
        })
        assert legado["event_type"] == "HEARTBEAT"
        assert legado["zone"] == "z9"


class TestSnapshotPath:
    def test_snapshot_salvo_com_caminho_relativo(self, tmp_path):
        cv2 = pytest.importorskip("cv2")
        np = pytest.importorskip("numpy")
        from munck_safety.alarm import AlarmManager

        cfg = AlarmConfig(artifacts_dir=str(tmp_path), save_snapshots=True)
        mgr = AlarmManager(cfg)
        event = SafetyEvent(
            kind=EventKind.INTRUSION_START, severity=Severity.CRITICAL,
            camera_id="cam_a", track_id=1, zone_id="z1", message="m",
            frame=np.zeros((4, 4, 3), dtype="uint8"),
        )
        name = mgr._save_snapshot(event)

        assert name is not None
        assert "/" not in name
        assert (tmp_path / name).exists()
        assert cv2 is not None


def test_camera_config_import_ok():
    assert CameraConfig(camera_id="c", source="0").camera_id == "c"
