"""
Dashboard HTTP para auditoria e gestão — Fase 2.

Servidor leve usando apenas stdlib (http.server).
Sem dependências externas — roda no Jetson sem pip adicional.

Endpoints:
  GET  /                        → dashboard HTML (SPA inline)
  GET  /api/events              → lista paginada (JSON)
  GET  /api/events?kind=X&...   → filtros: kind, severity, camera_id, zone_id
  GET  /api/summary             → contagens por kind/severity + recentes
  GET  /api/export.csv          → exportação CSV
  GET  /snapshots/<file>        → serve snapshot de evidência
  GET  /camera/<id>/stream      → MJPEG stream da câmera (frames do YOLO)
  GET  /events/stream           → SSE stream de eventos em tempo real

Acesso: somente rede local — não expor à internet.
"""
from __future__ import annotations

import json
import mimetypes
import queue
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from munck_safety.config import DashboardConfig
from munck_safety.dashboard.store import EventStore
from munck_safety.logging_cfg import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# HTML do dashboard (SPA inline — sem build step)
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Munck Safety — Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
  header{background:#1e293b;padding:1rem 2rem;display:flex;align-items:center;gap:1rem;border-bottom:1px solid #334155}
  header h1{font-size:1.2rem;font-weight:700;color:#f8fafc}
  header span{font-size:.8rem;color:#64748b}
  #status{margin-left:auto;font-size:.75rem}
  .ok{color:#4ade80} .warn{color:#fb923c} .err{color:#f87171}
  .cameras{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem;padding:1rem 2rem}
  .cam-card{background:#1e293b;border-radius:.5rem;overflow:hidden;border:2px solid #334155}
  .cam-card.alarm{border-color:#ef4444;box-shadow:0 0 12px #ef444480}
  .cam-card h3{padding:.4rem .8rem;font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
  .cam-card img{width:100%;display:block;background:#0f172a;min-height:180px;object-fit:contain}
  .cam-card .cam-status{padding:.3rem .8rem;font-size:.7rem;color:#64748b}
  .summary{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:.75rem;padding:0 2rem 1rem}
  .card{background:#1e293b;border-radius:.5rem;padding:1rem;border-left:4px solid #3b82f6}
  .card h3{font-size:.7rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
  .card p{font-size:1.6rem;font-weight:700;margin-top:.25rem}
  .card.danger{border-left-color:#ef4444} .card.warn{border-left-color:#f59e0b}
  .alarm-banner{display:none;background:#ef4444;color:#fff;padding:.6rem 2rem;font-weight:700;font-size:.95rem;align-items:center;gap:1rem}
  .alarm-banner.show{display:flex}
  .alarm-banner button{background:#fff;color:#ef4444;border:none;padding:.3rem .8rem;border-radius:.25rem;cursor:pointer;font-weight:700}
  .log-section{padding:0 2rem 1rem}
  .log-section h2{font-size:.8rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem}
  .log-list{background:#1e293b;border-radius:.5rem;max-height:280px;overflow-y:auto;font-size:.78rem;font-family:monospace}
  .log-item{padding:.35rem .8rem;border-bottom:1px solid #0f172a;display:flex;gap:.5rem;align-items:baseline}
  .log-item.intrusion{background:#2d0a0a}
  .log-item .time{color:#475569;flex-shrink:0;font-size:.7rem}
  .log-item .badge{padding:.1rem .4rem;border-radius:3px;font-size:.65rem;font-weight:700;flex-shrink:0}
  .INTRUSION_START .badge,.INTRUSION_END .badge{background:#ef4444;color:#fff}
  .HEARTBEAT .badge,.SYSTEM_READY .badge{background:#1e3a5f;color:#93c5fd}
  .STREAM_LOST .badge,.MODEL_UNAVAILABLE .badge{background:#78350f;color:#fcd34d}
  .log-item .msg{color:#cbd5e1}
</style>
</head>
<body>
<header>
  <h1>🏗️ Munck Safety</h1>
  <span id="conn-status" class="warn">⏳ Conectando…</span>
  <span id="status">—</span>
</header>

<div class="alarm-banner" id="alarm-banner">
  <span>🚨 <span id="alarm-msg">INTRUSÃO DETECTADA</span></span>
  <button onclick="clearAlarm()">Reconhecer</button>
</div>

<div class="cameras" id="cameras"></div>

<div class="summary">
  <div class="card danger"><h3>Intrusões</h3><p id="s-intrusions">0</p></div>
  <div class="card warn"><h3>Câmeras Online</h3><p id="s-cameras">0</p></div>
  <div class="card"><h3>Uptime</h3><p id="s-uptime">0s</p></div>
</div>

<div class="log-section">
  <h2>Log de Eventos</h2>
  <div class="log-list" id="log-list"></div>
</div>

<script>
const MAX_LOG = 200;
let intrusions = 0;
let alarmTimeout = null;
let cameras = new Set();
let startTime = Date.now();
let eventSource = null;

function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource('/events/stream');

  eventSource.onopen = () => {
    document.getElementById('conn-status').textContent = '✅ Online';
    document.getElementById('conn-status').className = 'ok';
  };

  eventSource.onerror = () => {
    document.getElementById('conn-status').textContent = '🔴 Desconectado — reconectando…';
    document.getElementById('conn-status').className = 'err';
    setTimeout(connectSSE, 3000);
  };

  eventSource.addEventListener('event', (e) => {
    const data = JSON.parse(e.data);
    handleEvent(data);
  });

  eventSource.addEventListener('ping', () => {});
}

function handleEvent(ev) {
  const type = ev.kind || ev.event_type || '';
  const isReplay = ev.is_replay === true;
  const cam = ev.camera_id || '';
  const zone = ev.zone_id || ev.zone || '';
  const track = ev.track_id != null ? ev.track_id : '';
  const msg = ev.message || '';
  const ts = (ev.ts || ev.timestamp || new Date().toISOString()).replace('T', ' ').slice(0, 19);

  // Registrar câmera
  if (cam && !cameras.has(cam)) {
    cameras.add(cam);
    addCamera(cam);
    document.getElementById('s-cameras').textContent = cameras.size;
  }

  if (type === 'INTRUSION_START') {
    intrusions++;
    document.getElementById('s-intrusions').textContent = intrusions;
    if (cam) document.getElementById('cam-' + cam)?.classList.add('alarm');
    if (!isReplay) triggerAlarm('Pessoa #' + track + (cam ? ' | ' + cam : '') + (zone ? ' | ' + zone : ''));
  }

  addLog(ts, type, msg, cam, track);
}

function addCamera(camId) {
  const div = document.createElement('div');
  div.className = 'cam-card';
  div.id = 'cam-' + camId;
  div.innerHTML = '<h3>' + camId + '</h3>' +
    '<img src="/camera/' + camId + '/stream" onerror="this.style.opacity=\'0.3\'" ' +
    'onload="this.style.opacity=\'1\'" alt="' + camId + '">' +
    '<div class="cam-status" id="cam-status-' + camId + '">Aguardando frames…</div>';
  document.getElementById('cameras').appendChild(div);
}

function addLog(ts, type, msg, cam, track) {
  const list = document.getElementById('log-list');
  const div = document.createElement('div');
  div.className = 'log-item ' + type;
  div.innerHTML = '<span class="time">' + ts + '</span>' +
    '<span class="badge">' + type + '</span>' +
    '<span class="msg">' + (cam ? '[' + cam + '] ' : '') +
    (track !== '' ? '#' + track + ' ' : '') + msg + '</span>';
  list.insertBefore(div, list.firstChild);
  while (list.children.length > MAX_LOG) list.removeChild(list.lastChild);
}

function triggerAlarm(msg) {
  const banner = document.getElementById('alarm-banner');
  document.getElementById('alarm-msg').textContent = '🚨 INTRUSÃO: ' + msg;
  banner.classList.add('show');
  try { new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAA...').play(); } catch(e) {}
  if (alarmTimeout) clearTimeout(alarmTimeout);
  alarmTimeout = setTimeout(clearAlarm, 10000);
}

function clearAlarm() {
  document.getElementById('alarm-banner').classList.remove('show');
  document.querySelectorAll('.cam-card.alarm').forEach(c => c.classList.remove('alarm'));
  if (alarmTimeout) { clearTimeout(alarmTimeout); alarmTimeout = null; }
}

function updateStats() {
  const uptime = Math.floor((Date.now() - startTime) / 1000);
  const h = Math.floor(uptime / 3600), m = Math.floor((uptime % 3600) / 60), s = uptime % 60;
  document.getElementById('s-uptime').textContent =
    (h ? h + 'h ' : '') + (m ? m + 'm ' : '') + s + 's';
  fetch('/api/summary').then(r => r.json()).then(d => {
    const i = d.by_kind && d.by_kind['INTRUSION_START'];
    if (i !== undefined) document.getElementById('s-intrusions').textContent = i;
    document.getElementById('status').textContent = 'Atualizado ' + new Date().toLocaleTimeString('pt-BR');
  }).catch(() => {});
}

connectSSE();
setInterval(updateStats, 5000);
updateStats();

// Detectar câmeras existentes via summary
fetch('/api/summary').then(r => r.json()).then(d => {
  if (d.cameras) d.cameras.forEach(c => { if (!cameras.has(c)) { cameras.add(c); addCamera(c); } });
  document.getElementById('s-cameras').textContent = cameras.size;
}).catch(() => {});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Estado compartilhado de frames (thread-safe)
# ---------------------------------------------------------------------------

class FrameStore:
    """Armazena o último frame JPEG de cada câmera para MJPEG streaming."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frames: dict[str, bytes] = {}

    def put(self, camera_id: str, jpeg_bytes: bytes) -> None:
        with self._lock:
            self._frames[camera_id] = jpeg_bytes

    def get(self, camera_id: str) -> bytes | None:
        with self._lock:
            return self._frames.get(camera_id)

    def cameras(self) -> list[str]:
        with self._lock:
            return list(self._frames.keys())


# Singleton global — o app.py importa e usa diretamente
frame_store = FrameStore()


# ---------------------------------------------------------------------------
# SSE — lista de filas de clientes
# ---------------------------------------------------------------------------

class SSEBroker:
    """Distribui eventos SSE para todos os clientes conectados."""

    def __init__(self):
        self._lock = threading.Lock()
        self._clients: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    def publish(self, event_dict: dict) -> None:
        data = json.dumps(event_dict, ensure_ascii=False, default=str)
        msg = f"event: event\ndata: {data}\n\n"
        with self._lock:
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.remove(q)

    def ping(self) -> None:
        msg = "event: ping\ndata: {}\n\n"
        with self._lock:
            for q in self._clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


# Singleton global
sse_broker = SSEBroker()


# ---------------------------------------------------------------------------
# Handler HTTP
# ---------------------------------------------------------------------------

MAX_PAGE_SIZE = 500


class _Handler(BaseHTTPRequestHandler):
    store: EventStore
    cfg: DashboardConfig
    artifacts_dir: Path

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # Suprime logs do stdlib para não poluir o structlog

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        try:
            if path == "/" or path == "":
                self._send_html(_HTML)
            elif path == "/api/summary":
                data = self.store.summary()
                # Adiciona lista de cameras conhecidas
                data["cameras"] = frame_store.cameras()
                self._send_json(data)
            elif path == "/api/events":
                result = self.store.query(
                    kind=params.get("kind"),
                    severity=params.get("severity"),
                    camera_id=params.get("camera_id"),
                    zone_id=params.get("zone_id"),
                    page=max(1, self._int_param(params, "page", 1)),
                    page_size=min(
                        MAX_PAGE_SIZE,
                        max(1, self._int_param(params, "page_size", self.cfg.page_size)),
                    ),
                )
                self._send_json(result)
            elif path == "/api/export.csv":
                csv_data = self.store.export_csv(kind=params.get("kind"))
                self._send(200, csv_data.encode(), "text/csv; charset=utf-8",
                           headers={"Content-Disposition": "attachment; filename=events.csv"})
            elif path.startswith("/snapshots/"):
                fname = urllib.parse.unquote(path[len("/snapshots/"):])
                self._serve_snapshot(fname)
            elif path.startswith("/camera/") and path.endswith("/stream"):
                # /camera/<camera_id>/stream  →  MJPEG
                parts = path.strip("/").split("/")
                if len(parts) == 3:
                    self._stream_mjpeg(parts[1])
                else:
                    self._send(404, b"Not found", "text/plain")
            elif path == "/events/stream":
                self._stream_sse()
            else:
                self._send(404, b"Not found", "text/plain")
        except Exception as exc:
            log.exception("dashboard_handler_error", path=path, error=str(exc))
            try:
                self._send(500, b"Internal server error", "text/plain")
            except Exception:
                pass

    def _stream_mjpeg(self, camera_id: str) -> None:
        """Gera stream MJPEG a partir do frame_store."""
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                jpeg = frame_store.get(camera_id)
                if jpeg is not None:
                    self.wfile.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        jpeg + b"\r\n"
                    )
                    self.wfile.flush()
                time.sleep(0.05)  # ~20fps máx
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _stream_sse(self) -> None:
        """Envia eventos em tempo real via Server-Sent Events."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # Replay de histórico
        try:
            recent = self.store.query(page=1, page_size=200)
            for item in reversed(recent.get("items", [])):
                item["is_replay"] = True
                data = json.dumps(item, ensure_ascii=False, default=str)
                self.wfile.write(f"event: event\ndata: {data}\n\n".encode())
            self.wfile.flush()
        except Exception:
            pass

        q = sse_broker.subscribe()
        try:
            while True:
                try:
                    msg = q.get(timeout=15.0)
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                except queue.Empty:
                    # Heartbeat
                    self.wfile.write(b"event: ping\ndata: {}\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            sse_broker.unsubscribe(q)

    @staticmethod
    def _int_param(params: dict, name: str, default: int) -> int:
        try:
            return int(params.get(name, default))
        except (TypeError, ValueError):
            return default

    def _serve_snapshot(self, fname: str) -> None:
        """Serve um snapshot garantindo que o caminho fique dentro de artifacts_dir."""
        root = self.artifacts_dir.resolve()
        target = (root / fname).resolve()
        if root != target and root not in target.parents:
            log.warning("snapshot_path_rejected", requested=fname)
            self._send(404, b"Not found", "text/plain")
            return
        self._serve_file(target)

    def _send_html(self, html: str) -> None:
        self._send(200, html.encode(), "text/html; charset=utf-8")

    def _send_json(self, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self._send(200, body, "application/json; charset=utf-8")

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send(404, b"Not found", "text/plain")
            return
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), mime)

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        headers: Optional[dict] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------

class DashboardServer:
    """Servidor HTTP do dashboard rodando em thread daemon."""

    def __init__(
        self,
        store: EventStore,
        cfg: DashboardConfig,
        artifacts_dir: str = "artifacts",
    ) -> None:
        self._store = store
        self._cfg = cfg
        self._artifacts = Path(artifacts_dir)
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._ping_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        handler = _Handler
        handler.store = self._store
        handler.cfg = self._cfg
        handler.artifacts_dir = self._artifacts

        self._server = ThreadingHTTPServer((self._cfg.host, self._cfg.port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="dashboard-http",
            daemon=True,
        )
        self._thread.start()

        # Thread de ping SSE a cada 10s para manter conexões vivas
        self._ping_thread = threading.Thread(
            target=self._sse_ping_loop,
            name="sse-ping",
            daemon=True,
        )
        self._ping_thread.start()

        log.info("dashboard_started", host=self._cfg.host, port=self._cfg.port,
                 url=f"http://localhost:{self._cfg.port}")

    def _sse_ping_loop(self) -> None:
        while True:
            time.sleep(10)
            sse_broker.ping()

    def push_event(self, event_dict: dict) -> None:
        """Pusha evento para todos os clientes SSE conectados."""
        sse_broker.publish(event_dict)

    def push_frame(self, camera_id: str, jpeg_bytes: bytes) -> None:
        """Atualiza o frame JPEG de uma câmera para MJPEG streaming."""
        frame_store.put(camera_id, jpeg_bytes)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("dashboard_stopped")
