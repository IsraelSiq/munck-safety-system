# Munck Safety System

> Sistema auxiliar de sinalização para operações com guindaste hidráulico (Munck).
> Não controla o equipamento, não substitui procedimentos normativos e não é certificação de conformidade.

---

## O que é

Visão computacional embarcada que monitora a área de atuação do Munck em tempo real, detecta pessoas em zonas de risco, verifica conformidade de EPI e mantém trilha de auditoria completa.

```
4 câmeras IP
    └─► switch PoE
            └─► Jetson Orin Nano
                    ├─► detector de pessoas (YOLO + ByteTrack)
                    ├─► motor de regras (zonas · confirmação · cooldown)
                    ├─► monitor de EPI  (janela temporal · conformidade)
                    ├─► alarme sonoro + evidências
                    └─► dashboard HTTP + SQLite
```

A IA informa detecções, confiança, posição e `track_id`.
O motor de regras — código determinístico e testável — decide se houve intrusão, qual a severidade e qual resposta acionar.

---

## Status das fases

| Fase | Descrição | Status |
|------|-----------|--------|
| **0** | Requisitos, modelagem e POC | ✅ Concluída |
| **1** | Detecção de intrusão multi-câmera | ✅ Concluída · 30/30 testes |
| **2** | EPI, dashboard e auditoria | 🔄 Implementada · pendente testes de campo |
| **3** | Envelope dinâmico e TensorRT | 📋 Planejada |

---

## Instalação

```bash
git clone https://github.com/IsraelSiq/munck-safety-system
cd munck-safety-system

python -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\Activate.ps1   # Windows

pip install -e .
```

### Dependências principais

| Pacote | Função |
|--------|--------|
| `ultralytics` | YOLO + ByteTrack |
| `opencv-python-headless` | captura e preview |
| `shapely` | geometria de zonas (polígonos) |
| `pydantic` | validação de configuração |
| `structlog` | logging estruturado JSON |
| `psutil` | monitoramento de disco/CPU |
| `pygame` | alarme sonoro |

---

## Uso rápido

```bash
# webcam — operação ativa, preview na tela
python -m munck_safety.app \
    --source 0 \
    --config config/example.json \
    --operation-active \
    --show-preview

# arquivo de vídeo (validação sem hardware)
python -m munck_safety.app \
    --source videos/teste_01.mp4 \
    --config config/example.json \
    --operation-active

# URL RTSP (câmera IP real)
python -m munck_safety.app \
    --source rtsp://192.168.1.10:554/stream \
    --config config/example.json \
    --operation-active
```

Dashboard acessível em **http://localhost:8080** após iniciar o sistema.

### Calibrar zonas

```bash
python scripts/calibrate_zone.py \
    --source 0 \
    --camera-id cam_frente_esq \
    --output config/zones_calibrated.json
```

Clique nos vértices da zona com o mouse → Enter para salvar.

---

## Estrutura do projeto

```
munck-safety-system/
├── src/munck_safety/
│   ├── app.py                    # orquestrador principal
│   ├── config.py                 # configuração JSON + Pydantic
│   ├── models.py                 # contratos de dados
│   ├── logging_cfg.py            # logging estruturado
│   ├── camera/
│   │   └── capture.py            # captura com reconexão automática
│   ├── detector/
│   │   └── person_detector.py    # YOLO + ByteTrack
│   ├── rules/
│   │   └── engine.py             # motor de regras (intrusão)
│   ├── ppe/
│   │   ├── detector.py           # detecção de EPI por IoU
│   │   └── monitor.py            # conformidade por janela temporal
│   ├── alarm/
│   │   └── manager.py            # alarme sonoro + snapshot + JSONL
│   ├── dashboard/
│   │   ├── store.py              # persistência SQLite
│   │   └── server.py             # HTTP server (stdlib)
│   └── utils/
│       └── health.py             # heartbeat + watchdog
├── tests/                        # 56 testes unitários
├── scripts/
│   └── calibrate_zone.py         # calibração de zonas com mouse
├── config/
│   └── example.json              # configuração de referência
└── docs/                         # documentação técnica
```

---

## Configuração

O sistema é configurado por um único arquivo JSON:

```jsonc
{
  "cameras": [
    { "camera_id": "cam_frente_esq", "source": "0", "fps": 15 },
    { "camera_id": "cam_frente_dir", "source": "rtsp://..." }
  ],
  "zones": [
    {
      "zone_id": "zona_frente_esq",
      "camera_id": "cam_frente_esq",
      "label": "Zona Frente Esq",
      "points": [
        { "x": 0.1, "y": 0.3 }, { "x": 0.9, "y": 0.3 },
        { "x": 0.9, "y": 0.95 }, { "x": 0.1, "y": 0.95 }
      ]
    }
  ],
  "ppe_zones": [
    {
      "zone_id": "zona_frente_esq",
      "required_ppe": ["HELMET", "VEST"],
      "confirmation_window_s": 5.0,
      "cooldown_s": 30.0
    }
  ],
  "rules": { "confirmation_frames": 3, "cooldown_s": 10.0, "hysteresis_frames": 5 },
  "dashboard": { "enabled": true, "port": 8080 }
}
```

Ver [`config/example.json`](config/example.json) para a configuração completa com 4 câmeras.

---

## Eventos gerados

| Evento | Severidade | Dispara alarme |
|--------|-----------|---------------|
| `INTRUSION_START` | CRITICAL | ✅ Sirene |
| `INTRUSION_END` | INFO | — |
| `PPE_NON_COMPLIANT` | WARNING | ❌ Só evidência |
| `PPE_COMPLIANT` | INFO | — |
| `CAMERA_OFFLINE` | WARNING | — |
| `STREAM_LOST` | WARNING | — |
| `MODEL_UNAVAILABLE` | CRITICAL | — |
| `STORAGE_FULL` | WARNING | — |
| `HEARTBEAT` | INFO | — |
| `SYSTEM_READY` | INFO | — |

**Princípio de segurança:** qualquer falha técnica (`CAMERA_OFFLINE`, `MODEL_UNAVAILABLE` etc.) é sempre explícita — nunca interpretada como ausência de risco.

---

## Testes

```bash
pytest tests/ -v
# 56 passed in 0.88s
```

Os testes cobrem os contratos de segurança críticos:

- Sem operação ativa → nenhum alarme
- Confirmação em exatamente N frames consecutivos
- Histerese antes de encerrar evento
- Cooldown bloqueando flooding
- Falhas técnicas sempre explícitas
- EPI inconclusivo não gera violação (fail-safe)

---

## Documentação

| Documento | Conteúdo |
|-----------|----------|
| [ROADMAP](docs/ROADMAP.md) | Fases, entregas e critérios de conclusão |
| [VALIDATION](docs/VALIDATION.md) | Estratégia de validação sem hardware |
| [MUNCK-MODEL](docs/MUNCK-MODEL.md) | Modelagem do equipamento e zonas |
| [POC-v0.1](docs/POC-v0.1.md) | Contrato e critérios da prova de conceito |
| [REFERENCES](docs/REFERENCES.md) | Projetos e referências relacionados |

---

## Guia de contribuição rápida

```bash
# criar branch
git checkout -b feat/minha-feature

# rodar testes antes de commitar
pytest tests/ -v

# padrão de commit
git commit -m "feat(rules): adiciona suporte a zona dinâmica por ângulo de lança"
```

Tipos de commit: `feat` · `fix` · `test` · `docs` · `chore` · `refactor`
