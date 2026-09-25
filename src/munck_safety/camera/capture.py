"""
Captura de frames de uma câmera com reconexão automática.

Cada câmera roda em sua própria thread. Falhas nunca são silenciadas.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

from munck_safety.config import CameraConfig
from munck_safety.logging_cfg import get_logger
from munck_safety.models import CameraHealth

log = get_logger(__name__)

HealthCallback = Callable[[CameraHealth], None]


@dataclass(slots=True)
class Frame:
    camera_id: str
    image: np.ndarray
    timestamp: float


class CameraCapture:
    """Captura contínua de uma câmera em thread dedicada com reconexão automática."""

    def __init__(
        self,
        cfg: CameraConfig,
        on_health_change: Optional[HealthCallback] = None,
        max_queue: int = 4,
    ) -> None:
        self.cfg = cfg
        self._on_health = on_health_change
        self._queue: queue.Queue[Frame] = queue.Queue(maxsize=max_queue)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"cam-{cfg.camera_id}", daemon=True
        )
        self._health = CameraHealth(
            camera_id=cfg.camera_id, online=False, last_frame_ts=0.0
        )

    def start(self) -> None:
        self._thread.start()
        log.info("camera_thread_started", camera_id=self.cfg.camera_id)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        log.info("camera_thread_stopped", camera_id=self.cfg.camera_id)

    def get_frame(self, timeout: float = 1.0) -> Optional[Frame]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def health(self) -> CameraHealth:
        return self._health

    def _run(self) -> None:
        source = self._parse_source(self.cfg.source)
        while not self._stop_event.is_set():
            cap = self._open(source)
            if cap is None:
                self._mark_offline()
                self._wait_reconnect()
                continue
            self._mark_online()
            self._capture_loop(cap)
            cap.release()
            if not self._stop_event.is_set():
                log.warning("stream_lost", camera_id=self.cfg.camera_id)
                self._mark_offline()
                self._wait_reconnect()

    def _capture_loop(self, cap: cv2.VideoCapture) -> None:
        failures = 0
        while not self._stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                self._health.consecutive_failures = failures
                if failures >= self.cfg.max_failures:
                    return
                time.sleep(0.05)
                continue
            failures = 0
            self._health.consecutive_failures = 0
            self._health.last_frame_ts = time.monotonic()
            f = Frame(camera_id=self.cfg.camera_id, image=frame,
                      timestamp=self._health.last_frame_ts)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(f)

    def _open(self, source: int | str) -> Optional[cv2.VideoCapture]:
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            log.warning("camera_open_failed",
                        camera_id=self.cfg.camera_id, source=source)
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
        cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        return cap

    def _mark_online(self) -> None:
        was_online = self._health.online
        self._health.online = True
        self._health.consecutive_failures = 0
        if not was_online:
            log.info("camera_online", camera_id=self.cfg.camera_id)
            if self._on_health:
                self._on_health(self._health)

    def _mark_offline(self) -> None:
        was_online = self._health.online
        self._health.online = False
        if was_online:
            log.error("camera_offline", camera_id=self.cfg.camera_id)
            if self._on_health:
                self._on_health(self._health)

    def _wait_reconnect(self) -> None:
        self._stop_event.wait(timeout=self.cfg.reconnect_delay_s)

    @staticmethod
    def _parse_source(source: str) -> int | str:
        try:
            return int(source)
        except ValueError:
            return source
