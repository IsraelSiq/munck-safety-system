"""Testes de configuração e modelos de dados."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from munck_safety.config import Config
from munck_safety.models import BoundingBox, Detection, Zone


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def _minimal_config(self) -> dict:
        return {
            "cameras": [{"camera_id": "cam_a", "source": "0"}],
            "zones": [
                {
                    "zone_id": "z1",
                    "camera_id": "cam_a",
                    "points": [
                        {"x": 0.1, "y": 0.1},
                        {"x": 0.9, "y": 0.1},
                        {"x": 0.9, "y": 0.9},
                        {"x": 0.1, "y": 0.9},
                    ],
                }
            ],
        }

    def test_config_valida_carrega(self):
        cfg = Config.from_dict(self._minimal_config())
        assert len(cfg.cameras) == 1
        assert len(cfg.zones) == 1

    def test_zona_com_camera_inexistente_falha(self):
        data = self._minimal_config()
        data["zones"][0]["camera_id"] = "cam_inexistente"
        with pytest.raises(Exception):
            Config.from_dict(data)

    def test_zona_com_menos_de_3_pontos_falha(self):
        data = self._minimal_config()
        data["zones"][0]["points"] = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}]
        with pytest.raises(Exception):
            Config.from_dict(data)

    def test_from_file(self, tmp_path: Path):
        data = self._minimal_config()
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        cfg = Config.from_file(p)
        assert cfg.cameras[0].camera_id == "cam_a"

    def test_config_example_json_valido(self):
        example = Path("config/example.json")
        if example.exists():
            cfg = Config.from_file(example)
            assert len(cfg.cameras) == 4
            assert len(cfg.zones) == 4


# ---------------------------------------------------------------------------
# BoundingBox
# ---------------------------------------------------------------------------

class TestBoundingBox:
    def test_foot_point_centro_inferior(self):
        bbox = BoundingBox(x1=0.2, y1=0.1, x2=0.6, y2=0.9)
        assert bbox.foot_x == pytest.approx(0.4)
        assert bbox.foot_y == pytest.approx(0.9)

    def test_centro(self):
        bbox = BoundingBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0)
        assert bbox.cx == pytest.approx(0.5)
        assert bbox.cy == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------

class TestZone:
    def test_zona_valida(self):
        z = Zone(
            zone_id="z1",
            camera_id="cam_a",
            points=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
        )
        assert z.zone_id == "z1"

    def test_zona_com_menos_de_3_pontos_levanta(self):
        with pytest.raises(ValueError):
            Zone(
                zone_id="z_ruim",
                camera_id="cam_a",
                points=((0.1, 0.1), (0.9, 0.9)),
            )
