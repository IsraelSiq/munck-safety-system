# MUNCK Safety System — Plano de Validação sem Hardware

## Objetivo
Validar a detecção de intrusão em zonas e geração de eventos **sem comprar câmeras, Jetson ou equipamento físico**. Usar vídeos reais/licenciados, webcam e streams simuladas.

---

## 1. Estrutura de Testes (Pirâmide)

```
         🎬 Testes End-to-End (vídeos sintetizados)
       ↗️  ↖️
      Testes de Integração (zona + regras + eventos)
    ↗️  ↖️
   Testes Unitários (detecção, tracking, zona)
```

### Nível 1: Unitários (Cada módulo isolado)
- **Detecção YOLO**: Entrada = imagem > Saída = bounding boxes
- **Tracking**: Entrada = frames + detecções > Saída = track IDs persistentes
- **Zona**: Entrada = ponto (x, y) + polígono > Saída = bool (dentro/fora)
- **Regras**: Entrada = {detecção, track_id, zona} > Saída = {intrusão, severidade}

### Nível 2: Integração (Fluxo completo)
- Vídeo → Detecção → Tracking → Zona → Regras → Evento JSON
- Entrada: `videos/teste_01.mp4`
- Saída: `artifacts/events.jsonl` + snapshots
- Validar: eventos com timestamp, track_id, confiança

### Nível 3: E2E (Cenários realistas)
- Video com **entrada esperada** e **saída esperada**
- Ex: pessoa entra zona às 0:05s → evento deve ter timestamp ~5000ms

---

## 2. Dados de Teste Organizados

### 2.1 Vídeos de Referência (Licenciados)
Fonte: Se disponível, usar vídeos de segurança públicos ou criar com webcam controlada.

**Estrutura de pasta:**
```
videos/
├── test_person_enters_zone.mp4       # Determinístico: entra aos 5s, sai aos 15s
├── test_multiple_people.mp4           # 3 pessoas, apenas 2 em zona
├── test_false_positive_guard.mp4      # Pessoa fora da zona (não deve gerar evento)
├── test_rapid_entry_exit.mp4          # Múltiplas entradas/saídas (histerese)
└── test_occlusion.mp4                 # Pessoa parcialmente ocluída
```

### 2.2 Zona de Testes (JSON)
```json
{
  "zone_name": "operational_area",
  "points_normalized": [
    [0.2, 0.2],  // top-left
    [0.8, 0.2],  // top-right
    [0.8, 0.8],  // bottom-right
    [0.2, 0.8]   // bottom-left
  ]
}
```

### 2.3 Matriz de Testes
| # | Cenário | Entrada | Saída Esperada | Status |
|---|---------|---------|----------------|--------|
| T1 | Pessoa entra zona | test_person_enters_zone.mp4 | 1 evento PERSON_ENTERED | ⏳ |
| T2 | Pessoa fora zona | test_false_positive_guard.mp4 | 0 eventos | ⏳ |
| T3 | Múltiplas pessoas | test_multiple_people.mp4 | 2 eventos (só zona) | ⏳ |
| T4 | Histerese/cooldown | test_rapid_entry_exit.mp4 | 1–2 eventos (cooldown=5s) | ⏳ |
| T5 | Oclusão parcial | test_occlusion.mp4 | 1 evento (confiança >0.5) | ⏳ |

---

## 3. Validação Sem Hardware: Estratégia

### 3.1 Webcam (Teste Controlado)
```bash
# Setup: uma sala branca, marcadores de zona no chão
python -m munck_safety.app \
  --source 0 \
  --config config/test_webcam.json \
  --operation-active

# Executar:
# 1. Ficar fora da zona (5s) → sem eventos
# 2. Entrar na zona (5s) → evento PERSON_ENTERED
# 3. Sair e re-entrar (3x) → validar cooldown
# 4. Histerese: passar perto da borda 10x → contar eventos
```

### 3.2 Arquivo MP4 (Testes Determinísticos)
```bash
python -m munck_safety.app \
  --source videos/test_person_enters_zone.mp4 \
  --config config/test_file.json \
  --operation-active

# Saída esperada em artifacts/:
# events.jsonl:
#   {"timestamp": 5000, "event": "PERSON_ENTERED_OPERATION_ZONE", "track_id": 0, "confidence": 0.92}
#
# snapshots/:
#   person_track_0_5000ms.jpg (frame onde pessoa entrou)
```

