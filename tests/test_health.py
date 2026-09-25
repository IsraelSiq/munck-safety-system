"""
Testes do monitor de saúde.

Requisito fundamental: falha técnica NUNCA é silenciosa.
"""
from __future__ import annotations

import time

import pytest

from munck_safety.config import AlarmConfig, HealthConfig
from munck_safety.models import CameraHealth, EventKind, HealthStatus, SafetyEvent
from munck_safety.utils.health import HealthMonitor


def make_monitor(events: list[SafetyEvent]) -> HealthMonitor:
    cfg = HealthConfig(heartbeat_interval_s=10.0, camera_timeout_s=5.0)
    alarm_cfg = AlarmConfig(disk_min_free_mb=500.0)
    return HealthMonitor(cfg, alarm_cfg, on_event=events.append)


def make_cam(camera_id: str, online: bool, last_frame_ts: float) -> CameraHealth:
    return CameraHealth(camera_id=camera_id, online=online, last_frame_ts=last_frame_ts)


class TestCameraOffline:
    def test_camera_sem_frame_torna_offline(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = time.monotonic()

        cam = make_cam("cam_a", online=True, last_frame_ts=now - 10.0)  # 10s atrás
        monitor.tick([cam], model_available=True, now=now)

        offline = [e for e in events if e.kind == EventKind.CAMERA_OFFLINE]
        assert len(offline) == 1
        assert offline[0].camera_id == "cam_a"

    def test_camera_recente_nao_gera_offline(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = time.monotonic()

        cam = make_cam("cam_a", online=True, last_frame_ts=now - 1.0)
        monitor.tick([cam], model_available=True, now=now)

        offline = [e for e in events if e.kind == EventKind.CAMERA_OFFLINE]
        assert not offline


class TestModelUnavailable:
    def test_modelo_indisponivel_gera_evento_critico(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = time.monotonic()

        cam = make_cam("cam_a", online=True, last_frame_ts=now)
        monitor.tick([cam], model_available=False, now=now)

        model_events = [e for e in events if e.kind == EventKind.MODEL_UNAVAILABLE]
        assert len(model_events) == 1

    def test_status_failed_sem_modelo(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = time.monotonic()

        cam = make_cam("cam_a", online=True, last_frame_ts=now)
        health = monitor.tick([cam], model_available=False, now=now)

        assert health.status == HealthStatus.FAILED


class TestHealthStatus:
    def test_status_ok_com_todas_cameras_online(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = time.monotonic()

        cams = [
            make_cam("cam_a", online=True, last_frame_ts=now),
            make_cam("cam_b", online=True, last_frame_ts=now),
        ]
        health = monitor.tick(cams, model_available=True, now=now)
        assert health.status == HealthStatus.OK

    def test_status_degraded_com_uma_camera_offline(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = time.monotonic()

        cams = [
            make_cam("cam_a", online=True, last_frame_ts=now),
            make_cam("cam_b", online=False, last_frame_ts=now - 100.0),
        ]
        health = monitor.tick(cams, model_available=True, now=now)
        assert health.status == HealthStatus.DEGRADED

    def test_status_failed_todas_cameras_offline(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = time.monotonic()

        cams = [
            make_cam("cam_a", online=False, last_frame_ts=now - 100.0),
            make_cam("cam_b", online=False, last_frame_ts=now - 100.0),
        ]
        health = monitor.tick(cams, model_available=True, now=now)
        assert health.status == HealthStatus.FAILED


class TestHeartbeat:
    def test_heartbeat_emitido_apos_intervalo(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = 1000.0

        cam = make_cam("cam_a", online=True, last_frame_ts=now)
        # Força o heartbeat (last=0, intervalo=10 → now=1000 > 10)
        monitor.tick([cam], model_available=True, now=now)

        hb = [e for e in events if e.kind == EventKind.HEARTBEAT]
        assert len(hb) == 1

    def test_heartbeat_nao_repete_antes_do_intervalo(self):
        events: list[SafetyEvent] = []
        monitor = make_monitor(events)
        now = 1000.0

        cam = make_cam("cam_a", online=True, last_frame_ts=now)
        monitor.tick([cam], model_available=True, now=now)
        monitor.tick([cam], model_available=True, now=now + 1.0)  # 1s depois

        hb = [e for e in events if e.kind == EventKind.HEARTBEAT]
        assert len(hb) == 1
