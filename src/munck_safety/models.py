"""
Modelos de dados centrais do Munck Safety System.

Todos os contratos entre módulos passam por aqui.
O motor de regras consome Detection; produz SafetyEvent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"


class EventKind(str, Enum):
    INTRUSION_START   = "INTRUSION_START"
    INTRUSION_END     = "INTRUSION_END"
    CAMERA_OFFLINE    = "CAMERA_OFFLINE"
    STREAM_LOST       = "STREAM_LOST"
    STORAGE_FULL      = "STORAGE_FULL"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    OPERATION_START   = "OPERATION_START"
    OPERATION_END     = "OPERATION_END"
    SYSTEM_READY      = "SYSTEM_READY"
    HEARTBEAT         = "HEARTBEAT"
    PPE_NON_COMPLIANT = "PPE_NON_COMPLIANT"
    PPE_COMPLIANT     = "PPE_COMPLIANT"


class HealthStatus(str, Enum):
    OK       = "OK"
    DEGRADED = "DEGRADED"
    FAILED   = "FAILED"


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def foot_x(self) -> float:
        return self.cx

    @property
    def foot_y(self) -> float:
        return self.y2


@dataclass(frozen=True, slots=True)
class Detection:
    camera_id: str
    track_id: int
    bbox: BoundingBox
    confidence: float
    timestamp: float = field(default_factory=time.monotonic)

    def foot_point(self) -> tuple[float, float]:
        return (self.bbox.foot_x, self.bbox.foot_y)


# ---------------------------------------------------------------------------
# Zona
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Zone:
    zone_id: str
    camera_id: str
    points: tuple[tuple[float, float], ...]
    label: str = "zona"

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError(f"Zona {self.zone_id} precisa de ao menos 3 pontos.")


# ---------------------------------------------------------------------------
# Evento de segurança
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SafetyEvent:
    kind: EventKind
    severity: Severity
    camera_id: Optional[str]
    track_id: Optional[int]
    zone_id: Optional[str]
    message: str
    timestamp: float = field(default_factory=time.time)
    frame: Optional[object] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Saúde
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CameraHealth:
    camera_id: str
    online: bool
    last_frame_ts: float
    consecutive_failures: int = 0


@dataclass(slots=True)
class SystemHealth:
    status: HealthStatus
    cameras: list[CameraHealth]
    disk_free_bytes: int
    model_available: bool
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Fase 2 — EPI (PPE)
# ---------------------------------------------------------------------------

class PPEItem(str, Enum):
    """EPI que pode ser exigido numa zona."""
    HELMET   = "HELMET"
    VEST     = "VEST"
    GLOVES   = "GLOVES"
    BOOTS    = "BOOTS"
    GOGGLES  = "GOGGLES"


@dataclass(frozen=True, slots=True)
class PPEDetection:
    """
    Resultado da detecção de EPI para um track_id.

    detected: conjunto de EPIs identificados como presentes.
    confidence: dict PPEItem → float (confiança por item).
    """
    camera_id: str
    track_id: int
    detected: frozenset[PPEItem]
    confidence: dict[str, float]
    timestamp: float = field(default_factory=time.monotonic)

    def missing(self, required: frozenset[PPEItem]) -> frozenset[PPEItem]:
        return required - self.detected


@dataclass(slots=True)
class PPEViolation:
    """
    Violação de EPI confirmada após janela temporal.

    Não dispara sirene — gera evidência e registro auditável.
    """
    track_id: int
    camera_id: str
    zone_id: str
    missing_items: frozenset[PPEItem]
    first_seen_ts: float
    confirmed_ts: float
    frame: Optional[object] = field(default=None, repr=False)
