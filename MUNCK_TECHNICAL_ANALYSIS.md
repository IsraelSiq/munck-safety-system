# MUNCK Safety System — Análise Técnica Detalhada

## 1. Stack Identificado

```
Frontend/CLI:    CLI (argparse + cv2 display)
Backend:         Python 3.8+ (asyncio optional)
Detecção:        YOLOv8 (Ultralytics)
Tracking:        ByteTrack ou centroid-based
Storage:         JSONL (eventos) + JPEG (snapshots)
Hardware Target: Jetson Orin Nano (deployment)
                 Laptop/Desktop (dev)
```

### Dependências Críticas
```ini
# pyproject.toml esperado
torch >= 2.0          # YOLOv8
ultralytics >= 8.0    # YOLO wrapper
opencv-python >= 4.7  # Video I/O + zone detection
numpy >= 1.20
```

---

## 2. Arquitetura de Código (Estrutura Esperada)

```
src/munck_safety/
│
├── app.py                          # Entry point + argparse
│   ├── parse_args()                  # --source, --config, --operation-active
│   ├── load_config(json_path)        # Zone, operação, detecção
│   └── main()                        # Loop principal
│
├── detector.py                     # Wrapper YOLO
│   ├── YOLODetector.__init__(model_path)
│   ├── detect(frame) → List[Detection]  # bboxes + confidences
│   └── get_person_foot_point()      # Ponto inferior central da bbox
│
├── tracker.py                      # Associação de pessoa entre frames
│   ├── Tracker.__init__()
│   ├── update(detections) → List[Track]  # track_id + posição
│   └── get_inactive_tracks()
│
├── zone.py                         # Geometria de zona
│   ├── Zone.__init__(name, points_normalized)
│   ├── contains_point(x, y) → bool   # Point-in-polygon (Shapely ou NumPy)
│   └── visualize(frame) → frame with zone overlay
│
├── rules.py                        # Motor de decisão (Fase 1)
│   ├── RuleEngine.__init__(cooldown_ms=3000)
│   ├── evaluate_intrusion()
│   │   ├── Input: {track_id, zone_result, timestamp}
│   │   ├── Logic: "Se zona=true E operação=ativa → intrusão"
│   │   └── Output: {intrusão: bool, severidade: "crítica"}
│   └── get_cooldown_remaining(track_id)  # Histerese
│
├── event_manager.py                # Saída (eventos + snapshots)
│   ├── EventManager.__init__(output_dir="artifacts/")
│   ├── log_intrusion_event()
│   │   ├── Escreve JSONL: {timestamp, track_id, confiança, zona}
│   │   └── Salva snapshot: frame @ momento da intrusão
│   └── close()  # Flush buffers
│
├── alarm.py                        # [Phase 1] Abstração de alarme
│   ├── AlarmManager.__init__()
│   ├── trigger_alarm(severity)
│   │   ├── "crítica" → som alto + LED (futuro: relé)
│   │   └── "silencioso" → log + dashboard (Fase 2 EPI)
│   └── acknowledge()  # Reset cooldown
│
└── __main__.py                     # python -m munck_safety
```

---

## 3. Fluxo de Dados (Request/Response)

### Frame Processing Loop
```python
# Pseudocódigo do app.py main()

for frame_idx, frame in video_source:
    # 1. DETECÇÃO
    detections = detector.detect(frame)  # YOLO
    # Output: [Detection(bbox=[x1,y1,x2,y2], conf=0.92), ...]
    
    # 2. TRACKING
    tracks = tracker.update(detections)  # Centroid ou ByteTrack
    # Output: [Track(id=0, pos=(320, 400), conf=0.92), ...]
    
    # 3. ZONA
    for track in tracks:
        x, y = track.foot_point
        in_zone = zone.contains_point(x, y)  # Point-in-polygon
        
        # 4. REGRAS
        if in_zone and operation_active:
            intrusion = rules.evaluate_intrusion(track.id, timestamp)
            # Lógica: "Primeira vez vendo este track_id na zona?"
            
            if intrusion:
                # 5. EVENTOS + ALARME
                alarm.trigger_alarm("crítica")
                event_mgr.log_intrusion_event(
                    timestamp=timestamp,
                    track_id=track.id,
                    confidence=track.conf,
                    zone=zone.name,
                    frame=frame  # snapshot
                )
    
    # 6. RENDERIZAÇÃO (opcional)
    if display:
        render_frame(frame, tracks, zone)
        cv2.imshow("MUNCK Safety", frame)
```

---

## 4. Pontos Críticos de Implementação

### 4.1 Point-in-Polygon (Zona)
**Problema:** Zona pode ser qualquer polígono. Coordenadas normalizadas (0–1) devem mapear para pixel (0–width).

**Implementação (NumPy ou Shapely):**
```python
# zone.py
import numpy as np
from shapely.geometry import Polygon, Point

class Zone:
    def __init__(self, name, points_normalized):
        """points_normalized: lista de [x, y] em escala 0–1"""
        self.name = name
        self.polygon = Polygon(points_normalized)  # Shapely
    
    def contains_point(self, x_norm, y_norm):
        """Retorna True se ponto está dentro"""
        return self.polygon.contains(Point(x_norm, y_norm))

# Uso
zone = Zone("operational_area", [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
is_inside = zone.contains_point(0.5, 0.5)  # True (centro)
```

