"""Fixtures compartilhadas."""
from __future__ import annotations

import pytest

from munck_safety.config import RulesConfig, ZoneConfig, ZonePoint
from munck_safety.models import BoundingBox, Detection


# ---------------------------------------------------------------------------
# Config padrão para testes
# ---------------------------------------------------------------------------

@pytest.fixture
def rules_cfg() -> RulesConfig:
    return RulesConfig(confirmation_frames=3, cooldown_s=5.0, hysteresis_frames=3)


@pytest.fixture
def zone_cfg() -> ZoneConfig:
    """Zona quadrada cobrindo x=[0.2,0.8] y=[0.2,0.8] na câmera 'cam_a'."""
    return ZoneConfig(
        zone_id="zona_teste",
        camera_id="cam_a",
        label="Zona Teste",
        points=[
            ZonePoint(x=0.2, y=0.2),
            ZonePoint(x=0.8, y=0.2),
            ZonePoint(x=0.8, y=0.8),
            ZonePoint(x=0.2, y=0.8),
        ],
    )


# ---------------------------------------------------------------------------
# Helpers para criar detecções
# ---------------------------------------------------------------------------

def make_detection(
    camera_id: str = "cam_a",
    track_id: int = 1,
    foot_x: float = 0.5,
    foot_y: float = 0.7,
    confidence: float = 0.9,
) -> Detection:
    """
    Cria uma Detection com o ponto dos pés em (foot_x, foot_y).
    A bbox é ajustada para que foot_x/foot_y coincidam com cx/y2.
    """
    half_w = 0.05
    half_h = 0.15
    return Detection(
        camera_id=camera_id,
        track_id=track_id,
        bbox=BoundingBox(
            x1=foot_x - half_w,
            y1=foot_y - half_h * 2,
            x2=foot_x + half_w,
            y2=foot_y,              # y2 = foot_y
        ),
        confidence=confidence,
    )