### 3.3 Quatro Fontes Virtuais (Simulação Jetson)
```python
# src/munck_safety/multi_source.py (NOVO)

from threading import Thread
import cv2

class VirtualCameraPool:
    """4 câmeras simuladas = 4 threads de vídeos em paralelo"""
    
    def __init__(self, video_paths):
        self.sources = [
            cv2.VideoCapture(video_paths[0]),  # NE
            cv2.VideoCapture(video_paths[1]),  # NW
            cv2.VideoCapture(video_paths[2]),  # SE
            cv2.VideoCapture(video_paths[3]),  # SW
        ]
        self.frames = [None] * 4
    
    def start(self):
        for i, cap in enumerate(self.sources):
            t = Thread(target=self._read_loop, args=(i, cap))
            t.daemon = True
            t.start()
    
    def _read_loop(self, idx, cap):
        while True:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
            self.frames[idx] = frame
    
    def get_all(self):
        return self.frames

# Configuração para 4 câmeras
config_4cameras = {
    "sources": [
        "videos/northeast_corner.mp4",
        "videos/northwest_corner.mp4",
        "videos/southeast_corner.mp4",
        "videos/southwest_corner.mp4"
    ],
    "zones": {
        "camera_0": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
        "camera_1": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
        "camera_2": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
        "camera_3": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
    }
}
```

### 3.4 Métricas de Validação
```python
# tests/test_validation.py

import json
from pathlib import Path

def validate_events_file(events_path, expected_count, confidence_threshold=0.5):
    """Validar saída em JSONL"""
    with open(events_path) as f:
        events = [json.loads(line) for line in f]
    
    # Verificações
    assert len(events) == expected_count, f"Expected {expected_count} events, got {len(events)}"
    for evt in events:
        assert evt["confidence"] >= confidence_threshold
        assert "timestamp" in evt
        assert evt["event"] == "PERSON_ENTERED_OPERATION_ZONE"
        assert isinstance(evt["track_id"], int)
    
    return True

def validate_snapshots(artifacts_dir, expected_count):
    """Validar presença de snapshots"""
    snapshots = list(Path(artifacts_dir).glob("*.jpg"))
    assert len(snapshots) == expected_count, f"Expected {expected_count} snapshots, got {len(snapshots)}"
    for snap in snapshots:
        assert snap.stat().st_size > 1000, f"{snap} is too small"
    return True

# Exemplo de execução
if __name__ == "__main__":
    assert validate_events_file(
        "artifacts/events.jsonl",
        expected_count=1,
        confidence_threshold=0.5
    )
    assert validate_snapshots("artifacts", expected_count=1)
    print("✅ Validação passou!")
```

---

## 4. Cenários Determinísticos (Vídeos com Ground Truth)

### T1: Pessoa Entra Zona (5s)
**Vídeo gerado (ou gravado):**
- 0–4s: pessoa fora da zona (deve passar desapercebida)
- 5s: pessoa entra na zona → **EVENTO DISPARADO**
- 5–14s: pessoa se move dentro da zona
- 15s: pessoa sai → não dispara novo evento (já foi visto)

**Validação:**
```json
{
  "expected_events": 1,
  "expected_timestamp": 5000,
  "expected_track_id": 0,
  "min_confidence": 0.5
}
```

### T2: Histerese & Cooldown (Entrada/Saída Rápida)
**Vídeo:**
- 0–1s: entra (evento 1)
- 1–2s: sai
- 2–2.5s: re-entra rapidamente

**Validação:**
```
Se cooldown=3s:
  - Evento 1 @ 1000ms (entrada)
  - Evento 2 @ 2500ms (re-entrada, fora do cooldown = 1.5s < 3s)
  
Se cooldown=2s:
  - Evento 1 @ 1000ms
  - Evento 2 @ 2500ms (1.5s depois, dentro do cooldown = NÃO DISPARA)
  - Evento 3 @ 5000ms (re-entrada após cooldown)
```

### T3: Múltiplas Pessoas (Tracking Robusto)
**Vídeo:** 3 pessoas, 2 entram, 1 fica fora

**Validação:**
```json
{
  "expected_events": 2,
  "track_ids": [0, 1],
  "outside_person_track_id": 2,
  "outside_person_should_not_appear": true
}
```

