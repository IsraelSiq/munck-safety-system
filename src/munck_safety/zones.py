from __future__ import annotations

from typing import Iterable, Sequence

import cv2
import numpy as np


def normalized_to_pixels(polygon: Iterable[Sequence[float]], width: int, height: int) -> np.ndarray:
    points = [(round(float(x) * width), round(float(y) * height)) for x, y in polygon]
    if len(points) < 3:
        raise ValueError("A zona precisa de pelo menos tres pontos")
    return np.asarray(points, dtype=np.int32)


def contains_point(point: tuple[int, int], polygon: np.ndarray) -> bool:
    return cv2.pointPolygonTest(polygon, point, False) >= 0
