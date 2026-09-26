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

Acesso: somente rede local — não expor à internet.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
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
  .pills{display:flex;gap:.5rem;flex-wrap:wrap;padding:1rem 2rem}
  .pill{padding:.3rem .8rem;border-radius:999px;font-size:.75rem;font-weight:600;cursor:pointer;border:2px solid transparent}
  .pill.active{border-color:#3b82f6}
  .pill.CRITICAL{background:#7f1d1d;color:#fca5a5}
  .pill.WARNING{background:#78350f;color:#fcd34d}
  .pill.INFO{background:#1e3a5f;color:#93c5fd}
  .summary{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.75rem;padding:0 2rem 1rem}
  .card{background:#1e293b;border-radius:.5rem;padding:1rem;border-left:4px solid #3b82f6}
  .card h3{font-size:.7rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
  .card p{font-size:1.6rem;font-weight:700;margin-top:.25rem}
  .card.INTRUSION_START .card-bar{border-color:#ef4444} .card.PPE_NON_COMPLIANT .card-bar{border-color:#f59e0b}
  table{width:100%;border-collapse:collapse;font-size:.82rem}
  th{background:#1e293b;padding:.6rem 1rem;text-align:left;color:#94a3b8;font-weight:600;position:sticky;top:0}
  td{padding:.55rem 1rem;border-bottom:1px solid #1e293b}
  tr:hover td{background:#1e293b88}
  .badge{display:inline-block;padding:.15rem .5rem;border-radius:4px;font-size:.7rem;font-weight:700}
  .CRITICAL{background:#7f1d1d;color:#fca5a5} .WARNING{background:#78350f;color:#fcd34d} .INFO{background:#1e3a5f;color:#93c5fd}
  .tbl-wrap{overflow-x:auto;padding:0 2rem 2rem}
  .filters{display:flex;gap:.5rem;padding:0 2rem .75rem;flex-wrap:wrap;align-items:center}
  .filters select,.filters input{background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:.35rem .6rem;border-radius:.35rem;font-size:.82rem}
  .filters button{background:#3b82f6;color:#fff;border:none;padding:.35rem .9rem;border-radius:.35rem;cursor:pointer;font-size:.82rem}
  .filters a{color:#60a5fa;font-size:.82rem;text-decoration:none}
  .pager{display:flex;gap:.5rem;align-items:center;padding:.75rem 2rem;font-size:.82rem}
  .pager button{background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:.3rem .7rem;border-radius:.35rem;cursor:pointer}
  .pager button:disabled{opacity:.4;cursor:default}
  #status{margin-left:auto;font-size:.75rem;color:#64748b}
</style>
</head>
<body>
<header>
  <h1>🏗️ Munck Safety</h1>
  <span>Dashboard de Segurança</span>
  <span id="status">Carregando…</span>
</header>
<div class="summary" id="summary"></div>
<div class="filters">
  <select id="fKind"><option value="">Todos os tipos</option>
    <option>INTRUSION_START</option><option>INTRUSION_END</option>
    <option>PPE_NON_COMPLIANT</option><option>PPE_COMPLIANT</option>
    <option>CAMERA_OFFLINE</option><option>MODEL_UNAVAILABLE</option>
    <option>HEARTBEAT</option>
  </select>
  <select id="fSeverity"><option value="">Todas severidades</option>
    <option>CRITICAL</option><option>WARNING</option><option>INFO</option>
  </select>
  <input id="fZone" placeholder="Zona…" style="width:130px">
  <input id="fCamera" placeholder="Câmera…" style="width:130px">
  <button onclick="load(1)">Filtrar</button>
  <a href="/api/export.csv" id="exportLink">⬇ Exportar CSV</a>
</div>
<div class="tbl-wrap">
<table>
<thead><tr><th>Hora</th><th>Tipo</th><th>Severidade</th><th>Câmera</th><th>Track</th><th>Zona</th><th>Mensagem</th><th>Evidência</th></tr></thead>
<tbody id="tbody"></tbody>
</table>
</div>
<div class="pager">
  <button id="btnPrev" onclick="changePage(-1)">◀ Anterior</button>
  <span id="pageInfo"></span>
  <button id="btnNext" onclick="changePage(1)">Próxima ▶</button>
</div>
<script>
let currentPage=1,totalPages=1;
function q(id){return document.getElementById(id).value}

function load(page){
  currentPage=page;
  const params=new URLSearchParams({page,page_size:50});
  if(q('fKind'))params.set('kind',q('fKind'));
  if(q('fSeverity'))params.set('severity',q('fSeverity'));
  if(q('fZone'))params.set('zone_id',q('fZone'));
  if(q('fCamera'))params.set('camera_id',q('fCamera'));
  fetch('/api/events?'+params).then(r=>r.json()).then(data=>{
    totalPages=data.pages;
    document.getElementById('pageInfo').textContent=`Pág ${data.page} de ${data.pages} (${data.total} eventos)`;
    document.getElementById('btnPrev').disabled=page<=1;
    document.getElementById('btnNext').disabled=page>=data.pages;
    const tbody=document.getElementById('tbody');
    tbody.innerHTML=data.items.map(e=>`
      <tr>
        <td>${e.ts.replace('T',' ').slice(0,19)}</td>
        <td>${e.kind}</td>
        <td><span class="badge ${e.severity}">${e.severity}</span></td>
        <td>${e.camera_id||'—'}</td>
        <td>${e.track_id!=null?e.track_id:'—'}</td>
        <td>${e.zone_id||'—'}</td>
        <td>${e.message}</td>
        <td>${e.snapshot?`<a href="/snapshots/${e.snapshot}" target="_blank">📷</a>`:'—'}</td>
      </tr>`).join('');
  });
  // Atualiza link de exportação com filtros
  const exp=new URLSearchParams();
  if(q('fKind'))exp.set('kind',q('fKind'));
  document.getElementById('exportLink').href='/api/export.csv?'+exp;
}

function changePage(delta){if(currentPage+delta>=1&&currentPage+delta<=totalPages)load(currentPage+delta)}

function loadSummary(){
  fetch('/api/summary').then(r=>r.json()).then(data=>{
    const keys=['INTRUSION_START','PPE_NON_COMPLIANT','CAMERA_OFFLINE','MODEL_UNAVAILABLE'];
    const labels={'INTRUSION_START':'Intrusões','PPE_NON_COMPLIANT':'Violações EPI','CAMERA_OFFLINE':'Câmera Offline','MODEL_UNAVAILABLE':'Modelo Indisp.'};
    document.getElementById('summary').innerHTML=keys.map(k=>`
      <div class="card">
        <h3>${labels[k]||k}</h3>
        <p>${data.by_kind[k]||0}</p>
      </div>`).join('');
    document.getElementById('status').textContent='Atualizado '+new Date().toLocaleTimeString('pt-BR');
  });
}

load(1);loadSummary();
setInterval(()=>{load(currentPage);loadSummary();},15000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Handler HTTP
# ---------------------------------------------------------------------------

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
                self._send_json(self.store.summary())
            elif path == "/api/events":
                result = self.store.query(
                    kind=params.get("kind"),
                    severity=params.get("severity"),
                    camera_id=params.get("camera_id"),
                    zone_id=params.get("zone_id"),
                    page=int(params.get("page", 1)),
                    page_size=int(params.get("page_size", self.cfg.page_size)),
                )
                self._send_json(result)
            elif path == "/api/export.csv":
                csv_data = self.store.export_csv(kind=params.get("kind"))
                self._send(200, csv_data.encode(), "text/csv; charset=utf-8",
                           headers={"Content-Disposition": "attachment; filename=events.csv"})
            elif path.startswith("/snapshots/"):
                fname = path[len("/snapshots/"):]
                self._serve_file(self.artifacts_dir / fname)
            else:
                self._send(404, b"Not found", "text/plain")
        except Exception as exc:
            log.exception("dashboard_handler_error", path=path, error=str(exc))
            self._send(500, b"Internal server error", "text/plain")

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
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        handler = _Handler
        handler.store = self._store
        handler.cfg = self._cfg
        handler.artifacts_dir = self._artifacts

        self._server = HTTPServer((self._cfg.host, self._cfg.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="dashboard-http",
            daemon=True,
        )
        self._thread.start()
        log.info("dashboard_started", host=self._cfg.host, port=self._cfg.port,
                 url=f"http://localhost:{self._cfg.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            log.info("dashboard_stopped")