**⚠️ Cuidado:** Coordenadas YOLO retornam em pixels. Normalizar antes:
```python
x_norm = bbox_x / frame_width
y_norm = bbox_y / frame_height
```

### 4.2 Tracking & Persistência de track_id
**Problema:** Pessoa sai e volta → deve gerar novo evento (não reutilizar track_id).

**Decisão:** Usar centroid-based ou ByteTrack:
```python
# tracker.py (simplificado)
class SimpleTracker:
    def __init__(self, max_age=30):
        self.tracks = {}  # {track_id: Track(pos, conf, age)}
        self.next_id = 0
    
    def update(self, detections):
        # 1. Associar detections com tracks existentes (distância euclidiana)
        # 2. Remover tracks com age > max_age (pessoa saiu)
        # 3. Criar novos tracks para detections não associadas
        # 4. Retornar lista de tracks ativas
        return list(self.tracks.values())
```

**⚠️ Risco:** Um único objeto YOLO pode ter IDs diferentes em sequências de vídeo diferentes (não há memória entre restarts). Aceito no POC.

### 4.3 Histerese & Cooldown
**Problema:** Pessoa caminha perto da borda → 10 entrads/saídas em 2 segundos.

**Solução:** Cooldown por track_id (não dispara novo evento se já disparou nos últimos N segundos).

```python
# rules.py
class RuleEngine:
    def __init__(self, cooldown_ms=3000):
        self.cooldown_ms = cooldown_ms
        self.last_intrusion_time = {}  # {track_id: timestamp}
    
    def evaluate_intrusion(self, track_id, timestamp_ms):
        """Retorna True se deve disparar alarme"""
        if track_id not in self.last_intrusion_time:
            # Primeira vez
            self.last_intrusion_time[track_id] = timestamp_ms
            return True
        
        elapsed = timestamp_ms - self.last_intrusion_time[track_id]
        if elapsed > self.cooldown_ms:
            # Fora do cooldown, pode disparar novamente
            self.last_intrusion_time[track_id] = timestamp_ms
            return True
        
        # Dentro do cooldown, ignorar
        return False
```

### 4.4 Saída de Eventos (JSONL)
**Formato esperado:**
```json
{"timestamp": 5000, "event": "PERSON_ENTERED_OPERATION_ZONE", "track_id": 0, "confidence": 0.92, "zone": "operational_area"}
```

```python
# event_manager.py
import json
from pathlib import Path
from datetime import datetime

class EventManager:
    def __init__(self, output_dir="artifacts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.events_file = self.output_dir / "events.jsonl"
        self.snapshots_dir = self.output_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)
    
    def log_intrusion_event(self, timestamp_ms, track_id, confidence, zone, frame):
        """Escreve evento + snapshot"""
        event = {
            "timestamp": timestamp_ms,
            "event": "PERSON_ENTERED_OPERATION_ZONE",
            "track_id": track_id,
            "confidence": round(confidence, 3),
            "zone": zone,
            "datetime_iso": datetime.now().isoformat()
        }
        
        # Escreve JSONL
        with open(self.events_file, "a") as f:
            f.write(json.dumps(event) + "\n")
        
        # Snapshot
        snap_path = self.snapshots_dir / f"person_track_{track_id}_{timestamp_ms}ms.jpg"
        cv2.imwrite(str(snap_path), frame)
```

---

## 5. Erros Comuns & Tratamento

### 5.1 Falhas de Hardware (Fase 1 Critical)
**Cenário:** Câmera sai de linha, conexão RTSP cai, disco cheio.

**Regra de Ouro:** Nunca interpretar falha como "ausência de pessoa".

```python
# app.py
try:
    frame = video_source.read()
    if frame is None:
        # Câmera offline
        log_error("CAMERA_OFFLINE", camera_id=0)
        alarm.trigger_alarm("crítica", reason="PERDA_DE_COBERTURA")
        continue  # Skip, não processa
except Exception as e:
    log_error("STREAM_LOST", error=str(e))
    alarm.trigger_alarm("crítica", reason="STREAM_LOST")
    break  # Ou retry com backoff
```

### 5.2 YOLO Falhar ou Model Indisponível
```python
# detector.py
def detect(self, frame):
    if self.model is None:
        log_error("MODEL_UNAVAILABLE")
        alarm.trigger_alarm("crítica", reason="MODEL_UNAVAILABLE")
        return []  # Sem detecções = sem evento, mas alarme técnico disparado
```

### 5.3 Storage Cheio
```python
# event_manager.py
import shutil

def log_intrusion_event(self, ...):
    disk_usage = shutil.disk_usage(self.output_dir)
    if disk_usage.free < 100_000_000:  # < 100MB
        log_error("STORAGE_FULL")
        alarm.trigger_alarm("crítica", reason="STORAGE_FULL")
        # Não escrever snapshot, mas escrever evento
    
    # Escrever evento sempre
    with open(self.events_file, "a") as f:
        f.write(json.dumps(event) + "\n")
```

