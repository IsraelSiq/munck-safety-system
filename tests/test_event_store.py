"""
Testes do EventStore SQLite — Fase 2.

Validam persistência, filtros, paginação, exportação CSV e purge.
"""
from __future__ import annotations

import time
import tempfile
from pathlib import Path

import pytest

from munck_safety.dashboard.store import EventStore
from munck_safety.models import EventKind, SafetyEvent, Severity


def make_event(
    kind: EventKind = EventKind.INTRUSION_START,
    severity: Severity = Severity.CRITICAL,
    camera_id: str = "cam_a",
    zone_id: str = "z1",
    track_id: int = 1,
) -> SafetyEvent:
    return SafetyEvent(
        kind=kind, severity=severity,
        camera_id=camera_id, track_id=track_id,
        zone_id=zone_id, message="teste",
        timestamp=time.time(),
    )


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(str(tmp_path / "events.db"), retention_days=30)


class TestEventStore:
    def test_save_e_query_basico(self, store: EventStore):
        e = make_event()
        store.save(e)
        result = store.query()
        assert result["total"] == 1
        assert result["items"][0]["kind"] == "INTRUSION_START"

    def test_filtro_por_kind(self, store: EventStore):
        store.save(make_event(kind=EventKind.INTRUSION_START))
        store.save(make_event(kind=EventKind.PPE_NON_COMPLIANT,
                              severity=Severity.WARNING))
        result = store.query(kind="PPE_NON_COMPLIANT")
        assert result["total"] == 1
        assert result["items"][0]["kind"] == "PPE_NON_COMPLIANT"

    def test_filtro_por_severity(self, store: EventStore):
        store.save(make_event(severity=Severity.CRITICAL))
        store.save(make_event(severity=Severity.WARNING,
                              kind=EventKind.PPE_NON_COMPLIANT))
        result = store.query(severity="WARNING")
        assert result["total"] == 1

    def test_filtro_por_zone_id(self, store: EventStore):
        store.save(make_event(zone_id="z1"))
        store.save(make_event(zone_id="z2"))
        result = store.query(zone_id="z2")
        assert result["total"] == 1

    def test_filtro_por_camera_id(self, store: EventStore):
        store.save(make_event(camera_id="cam_a"))
        store.save(make_event(camera_id="cam_b"))
        result = store.query(camera_id="cam_b")
        assert result["total"] == 1

    def test_paginacao(self, store: EventStore):
        for _ in range(7):
            store.save(make_event())
        p1 = store.query(page=1, page_size=3)
        p2 = store.query(page=2, page_size=3)
        p3 = store.query(page=3, page_size=3)
        assert p1["total"] == 7
        assert len(p1["items"]) == 3
        assert len(p2["items"]) == 3
        assert len(p3["items"]) == 1
        assert p1["pages"] == 3

    def test_export_csv(self, store: EventStore):
        store.save(make_event(kind=EventKind.INTRUSION_START))
        store.save(make_event(kind=EventKind.PPE_NON_COMPLIANT,
                              severity=Severity.WARNING))
        csv = store.export_csv()
        lines = csv.strip().splitlines()
        assert lines[0].startswith("id,ts,kind")  # header
        assert len(lines) == 3  # header + 2 eventos

    def test_export_csv_filtrado(self, store: EventStore):
        store.save(make_event(kind=EventKind.INTRUSION_START))
        store.save(make_event(kind=EventKind.PPE_NON_COMPLIANT,
                              severity=Severity.WARNING))
        csv = store.export_csv(kind="INTRUSION_START")
        lines = csv.strip().splitlines()
        assert len(lines) == 2  # header + 1

    def test_summary(self, store: EventStore):
        store.save(make_event(kind=EventKind.INTRUSION_START))
        store.save(make_event(kind=EventKind.INTRUSION_START))
        store.save(make_event(kind=EventKind.PPE_NON_COMPLIANT,
                              severity=Severity.WARNING))
        summary = store.summary()
        assert summary["by_kind"]["INTRUSION_START"] == 2
        assert summary["by_kind"]["PPE_NON_COMPLIANT"] == 1
        assert len(summary["recent"]) == 3

    def test_purge_remove_eventos_antigos(self, store: EventStore):
        old_event = make_event()
        old_event.timestamp = time.time() - (31 * 86400)  # 31 dias atrás
        store.save(old_event)
        store.save(make_event())  # recente
        removed = store.purge_old()
        assert removed == 1
        assert store.query()["total"] == 1

    def test_snapshot_path_salvo(self, store: EventStore):
        e = make_event()
        store.save(e, snapshot_path="/artifacts/snap_001.jpg")
        result = store.query()
        assert result["items"][0]["snapshot"] == "/artifacts/snap_001.jpg"

    def test_multiplos_filtros_combinados(self, store: EventStore):
        store.save(make_event(kind=EventKind.INTRUSION_START, zone_id="z1"))
        store.save(make_event(kind=EventKind.INTRUSION_START, zone_id="z2"))
        store.save(make_event(kind=EventKind.PPE_NON_COMPLIANT,
                              severity=Severity.WARNING, zone_id="z1"))
        result = store.query(kind="INTRUSION_START", zone_id="z1")
        assert result["total"] == 1
