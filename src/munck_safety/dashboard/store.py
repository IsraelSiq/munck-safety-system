"""
Persistência de eventos em SQLite para auditoria e dashboard.

Decisões:
  - SQLite: sem dependências de servidor, portátil no Jetson.
  - WAL mode: leituras do dashboard não bloqueiam escritas do pipeline.
  - Retenção configurável: eventos antigos são removidos automaticamente.
  - Exportação CSV para integrações externas.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from munck_safety.logging_cfg import get_logger
from munck_safety.models import SafetyEvent

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL    NOT NULL,
    ts_iso       TEXT    NOT NULL,
    kind         TEXT    NOT NULL,
    severity     TEXT    NOT NULL,
    camera_id    TEXT,
    track_id     INTEGER,
    zone_id      TEXT,
    message      TEXT    NOT NULL,
    snapshot     TEXT                    -- caminho relativo do snapshot, se houver
);

CREATE INDEX IF NOT EXISTS idx_events_ts       ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_kind     ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);
CREATE INDEX IF NOT EXISTS idx_events_zone     ON events(zone_id);
"""


class EventStore:
    """
    Store thread-safe de eventos em SQLite.

    Uso:
        store = EventStore("artifacts/events.db")
        store.save(event)
        page = store.query(kind="INTRUSION_START", page=1)
    """

    def __init__(self, db_path: str, retention_days: int = 30) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def save(self, event: SafetyEvent, snapshot_path: Optional[str] = None) -> int:
        """Persiste um SafetyEvent. Retorna o id gerado."""
        ts_iso = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO events
                   (ts, ts_iso, kind, severity, camera_id, track_id, zone_id, message, snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.timestamp,
                    ts_iso,
                    event.kind.value,
                    event.severity.value,
                    event.camera_id,
                    event.track_id,
                    event.zone_id,
                    event.message,
                    snapshot_path,
                ),
            )
            return cur.lastrowid or 0

    def purge_old(self) -> int:
        """Remove eventos mais antigos que retention_days. Retorna registros removidos."""
        cutoff = time.time() - self._retention_days * 86400
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            removed = cur.rowcount
        if removed:
            log.info("events_purged", count=removed, retention_days=self._retention_days)
        return removed

    # ------------------------------------------------------------------
    # Leitura / filtros
    # ------------------------------------------------------------------

    def query(
        self,
        kind: Optional[str] = None,
        severity: Optional[str] = None,
        camera_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        since_ts: Optional[float] = None,
        until_ts: Optional[float] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """
        Retorna página de eventos com filtros opcionais.

        Retorno: {"items": [...], "total": int, "page": int, "pages": int}
        """
        where, params = self._build_where(
            kind, severity, camera_id, zone_id, since_ts, until_ts
        )
        with self._ro_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM events{where}", params
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"""SELECT id, ts_iso, kind, severity, camera_id,
                           track_id, zone_id, message, snapshot
                    FROM events{where}
                    ORDER BY ts DESC
                    LIMIT ? OFFSET ?""",
                (*params, page_size, offset),
            ).fetchall()

        items = [
            {
                "id": r[0], "ts": r[1], "kind": r[2], "severity": r[3],
                "camera_id": r[4], "track_id": r[5], "zone_id": r[6],
                "message": r[7], "snapshot": r[8],
            }
            for r in rows
        ]
        pages = max(1, (total + page_size - 1) // page_size)
        return {"items": items, "total": total, "page": page, "pages": pages}

    def summary(self) -> dict:
        """Contagens agrupadas por kind e severity para o dashboard."""
        with self._ro_conn() as conn:
            by_kind = conn.execute(
                "SELECT kind, COUNT(*) FROM events GROUP BY kind"
            ).fetchall()
            by_severity = conn.execute(
                "SELECT severity, COUNT(*) FROM events GROUP BY severity"
            ).fetchall()
            recent = conn.execute(
                """SELECT id, ts_iso, kind, severity, camera_id, zone_id, message
                   FROM events ORDER BY ts DESC LIMIT 10"""
            ).fetchall()
        return {
            "by_kind": dict(by_kind),
            "by_severity": dict(by_severity),
            "recent": [
                {"id": r[0], "ts": r[1], "kind": r[2], "severity": r[3],
                 "camera_id": r[4], "zone_id": r[5], "message": r[6]}
                for r in recent
            ],
        }

    def export_csv(
        self,
        kind: Optional[str] = None,
        since_ts: Optional[float] = None,
        until_ts: Optional[float] = None,
    ) -> str:
        """Exporta eventos filtrados como string CSV."""
        where, params = self._build_where(kind, None, None, None, since_ts, until_ts)
        with self._ro_conn() as conn:
            rows = conn.execute(
                f"""SELECT id, ts_iso, kind, severity, camera_id,
                           track_id, zone_id, message, snapshot
                    FROM events{where} ORDER BY ts DESC""",
                params,
            ).fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "ts", "kind", "severity", "camera_id",
                         "track_id", "zone_id", "message", "snapshot"])
        writer.writerows(rows)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where(
        kind, severity, camera_id, zone_id, since_ts, until_ts
    ) -> tuple[str, list]:
        clauses = []
        params: list = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if zone_id:
            clauses.append("zone_id = ?")
            params.append(zone_id)
        if since_ts is not None:
            clauses.append("ts >= ?")
            params.append(since_ts)
        if until_ts is not None:
            clauses.append("ts <= ?")
            params.append(until_ts)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        log.info("event_store_ready", path=str(self._path))

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        with self._lock:
            conn = sqlite3.connect(str(self._path), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def _ro_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True, timeout=5)
        try:
            yield conn
        finally:
            conn.close()
