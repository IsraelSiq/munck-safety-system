# MUNCK Safety System — Quick Start & Implementação Prática

## 0. Setup Inicial (5 min)

```bash
# Clone + ambiente
git clone https://github.com/siqueiraisrael-wq/munck-safety-system
cd munck-safety-system

# Virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.\.venv\Scripts\activate  # Windows

# Dependências
pip install -e .
# Se quiser dev tools também:
pip install -e ".[dev]"

# Verificar YOLO (baixa modelo na primeira execução)
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

---

## 1. Primeira Execução (Webcam - 2 min)

```bash
# Teste rápido com webcam
python -m munck_safety.app \
  --source 0 \
  --config config/example.json \
  --operation-active

# Se não houver config/example.json, criar:
```

### Criar `config/example.json`
```json
{
  "model": "yolov8n.pt",
  "zone": {
    "name": "operacao",
    "points_normalized": [
      [0.2, 0.2],
      [0.8, 0.2],
      [0.8, 0.8],
      [0.2, 0.8]
    ]
  },
  "cooldown_ms": 3000,
  "display": true,
  "artifacts_dir": "artifacts/"
}
```

**O que observar:**
- Uma janela se abre (OpenCV)
- Zona é desenhada (retângulo verde)
- Você entra na zona → evento JSON é criado em `artifacts/events.jsonl`
- Snapshot é salvo em `artifacts/`

---

## 2. Estrutura de Código (Copiar-Colar)

### 2.1 `src/munck_safety/detector.py`
```python
from ultralytics import YOLO
import numpy as np

class Detection:
    """Resultado de uma detecção YOLO"""
    def __init__(self, bbox, confidence, class_name="person"):
        self.bbox = bbox  # [x1, y1, x2, y2]
        self.confidence = confidence
        self.class_name = class_name
    
    @property
    def foot_point_normalized(self, frame_width, frame_height):
        """Ponto inferior central da bbox (em pixels)"""
        x1, y1, x2, y2 = self.bbox
        x_center = (x1 + x2) / 2
        y_bottom = y2
        return (x_center / frame_width, y_bottom / frame_height)

class YOLODetector:
    """Wrapper de detecção YOLO"""
    def __init__(self, model_name="yolov8n.pt"):
        self.model = YOLO(model_name)
    
    def detect(self, frame) -> list:
        """
        Input: frame (BGR, numpy array)
        Output: list de Detection
        """
        results = self.model(frame, conf=0.5, verbose=False)
        detections = []
        
        for result in results:
            for box in result.boxes:
                if int(box.cls) == 0:  # Classe 0 = pessoa
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0])
                    detections.append(
                        Detection(
                            bbox=[x1, y1, x2, y2],
                            confidence=conf
                        )
                    )
        
        return detections
```

### 2.2 `src/munck_safety/tracker.py`
```python
import numpy as np

class Track:
    """Faixa de rastreamento de pessoa"""
    def __init__(self, track_id, detection, frame_width, frame_height):
        self.id = track_id
        self.detection = detection
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.age = 0
        self.last_seen = 0
    
    @property
    def foot_point_normalized(self):
        """Ponto dos pés normalizado (0–1)"""
        x1, y1, x2, y2 = self.detection.bbox
        x_center = (x1 + x2) / 2
        y_bottom = y2
        return (x_center / self.frame_width, y_bottom / self.frame_height)
    
    def distance_to(self, detection):
        """Distância euclidiana entre centroides"""
        x1, y1, x2, y2 = self.detection.bbox
        x1_new, y1_new, x2_new, y2_new = detection.bbox
        
        cx_old = (x1 + x2) / 2
        cy_old = (y1 + y2) / 2
        
        cx_new = (x1_new + x2_new) / 2
        cy_new = (y1_new + y2_new) / 2
        
        return np.sqrt((cx_old - cx_new)**2 + (cy_old - cy_new)**2)