---

## 6. Testes & Validação

### 6.1 Teste Unitário: Zona
```python
# tests/test_zone.py
import pytest
from munck_safety.zone import Zone

def test_point_inside_zone():
    zone = Zone("test", [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    assert zone.contains_point(0.5, 0.5) == True
    assert zone.contains_point(0.1, 0.1) == False

def test_point_on_edge():
    zone = Zone("test", [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    # Point exatamente na borda (comportamento Shapely: Usually False)
    result = zone.contains_point(0.2, 0.2)
    assert isinstance(result, bool)
```

### 6.2 Teste de Integração: Arquivo MP4 → Eventos
```python
# tests/test_validation.py
def test_person_enters_zone():
    """Vídeo de teste: pessoa entra aos 5s, sai aos 15s"""
    app = MunckApp(
        source="videos/test_person_enters_zone.mp4",
        config="config/test_file.json",
        operation_active=True
    )
    events = app.run()
    
    assert len(events) == 1, f"Expected 1 event, got {len(events)}"
    event = events[0]
    assert event["event"] == "PERSON_ENTERED_OPERATION_ZONE"
    assert 4500 < event["timestamp"] < 5500, f"Timestamp mismatch: {event['timestamp']}"
```

### 6.3 Teste de Histerese
```python
def test_cooldown_histerese():
    """Pessoa entra/sai 3x em 2s (rápido)"""
    app = MunckApp(
        source="videos/test_rapid_entry_exit.mp4",
        config="config/test_cooldown_3000ms.json",
        operation_active=True
    )
    events = app.run()
    
    # Com cooldown=3000ms: apenas 1–2 eventos esperados
    assert len(events) <= 2, f"Too many events with cooldown: {len(events)}"
```

---

## 7. Roadmap de Implementação

### POC v0.1 (Atual)
- ✅ YOLO detecção pessoa
- ✅ Tracking simples (centroid-based ou ByteTrack)
- ✅ Zona polígonal configurável
- ✅ Motor de regras (histerese)
- ✅ Eventos JSONL + snapshots
- ❌ Alarme sonoro (abstração apenas)
- ❌ Múltiplas câmeras
- ❌ Dashboard

### Fase 1.5 (Hardware Prep)
- Integrar com Jetson Orin Nano
- Validar FPS em TensorRT
- Testar 4 RTSP streams simultaneamente
- Implementar alarme físico (relé)

### Fase 2 (EPI & Auditoria)
- YOLO-Pose para keypoints
- Associação EPI → pessoa
- Dashboard web (Streamlit)
- Filtros e busca em eventos
- Trilha de auditoria (quem reconheceu alarme?)
- Retenção de imagens (30 dias)

### Fase 3+ (Expansão)
- Fila de eventos (Redis/Kafka)
- API REST externa
- Integração com SigTI (alertas via SMS/Telegram)
- Modelagem comportamental (pessoas esperadas vs. intrusores)

---

## 8. Dependências & Ambiente

### pyproject.toml (Proposto)
```toml
[project]
name = "munck-safety-system"
version = "0.1.0"
description = "Intrusion detection and safety monitoring for crane operations"
requires-python = ">=3.8"

dependencies = [
    "torch>=2.0,<3",
    "ultralytics>=8.0,<9",
    "opencv-python>=4.7",
    "numpy>=1.20",
    "shapely>=2.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "black>=23.0",
    "ruff>=0.1",
]

jetson = [
    "nvidia-tensorrt>=8.5",
    "gstreamer-python>=1.0",
]

[project.scripts]
munck-safety = "munck_safety.app:main"
```

### Instalação
```bash
# Dev (laptop/desktop)
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Jetson (com TensorRT)
pip install -e ".[jetson]"

# Rodar
python -m munck_safety.app --source 0 --config config/example.json --operation-active
```

---

## 9. Métricas & KPIs

| Métrica | Alvo | Critério |
|---------|------|----------|
| **Detecção Recall** | ≥ 95% | Pessoa na zona é detectada |
| **FP (Falsos Positivos)** | < 2% | Pessoa fora = sem evento |
| **Latência Detecção** | < 500ms | Entrada real → evento |
| **FPS (Tempo Real)** | ≥ 20 | Processamento ao vivo |
| **Uptime** | > 99% | Falhas técnicas isoladas |
| **EI (Evento Intrusão)** | Trilha completa | timestamp + track_id + snapshot |

---

## 10. Referências & Inspiração

- **YOLOv8 Tracking**: https://docs.ultralytics.com/modes/track/
- **ByteTrack**: Simpler and Faster Multi-Object Tracking with Stronger Appearance Association (2022)
- **Shapely (Geometria)**: https://shapely.readthedocs.io/
- **Exemplo Similar**: vision-safety-monitor (GitHub, safety helmet + zone detection)
- **Eventlog (JSONL)**: Padrão de auditoria em sistemas de segurança
