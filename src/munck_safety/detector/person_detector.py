"""
Detector de pessoas usando YOLO (ultralytics) com ByteTrack.

Responsabilidade única: receber frame numpy → retornar lista de Detection.
Nunca toma decisões de segurança.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from munck_safety.logging_cfg import get_logger
from munck_safety.models import BoundingBox, Detection

log = get_logger(__name__)


class PersonDetector:
    """Wrapper sobre YOLO com tracking por câmera."""

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence: float = 0.45,
        iou: float = 0.5,
        device: str = "cpu",
        person_class_id: int = 0,
    ) -> None:
        self._conf = confidence
        self._iou = iou
        self._device = device
        self._cls = person_class_id
        self._model = self._load_model(model_path)

    @property
    def available(self) -> bool:
        return self._model is not None

    def detect(self, frame: np.ndarray, camera_id: str) -> list[Detection]:
        """
        Executa inferência + tracking num frame BGR.

        Retorna lista de Detection (pode ser vazia).
        Nunca lança exceção — falhas são logadas e retornam lista vazia.
        """
        if self._model is None:
            log.error("model_unavailable", camera_id=camera_id)
            return []
        try:
            return self._run(frame, camera_id)
        except Exception as exc:
            log.exception("detection_error", camera_id=camera_id, error=str(exc))
            return []

    def _run(self, frame: np.ndarray, camera_id: str) -> list[Detection]:
        h, w = frame.shape[:2]
        ts = time.monotonic()

        results = self._model.track(
            frame,
            conf=self._conf,
            iou=self._iou,
            classes=[self._cls],
            device=self._device,
            persist=True,
            verbose=False,
        )

        detections: list[Detection] = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                if box.id is None:
                    continue
                track_id = int(box.id.item())
                conf = float(box.conf.item())
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                bbox = BoundingBox(
                    x1=x1 / w, y1=y1 / h, x2=x2 / w, y2=y2 / h,
                )
                detections.append(Detection(
                    camera_id=camera_id,
                    track_id=track_id,
                    bbox=bbox,
                    confidence=conf,
                    timestamp=ts,
                ))
        return detections

    def _load_model(self, model_path: str) -> Optional[object]:
        try:
            from ultralytics import YOLO  # type: ignore[import-untyped]
            model = YOLO(model_path)
            log.info("model_loaded", path=model_path, device=self._device)
            return model
        except Exception as exc:
            log.error("model_load_failed", path=model_path, error=str(exc))
            return None