class SimpleTracker:
    """Rastreador centroid-based"""
    def __init__(self, max_age=30, distance_threshold=50):
        self.tracks = {}  # {track_id: Track}
        self.next_id = 0
        self.max_age = max_age
        self.distance_threshold = distance_threshold
    
    def update(self, detections, frame_width, frame_height):
        """
        Input: lista de Detection
        Output: lista de Track (ativas)
        """
        # 1. Associar detections com tracks (nearest neighbor)
        used_detections = set()
        for track_id, track in list(self.tracks.items()):
            if len(detections) == 0:
                track.age += 1
                if track.age > self.max_age:
                    del self.tracks[track_id]
                continue
            
            # Encontrar detection mais próximo
            min_distance = float('inf')
            best_det_idx = -1
            for det_idx, det in enumerate(detections):
                if det_idx in used_detections:
                    continue
                dist = track.distance_to(det)
                if dist < min_distance:
                    min_distance = dist
                    best_det_idx = det_idx
            
            if best_det_idx >= 0 and min_distance < self.distance_threshold:
                # Associar
                track.detection = detections[best_det_idx]
                track.age = 0
                track.last_seen = 0
                used_detections.add(best_det_idx)
            else:
                track.last_seen += 1
                track.age += 1
                if track.age > self.max_age:
                    del self.tracks[track_id]
        
        # 2. Criar novos tracks para detections não associadas
        for det_idx, det in enumerate(detections):
            if det_idx not in used_detections:
                self.tracks[self.next_id] = Track(
                    self.next_id, det, frame_width, frame_height
                )
                self.next_id += 1
        
        return list(self.tracks.values())
```

### 2.3 `src/munck_safety/zone.py`
```python
from shapely.geometry import Polygon, Point

class Zone:
    """Zona poligonal de operação"""
    def __init__(self, name, points_normalized):
        """
        points_normalized: lista de [x, y] em escala 0–1
        """
        self.name = name
        self.polygon = Polygon(points_normalized)
    
    def contains_point(self, x_norm, y_norm) -> bool:
        """Retorna True se (x, y) está dentro da zona"""
        return self.polygon.contains(Point(x_norm, y_norm))
    
    def draw_on_frame(self, frame):
        """Desenha zona no frame (overlay)"""
        import cv2
        import numpy as np
        
        h, w = frame.shape[:2]
        
        # Converter para pixel coordinates
        exterior = np.array(self.polygon.exterior.coords[:-1], dtype=np.int32)
        exterior = (exterior * np.array([w, h])).astype(np.int32)
        
        # Desenhar
        cv2.polylines(frame, [exterior], True, (0, 255, 0), 2)
        
        return frame
```

### 2.4 `src/munck_safety/rules.py`
```python
class RuleEngine:
    """Motor de regras (Fase 1: intrusão)"""
    def __init__(self, cooldown_ms=3000):
        self.cooldown_ms = cooldown_ms
        self.last_intrusion_time = {}  # {track_id: timestamp_ms}
    
    def evaluate_intrusion(self, track_id, timestamp_ms, operation_active=True) -> bool:
        """
        Decide se dispara alarme (intrusão detectada)
        
        Lógica:
        1. Se não é operação ativa → False
        2. Se nunca vimos este track_id na zona → True (primeira vez)
        3. Se já vimos mas passou cooldown → True
        4. Se está dentro do cooldown → False
        """
        if not operation_active:
            return False
        
        if track_id not in self.last_intrusion_time:
            # Primeira vez
            self.last_intrusion_time[track_id] = timestamp_ms
            return True
        
        elapsed = timestamp_ms - self.last_intrusion_time[track_id]
        if elapsed > self.cooldown_ms:
            # Fora do cooldown
            self.last_intrusion_time[track_id] = timestamp_ms
            return True
        
        # Dentro do cooldown
        return False
```

### 2.5 `src/munck_safety/event_manager.py`
```python
import json
from pathlib import Path
import cv2

