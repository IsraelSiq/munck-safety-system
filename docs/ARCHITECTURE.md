# Arquitetura — Munck Safety System

## Visão de alto nível

```
┌─────────────────────────────────────────────────────────────────┐
│                        Jetson Orin Nano                         │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ CameraCapture (thread por câmera)                    │       │
│  │  cam_frente_esq   cam_frente_dir   cam_tras_*        │       │
│  └──────┬───┘  └──────┬───┘  └──────┬───┘  └──────┬───┘       │
│         │              │              │              │            │
│         └──────────────┴──────────────┴──────────────┘           │
│                              │ Frame                             │
│                    ┌─────────▼──────────┐                        │
│                    │  PersonDetector    │  YOLO11 + ByteTrack    │
│                    │  (inferência)      │                        │
│                    └─────────┬──────────┘                        │
│                              │ List[Detection]                   │
│               ┌──────────────┼──────────────┐                    │
│               │              │              │                    │
│    ┌──────────▼───┐  ┌───────▼──────┐  ┌───▼──────────┐        │
│    │ RulesEngine  │  │  PPEDetector │  │ HealthMonitor│        │
│    │ (intrusão)   │  │  (EPI)       │  │ (watchdog)   │        │
│    └──────────┬───┘  └───────┬──────┘  └───┬──────────┘        │
│               │              │              │                    │
│               └──────────────┴──────────────┘                    │
│                              │ SafetyEvent                       │
│                    ┌─────────▼──────────┐                        │
│                    │   AlarmManager     │                        │
│                    │  som+snapshot+JSONL│                        │
│                    └─────────┬──────────┘                        │
│                              │                                   │
│                    ┌─────────▼──────────┐                        │
│                    │    EventStore      │  SQLite WAL            │
│                    └─────────┬──────────┘                        │
│                              │                                   │
│                    ┌─────────▼──────────┐                        │
│                    │  DashboardServer   │  HTTP :8080            │
│                    └────────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

## Princípios de design

**1. IA separada das regras de segurança**
O detector informa o que vê (detecções, confiança, posição, `track_id`).
O motor de regras — código determinístico e testável sem modelo — decide se houve intrusão e qual a resposta.

**2. Falha nunca é silenciosa**
`CAMERA_OFFLINE`, `STREAM_LOST`, `STORAGE_FULL` e `MODEL_UNAVAILABLE` geram eventos explícitos.
Ausência de detecção por falha técnica nunca é interpretada como ausência de pessoa.

**3. Alarm path independente do dashboard**
O alarme sonoro e o snapshot são gerados pelo `AlarmManager` antes de qualquer persistência.
O dashboard é um consumidor de eventos, não um intermediário de segurança.

**4. Fail-safe para EPI**
Modelo de EPI indisponível → resultado inconclusivo.
Inconclusivo não gera `PPE_NON_COMPLIANT` — apenas ausência confirmada por janela temporal acusa.

---

## Módulos

### `camera/capture.py` — CameraCapture
- Thread dedicada por câmera
- Fila sem bloqueio (frame mais recente descarta o anterior se cheia)
- Reconexão automática com delay configurável
- Callback `on_health_change` ao mudar estado

### `detector/person_detector.py` — PersonDetector
- Wrapper sobre YOLO11 + ByteTrack
- Normaliza coordenadas para `[0, 1]`
- Nunca lança exceção — falhas retornam lista vazia e logam o erro
- `available: bool` consultável pelo orquestrador

### `rules/engine.py` — RulesEngine
- Estado por `(track_id, zone_id)` em `_TrackState`
- `confirmation_frames`: N frames consecutivos antes de disparar
- `cooldown_s`: tempo mínimo entre eventos do mesmo `(track_id, zone_id)`
- `hysteresis_frames`: M frames fora da zona antes de encerrar evento
- `operation_active`: setter que emite `OPERATION_START`/`END` e limpa estados

### `ppe/detector.py` — PPEDetector
- YOLO especializado em EPI (capacete, colete, luvas, botas, óculos)
- Associa EPI a `track_id` por IoU ≥ 0.1 com bbox da pessoa
- Indisponibilidade → `PPEDetection(detected=frozenset(), confidence={})` (inconclusivo)

### `ppe/monitor.py` — PPEMonitor
- Estado por `(track_id, zone_id)` em `_PPETrackState`
- Confirmação por janela temporal (`confirmation_window_s`), não por frames
- `PPE_NON_COMPLIANT` com severidade `WARNING` (sem sirene)
- `PPE_COMPLIANT` fecha o ciclo ao retornar à conformidade

### `alarm/manager.py` — AlarmManager
- Alarme sonoro: arquivo .wav/.ogg via pygame ou beep de terminal como fallback
- Snapshot JPG no momento do evento
- Log JSONL auditável em `artifacts/events.jsonl`
- Integração opcional com `EventStore` (passa `snapshot_path` para o SQLite)

### `dashboard/store.py` — EventStore
- SQLite com `PRAGMA journal_mode=WAL` (leituras não bloqueiam escritas)
- Filtros: `kind`, `severity`, `camera_id`, `zone_id`, `since_ts`, `until_ts`
- Paginação configurável
- Exportação CSV
- Purge automático por `retention_days`

### `dashboard/server.py` — DashboardServer
- `http.server` stdlib — zero dependências adicionais
- SPA HTML inline (sem build step)
- Endpoints: `/`, `/api/events`, `/api/summary`, `/api/export.csv`, `/snapshots/<file>`
- Thread daemon — não bloqueia o loop principal

### `utils/health.py` — HealthMonitor
- Heartbeat periódico via `HEARTBEAT`
- `CAMERA_OFFLINE` quando frame não chega em `camera_timeout_s`
- `STORAGE_FULL` quando espaço livre cai abaixo do limiar
- Computa `SystemHealth.status`: `OK` / `DEGRADED` / `FAILED`

---

## Fluxo de dados por frame

```
CameraCapture.get_frame()
    → Frame(camera_id, image, timestamp)
    → PersonDetector.detect(image, camera_id)
        → List[Detection(camera_id, track_id, bbox, confidence)]
    → RulesEngine.process(detections, camera_id, frame)
        → para cada zona da câmera:
            → _foot_in_zone(det, polygon)  ← shapely
            → _handle_entry / _handle_exit
            → emit SafetyEvent → AlarmManager.handle()
    → PPEDetector.detect(image, detections, camera_id)  ← se habilitado
        → List[PPEDetection(track_id, detected, confidence)]
    → PPEMonitor.process(ppe_results, zone_id, camera_id)
        → _handle_entry / _handle_exit (janela temporal)
        → emit SafetyEvent → AlarmManager.handle()
```

---

## Contratos de dados

```python
# Detecção de pessoa — saída do detector
@dataclass(frozen=True)
class Detection:
    camera_id: str
    track_id: int
    bbox: BoundingBox          # normalizado [0,1]
    confidence: float
    timestamp: float           # monotonic

# Evento de segurança — contrato entre motor e alarme
@dataclass
class SafetyEvent:
    kind: EventKind            # INTRUSION_START, PPE_NON_COMPLIANT, ...
    severity: Severity         # CRITICAL, WARNING, INFO
    camera_id: Optional[str]
    track_id: Optional[int]
    zone_id: Optional[str]
    message: str
    timestamp: float
    frame: Optional[np.ndarray]   # snapshot opcional
```

---

## Thread model

```
main thread
├── CameraCapture-cam_frente_esq  (daemon thread)
├── CameraCapture-cam_frente_dir  (daemon thread)
├── CameraCapture-cam_tras_esq    (daemon thread)
├── CameraCapture-cam_tras_dir    (daemon thread)
└── dashboard-http                (daemon thread)
```

O loop principal é single-thread exceto pelas capturas.
Toda a lógica de inferência, regras, EPI e alarme roda no thread principal — sem race conditions.
