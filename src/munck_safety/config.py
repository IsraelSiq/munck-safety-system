"""
Configuração do sistema via arquivo JSON validado por Pydantic.

Uso:
    cfg = Config.from_file("config/example.json")
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ZonePoint(BaseModel):
    x: Annotated[float, Field(ge=0.0, le=1.0)]
    y: Annotated[float, Field(ge=0.0, le=1.0)]


class ZoneConfig(BaseModel):
    zone_id: str
    camera_id: str
    label: str = "zona"
    points: list[ZonePoint]

    @field_validator("points")
    @classmethod
    def _min_points(cls, v: list[ZonePoint]) -> list[ZonePoint]:
        if len(v) < 3:
            raise ValueError("Uma zona precisa de ao menos 3 pontos.")
        return v


class CameraConfig(BaseModel):
    camera_id: str
    source: str
    width: int = 1280
    height: int = 720
    fps: int = 15
    reconnect_delay_s: float = 5.0
    max_failures: int = 10


class DetectorConfig(BaseModel):
    model_path: str = "yolo11n.pt"
    confidence_threshold: float = 0.45
    iou_threshold: float = 0.5
    device: str = "cpu"
    classes: list[int] = Field(default_factory=lambda: [0])


class RulesConfig(BaseModel):
    confirmation_frames: int = 3
    cooldown_s: float = 10.0
    hysteresis_frames: int = 5


class AlarmConfig(BaseModel):
    sound_file: Optional[str] = None
    volume: float = 1.0
    artifacts_dir: str = "artifacts"
    save_snapshots: bool = True
    disk_min_free_mb: float = 500.0


class HealthConfig(BaseModel):
    heartbeat_interval_s: float = 10.0
    camera_timeout_s: float = 5.0



# ---------------------------------------------------------------------------
# Fase 2 — Configuração de EPI
# ---------------------------------------------------------------------------

class PPEZoneConfig(BaseModel):
    """EPIs exigidos por zona. Ausência implica zona sem requisito de EPI."""
    zone_id: str
    required_ppe: list[str]                    # valores de PPEItem enum
    confirmation_window_s: float = 5.0        # janela para confirmar ausência
    cooldown_s: float = 30.0                   # cooldown entre violações do mesmo track


class PPEDetectorConfig(BaseModel):
    model_path: str = "yolo11n-ppe.pt"        # modelo especializado em EPI
    confidence_threshold: float = 0.40
    device: str = "cpu"
    enabled: bool = False                      # desabilitado até modelo disponível


class DashboardConfig(BaseModel):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    retention_days: int = 30                  # retenção de eventos no banco
    db_path: str = "artifacts/events.db"      # SQLite
    page_size: int = 50

class Config(BaseModel):
    cameras: list[CameraConfig]
    zones: list[ZoneConfig]
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    alarm: AlarmConfig = Field(default_factory=AlarmConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    log_level: str = "INFO"
    ppe_zones: list[PPEZoneConfig] = Field(default_factory=list)
    ppe_detector: PPEDetectorConfig = Field(default_factory=PPEDetectorConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)

    @model_validator(mode="after")
    def _validate_zone_cameras(self) -> "Config":
        known = {c.camera_id for c in self.cameras}
        for z in self.zones:
            if z.camera_id not in known:
                raise ValueError(
                    f"Zona '{z.zone_id}' referencia camera_id '{z.camera_id}' "
                    "que nao existe na lista de cameras."
                )
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls.model_validate(data)