class EventManager:
    """Gerenciador de eventos e snapshots"""
    def __init__(self, output_dir="artifacts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.events_file = self.output_dir / "events.jsonl"
        self.snapshots_dir = self.output_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)
    
    def log_intrusion_event(self, timestamp_ms, track_id, confidence, 
                           zone_name, frame):
        """Escreve evento JSONL + snapshot"""
        event = {
            "timestamp": timestamp_ms,
            "event": "PERSON_ENTERED_OPERATION_ZONE",
            "track_id": track_id,
            "confidence": round(float(confidence), 3),
            "zone": zone_name
        }
        
        # Escrever evento
        with open(self.events_file, "a") as f:
            f.write(json.dumps(event) + "\n")
        
        # Salvar snapshot
        snap_name = f"person_track_{track_id}_{timestamp_ms}ms.jpg"
        snap_path = self.snapshots_dir / snap_name
        cv2.imwrite(str(snap_path), frame)
        
        print(f"✅ Evento gravado: track_id={track_id}, zone={zone_name}")
```

### 2.6 `src/munck_safety/app.py` (Main Loop)
```python
import argparse
import json
import cv2
from pathlib import Path
from .detector import YOLODetector
from .tracker import SimpleTracker
from .zone import Zone
from .rules import RuleEngine
from .event_manager import EventManager

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="0", help="0=webcam, caminho=arquivo, URL=RTSP")
    parser.add_argument("--config", default="config/example.json", help="Config JSON")
    parser.add_argument("--operation-active", action="store_true", help="Operação ativa")
    args = parser.parse_args()
    
    # Carregar config
    with open(args.config) as f:
        config = json.load(f)
    
    # Inicializar componentes
    detector = YOLODetector(config.get("model", "yolov8n.pt"))
    tracker = SimpleTracker()
    zone = Zone(config["zone"]["name"], config["zone"]["points_normalized"])
    rules = RuleEngine(config.get("cooldown_ms", 3000))
    event_mgr = EventManager(config.get("artifacts_dir", "artifacts/"))
    
    # Abrir vídeo
    source = args.source
    if source == "0":
        cap = cv2.VideoCapture(0)
    else:
        cap = cv2.VideoCapture(source)
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        h, w = frame.shape[:2]
        timestamp_ms = frame_count * (1000 / 30)  # Assumir 30 FPS
        
        # 1. Detecção
        detections = detector.detect(frame)
        
        # 2. Tracking
        tracks = tracker.update(detections, w, h)
        
        # 3. Processamento de zona + regras
        for track in tracks:
            x_norm, y_norm = track.foot_point_normalized
            in_zone = zone.contains_point(x_norm, y_norm)
            
            if in_zone:
                # 4. Avaliar regra
                should_alarm = rules.evaluate_intrusion(
                    track.id, 
                    int(timestamp_ms),
                    operation_active=args.operation_active
                )
                
                if should_alarm:
                    # 5. Registrar evento
                    event_mgr.log_intrusion_event(
                        int(timestamp_ms),
                        track.id,
                        track.detection.confidence,
                        zone.name,
                        frame
                    )
                    # TODO: Alarme sonoro
        
        # 6. Render (optional)
        if config.get("display", True):
            frame_display = zone.draw_on_frame(frame.copy())
            
            # Desenhar detecções
            for detection in detections:
                x1, y1, x2, y2 = detection.bbox
                cv2.rectangle(frame_display, (int(x1), int(y1)), (int(x2), int(y2)), 
                            (0, 255, 0), 2)
                cv2.putText(frame_display, f"Conf: {detection.confidence:.2f}", 
                          (int(x1), int(y1) - 5), cv2.FONT_HERSHEY_SIMPLEX, 
                          0.5, (0, 255, 0), 1)
            
            cv2.imshow("MUNCK Safety System", frame_display)
        
        # ESC to exit
        if cv2.waitKey(1) & 0xFF == 27:
            break
        
        frame_count += 1
    
    cap.release()
    cv2.destroyAllWindows()
    print(f"✅ Processamento concluído. Eventos em: {event_mgr.events_file}")

