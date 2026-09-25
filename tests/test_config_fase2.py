"""
Testes de integração config Fase 2 — EPI e dashboard.
"""
from __future__ import annotations

import pytest
from munck_safety.config import Config


def _base_config() -> dict:
    return {
        "cameras": [{"camera_id": "cam_a", "source": "0"}],
        "zones": [
            {
                "zone_id": "z1", "camera_id": "cam_a",
                "points": [
                    {"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9},
                ],
            }
        ],
    }


class TestConfigFase2:
    def test_config_sem_ppe_valida(self):
        cfg = Config.from_dict(_base_config())
        assert cfg.ppe_zones == []
        assert cfg.ppe_detector.enabled is False

    def test_ppe_zone_valida(self):
        data = _base_config()
        data["ppe_zones"] = [{
            "zone_id": "z1",
            "required_ppe": ["HELMET", "VEST"],
            "confirmation_window_s": 5.0,
            "cooldown_s": 30.0,
        }]
        cfg = Config.from_dict(data)
        assert len(cfg.ppe_zones) == 1
        assert "HELMET" in cfg.ppe_zones[0].required_ppe

    def test_dashboard_defaults(self):
        cfg = Config.from_dict(_base_config())
        assert cfg.dashboard.port == 8080
        assert cfg.dashboard.retention_days == 30
        assert cfg.dashboard.enabled is True

    def test_dashboard_customizado(self):
        data = _base_config()
        data["dashboard"] = {"port": 9090, "retention_days": 7, "enabled": False,
                             "host": "127.0.0.1", "db_path": "artifacts/db.sqlite",
                             "page_size": 25}
        cfg = Config.from_dict(data)
        assert cfg.dashboard.port == 9090
        assert cfg.dashboard.retention_days == 7
        assert cfg.dashboard.enabled is False

    def test_ppe_detector_habilitado(self):
        data = _base_config()
        data["ppe_detector"] = {
            "model_path": "meu_modelo.pt",
            "confidence_threshold": 0.5,
            "device": "cuda",
            "enabled": True,
        }
        cfg = Config.from_dict(data)
        assert cfg.ppe_detector.enabled is True
        assert cfg.ppe_detector.device == "cuda"
