"""
Detector de EPI (PPE) — Fase 2.

Responsabilidade: dado um frame e uma lista de track_ids presentes,
retornar PPEDetection por track com os EPIs identificados.

Fase 2 usa um modelo YOLO especializado (ex: PPE-detection).
Se o modelo não estiver disponível, retorna detecções vazias — o
monitor de EPI trata ausência de detecção como inconclusivo, não
como violação. Isso é fail-safe: dúvida não dispara evento.

Estratégia de fallback:
  - Modelo disponível → inferência real.
  - Modelo indisponível → PPEDetection(detected=frozenset()) por track.
    O PPEMonitor aguarda CONFIRMATION_WINDOW_S antes de registrar ausência,
    então uma indisponibilidade momentânea não gera falso positivo.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from munck_safety.logging_cfg import get_logger
from munck_safety.models import BoundingBox, Detection, PPEDetection, PPEItem

log = get_logger(__name__)

# Mapeamento de classe YOLO → PPEItem (ajuste conforme seu modelo)
# Referência: dataset Safety-Helmet-Wearing (Kaggle) ou similar
_CLASS_TO_PPE: dict[int, PPEItem] = {
    0: PPEItem.HELMET,
    1: PPEItem.VEST,
    2: PPEItem.GLOVES,
    3: PPEItem.BOOTS,
    4: PPEItem.GOGGLES,
}


class PPEDetector:
    """
    Detecta EPIs para cada pessoa rastreada num frame.

    Associa detecções de EPI a track_ids por sobreposição de bounding box
    (IoU entre a bbox da pessoa e a bbox do EPI detectado).
    """

    def __init__(
        self,
        model_path: str = "yolo11n-ppe.pt",
        confidence: float = 0.40,
        device: str = "cpu",
    ) -> None:
        self._conf = confidence
        self._device = device
        self._model = self._load_model(model_path)

    @property
    def available(self) -> bool:
        return self._model is not None

    def detect(
        self,
        frame: np.ndarray,
        person_detections: list[Detection],
        camera_id: str,
    ) -> list[PPEDetection]:
        """
        Retorna uma PPEDetection por pessoa presente no frame.

        Nunca lança exceção. Se o modelo falhar, retorna lista com
        PPEDetection(detected=frozenset()) para cada track — o monitor
        trata como inconclusivo.
        """
        if not person_detections:
            return []

        if self._model is None:
            return [
                PPEDetection(
                    camera_id=camera_id,
                    track_id=d.track_id,
                    detected=frozenset(),
                    confidence={},
                )
                for d in person_detections
                if d.camera_id == camera_id
            ]

        try:
            return self._run(frame, person_detections, camera_id)
        except Exception as exc:
            log.exception("ppe_detection_error", camera_id=camera_id, error=str(exc))
            return [
                PPEDetection(
                    camera_id=camera_id,
                    track_id=d.track_id,
                    detected=frozenset(),
                    confidence={},
                )
                for d in person_detections
                if d.camera_id == camera_id
            ]

    def _run(
        self,
        frame: np.ndarray,
        person_detections: list[Detection],
        camera_id: str,
    ) -> list[PPEDetection]:
        h, w = frame.shape[:2]
        ts = time.monotonic()

        results = self._model(frame, conf=self._conf, device=self._device, verbose=False)

        # Agrupa EPIs detectados por classe
        ppe_boxes: list[tuple[PPEItem, BoundingBox, float]] = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0].item())
                ppe_item = _CLASS_TO_PPE.get(cls_id)
                if ppe_item is None:
                    continue
                conf = float(box.conf[0].item())
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                ppe_boxes.append((
                    ppe_item,
                    BoundingBox(x1=x1/w, y1=y1/h, x2=x2/w, y2=y2/h),
                    conf,
                ))

        # Associa EPIs a pessoas por IoU
        result_list: list[PPEDetection] = []
        for det in person_detections:
            if det.camera_id != camera_id:
                continue
            detected: dict[PPEItem, float] = {}
            for ppe_item, ppe_bbox, conf in ppe_boxes:
                if _iou(det.bbox, ppe_bbox) > 0.1:
                    # Mantém maior confiança se item aparecer mais de uma vez
                    if ppe_item not in detected or conf > detected[ppe_item]:
                        detected[ppe_item] = conf
            result_list.append(PPEDetection(
                camera_id=camera_id,
                track_id=det.track_id,
                detected=frozenset(detected.keys()),
                confidence={k.value: v for k, v in detected.items()},
                timestamp=ts,
            ))

        return result_list

    def _load_model(self, model_path: str) -> Optional[object]:
        try:
            from ultralytics import YOLO  # type: ignore[import-untyped]
            model = YOLO(model_path)
            log.info("ppe_model_loaded", path=model_path, device=self._device)
            return model
        except Exception as exc:
            log.warning("ppe_model_unavailable", path=model_path, error=str(exc),
                        hint="PPE detector rodando sem modelo — eventos PPE desabilitados.")
            return None


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    """Intersection over Union entre duas bounding boxes normalizadas."""
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1)
    area_b = (b.x2 - b.x1) * (b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0