if __name__ == "__main__":
    main()
```

---

## 3. Testes Rápidos

### 3.1 Teste Unitário: Zona
```bash
# tests/test_zone.py
pytest tests/test_zone.py -v
```

**Conteúdo:**
```python
from munck_safety.zone import Zone

def test_point_inside():
    zone = Zone("test", [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    assert zone.contains_point(0.5, 0.5) == True

def test_point_outside():
    zone = Zone("test", [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    assert zone.contains_point(0.1, 0.1) == False

pytest.main([__file__, "-v"])
```

### 3.2 Teste com Vídeo MP4
```bash
# Gravar 20s de webcam de teste
python -c "
import cv2
cap = cv2.VideoCapture(0)
out = cv2.VideoWriter('videos/test.mp4', cv2.VideoWriter_fourcc(*'mp4v'), 30, (640, 480))
for i in range(600):
    ret, frame = cap.read()
    out.write(frame)
cap.release()
out.release()
print('✅ Vídeo salvo: videos/test.mp4')
"

# Rodar sobre o vídeo
python -m munck_safety.app \
  --source videos/test.mp4 \
  --config config/example.json \
  --operation-active

# Verificar eventos
cat artifacts/events.jsonl
```

---

## 4. Checklist de Implementação

- [ ] **Estrutura de pastas**
  ```
  src/munck_safety/
  ├── __init__.py
  ├── app.py
  ├── detector.py
  ├── tracker.py
  ├── zone.py
  ├── rules.py
  ├── event_manager.py
  └── __main__.py
  ```

- [ ] **Dependências instaladas**
  ```
  pip install -e .
  ```

- [ ] **Config JSON criada**
  ```
  config/example.json (copiar exemplo acima)
  ```

- [ ] **Teste rápido (webcam)**
  ```
  python -m munck_safety.app --source 0 --config config/example.json --operation-active
  Entra na zona → evento deve aparecer em artifacts/events.jsonl
  ```

- [ ] **Teste com vídeo**
  ```
  python -m munck_safety.app --source videos/test.mp4 --config config/example.json
  ```

- [ ] **Testes unitários**
  ```
  pytest tests/ -v
  ```

---

## 5. Troubleshooting

### Problema: "ModuleNotFoundError: No module named 'munck_safety'"
**Solução:**
```bash
pip install -e .
# Garanta estar no diretório raiz do projeto
```

### Problema: "Could not find a suitable module for YOLO model"
**Solução:**
```bash
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
# Baixa o modelo na primeira execução (~50MB)
```

### Problema: "No camera found" (webcam não funciona)
**Solução:**
```bash
# Testar com arquivo em vez de webcam
python -m munck_safety.app --source videos/test.mp4 --config config/example.json
```

### Problema: "artifacts/ folder not found"
**Solução:**
```bash
mkdir artifacts
# Ou deixar o código criar (já está implementado)
```

---

## 6. Próximos Passos

1. **Copiar snippets** dos arquivos acima
2. **Rodar com webcam** (2 min)
3. **Gravar vídeo de teste** com pessoa entrando/saindo zona (5 min)
4. **Rodar sobre vídeo** e validar eventos (2 min)
5. **Criar 3–5 vídeos determinísticos** (benchmark)
6. **Implementar testes** em `tests/` (com pytest)
7. **Preparar Jetson** (quando hardware disponível)

---

## 7. Links Úteis

- **Projeto GitHub**: https://github.com/siqueiraisrael-wq/munck-safety-system
- **YOLO Docs**: https://docs.ultralytics.com/
- **Shapely (Geometria)**: https://shapely.readthedocs.io/
- **ByteTrack Paper**: https://arxiv.org/abs/2110.06864
- **Exemplo Similar**: https://github.com/MrPhuocTan/vision-safety-monitor

