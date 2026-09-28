"""Testes do DashboardServer: path traversal, paginacao e shutdown."""
from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from munck_safety.config import DashboardConfig
from munck_safety.dashboard import DashboardServer, EventStore


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def running_server(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "snap.jpg").write_bytes(b"jpeg-bytes")
    (tmp_path / "secret.txt").write_text("conteudo sigiloso")

    store = EventStore(str(tmp_path / "events.db"), retention_days=7)
    cfg = DashboardConfig(enabled=True, host="127.0.0.1", port=_free_port())
    server = DashboardServer(store, cfg, str(artifacts))
    server.start()
    try:
        yield server, cfg, store
    finally:
        server.stop()


def _get(cfg: DashboardConfig, path: str):
    url = f"http://{cfg.host}:{cfg.port}{path}"
    return urllib.request.urlopen(url, timeout=5)


class TestSnapshotServing:
    def test_serve_snapshot_valido(self, running_server):
        _, cfg, _ = running_server
        resp = _get(cfg, "/snapshots/snap.jpg")
        assert resp.status == 200
        assert resp.read() == b"jpeg-bytes"

    def test_path_traversal_rejeitado(self, running_server):
        _, cfg, _ = running_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(cfg, "/snapshots/..%2Fsecret.txt")
        assert exc.value.code == 404

    def test_path_traversal_absoluto_rejeitado(self, running_server):
        _, cfg, _ = running_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(cfg, "/snapshots/../../../../etc/passwd")
        assert exc.value.code == 404


class TestPaginacao:
    def test_page_size_gigante_e_limitado(self, running_server):
        import json

        _, cfg, _ = running_server
        resp = _get(cfg, "/api/events?page_size=10000000")
        data = json.loads(resp.read())
        assert data["page_size"] <= 500

    def test_page_invalida_nao_quebra(self, running_server):
        import json

        _, cfg, _ = running_server
        resp = _get(cfg, "/api/events?page=abc&page_size=-5")
        data = json.loads(resp.read())
        assert data["page"] >= 1
        assert data["page_size"] >= 1


class TestShutdown:
    def test_stop_libera_a_porta(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        store = EventStore(str(tmp_path / "events.db"), retention_days=7)
        cfg = DashboardConfig(enabled=True, host="127.0.0.1", port=_free_port())

        first = DashboardServer(store, cfg, str(artifacts))
        first.start()
        first.stop()

        second = DashboardServer(store, cfg, str(artifacts))
        second.start()  # nao deve levantar "Address already in use"
        try:
            assert _get(cfg, "/api/summary").status == 200
        finally:
            second.stop()