---

## 5. Checklist de Implementação

### Fase 1: Infraestrutura
- [ ] Criar pasta `videos/test_*` com 3+ vídeos determinísticos
- [ ] Criar `tests/test_validation.py` com funções de verificação
- [ ] Configurar `pyproject.toml` para rodar testes: `pytest tests/`
- [ ] Adicionar `JSONL + Snapshots` como saída padrão em `EventManager`

### Fase 2: Validação Unitária
- [ ] **Detecção YOLO**: teste imagem única → bounding box
- [ ] **Tracking**: teste 3 frames → IDs persistentes
- [ ] **Zona**: teste ponto dentro/fora polígono
- [ ] **Regras**: teste {detecção, track, zona} → intrusão bool

### Fase 3: Validação Integrada (1 câmera)
- [ ] Rodar em MP4 (T1: pessoa entra)
- [ ] Rodar webcam manual (5 min de testes)
- [ ] Validar `events.jsonl` + snapshots
- [ ] Documentar tempo de processamento (FPS, latência)

### Fase 4: Multi-câmera Simulada
- [ ] Implementar `VirtualCameraPool`
- [ ] Rodar 4 vídeos em paralelo
- [ ] Consolidar eventos de todas 4 câmeras
- [ ] Validar sem conflito de track_id

### Fase 5: Testes Regressão
- [ ] Adicionar GitHub Actions: `pytest` em cada push
- [ ] Incluir testes no CI/CD antes de aceitar PRs
- [ ] Manter vídeos determinísticos no repo (ou LFS)

---

## 6. Métricas de Sucesso

| Métrica | Critério | Status |
|---------|----------|--------|
| **Precisão de Zona** | Pessoa dentro = evento ✅ / fora = sem evento ✅ | ⏳ |
| **Latência** | < 500ms entre entrada real e evento | ⏳ |
| **FPS** | ≥ 20 FPS com YOLO em Jetson (ou 30 FPS webcam) | ⏳ |
| **Confiabilidade** | 0 falsos negativos em 100 entradas | ⏳ |
| **Cobertura de Zona** | 4 câmeras = 4 zonas sem sobreposição | ⏳ |

---

## 7. Estrutura de Código Proposta

```
munck_safety/
├── app.py                     # CLI entry point
├── detector.py               # YOLO wrapper
├── tracker.py                # Tracking logic
├── zone.py                   # Zona polygon logic
├── rules.py                  # Rule engine
├── event_manager.py          # JSONL + snapshots
├── multi_source.py           # [NEW] 4 câmeras virtuais
└── validation/               # [NEW]
    ├── __init__.py
    ├── video_generator.py    # Cria vídeos determinísticos
    └── metrics.py            # Valida eventos

tests/
├── test_detection.py         # YOLO
├── test_tracking.py          # IDs persistentes
├── test_zone.py              # Polígono
├── test_rules.py             # Motor
├── test_validation.py        # End-to-end
└── fixtures/
    ├── test_person_enters_zone.mp4
    ├── test_multiple_people.mp4
    └── ground_truth/
        ├── events_t1.json
        ├── events_t2.json
        └── events_t3.json

docs/
├── VALIDATION.md             # Este arquivo
├── POC-v0.1.md               # Contrato
└── ROADMAP.md                # Fases
```

---

## 8. Próximas Ações (Ordem de Execução)

1. **Hoje**: Gravar/obter 3 vídeos de teste determinísticos (pessoas entrando/saindo zona)
2. **Semana 1**: Implementar `tests/test_validation.py` + `EventManager` JSONL
3. **Semana 2**: Rodar em arquivo (MP4) + webcam + validar eventos
4. **Semana 3**: Implementar `VirtualCameraPool` + testes 4-câmeras
5. **Semana 4**: Preparar Jetson + TensorRT (ou manter YOLO CPU se suficiente)

---

## Referências

- YOLO Tracking: https://docs.ultralytics.com/modes/track/
- OpenCV Zone Detection: https://stackoverflow.com/questions/33748967/opencv-python-point-in-contour
- Event-Driven Architecture: Similar ao projeto `vision-safety-monitor`
- Hardware: Jetson Orin Nano 8GB (~$200, quando aplicável)
