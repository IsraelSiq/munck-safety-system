# Validação — Munck Safety System

## Estratégia geral

Validar o sistema em camadas antes de colocar hardware no campo:

```
Nível 1  Testes unitários          → motor de regras isolado (sem câmera, sem modelo)
Nível 2  Vídeo determinístico      → comportamento com entrada/saída conhecidas
Nível 3  Webcam controlada         → integração end-to-end em ambiente real
Nível 4  4 fontes virtuais         → comportamento multi-câmera sem Jetson
Nível 5  RTSP local simulado       → protocolo de câmera IP real
Nível 6  Hardware real             → Jetson + câmeras + Munck
```

---

## Nível 1 — Testes unitários (implementado)

```bash
pytest tests/ -v
# 56 passed
```

### Contratos testados

| Teste | Requisito validado |
|-------|--------------------|
| `test_sem_operacao_ativa_nao_gera_intrusao` | Operação inativa → silêncio total |
| `test_intrusao_confirmada_apos_n_frames` | Confirmação em exatamente N frames |
| `test_pé_fora_da_zona_nao_gera_intrusao` | Ponto dos pés decide (não centroide) |
| `test_intrusao_encerrada_apos_m_frames_fora` | Histerese antes de encerrar |
| `test_segundo_evento_bloqueado_durante_cooldown` | Sem flooding por track |
| `test_zona_de_outra_camera_ignorada` | Escopo de câmera respeitado |
| `test_camera_sem_frame_torna_offline` | Falha explícita, nunca silenciosa |
| `test_modelo_indisponivel_gera_evento_critico` | MODEL_UNAVAILABLE crítico |
| `test_status_failed_sem_modelo` | Sistema em FAILED sem modelo |
| `test_heartbeat_emitido_apos_intervalo` | Watchdog ativo |
| `test_epi_ausente_apos_janela_gera_evento` | PPE: janela temporal respeitada |
| `test_violacao_severidade_warning_nao_critical` | EPI: WARNING, sem sirene |
| `test_modelo_indisponivel_nao_gera_violacao` | PPE fail-safe: inconclusivo ≠ violação |

---

## Nível 2 — Vídeos determinísticos

### Como criar

```bash
# Gravar cena controlada com webcam
python -c "
import cv2
cap = cv2.VideoCapture(0)
out = cv2.VideoWriter('videos/cenario_01_entrada_saida.mp4',
                      cv2.VideoWriter_fourcc(*'mp4v'), 15, (1280, 720))
for i in range(300):  # 20s a 15fps
    ret, frame = cap.read()
    out.write(frame)
cap.release(); out.release()
"
```

### Dataset de aceitação

| Cenário | Arquivo | Eventos esperados |
|---------|---------|-------------------|
| Pessoa fora da zona | `cenario_00_fora.mp4` | Nenhum |
| Entrada única | `cenario_01_entrada.mp4` | 1× INTRUSION_START |
| Entrada e saída | `cenario_02_entrada_saida.mp4` | 1× START + 1× END |
| Duas pessoas | `cenario_03_dois.mp4` | 2× START (track_ids diferentes) |
| Operação inativa | `cenario_04_inativo.mp4` | Nenhum alarme crítico |
| Perda de stream | `cenario_05_offline.mp4` | CAMERA_OFFLINE explícito |
| EPI ausente | `cenario_06_sem_capacete.mp4` | PPE_NON_COMPLIANT após 5s |
| EPI presente | `cenario_07_com_epi.mp4` | Nenhuma violação |

### Como rodar

```bash
python -m munck_safety.app \
    --source videos/cenario_01_entrada.mp4 \
    --config config/example.json \
    --operation-active

# Verificar eventos gerados
cat artifacts/events.jsonl | python3 -m json.tool
```

---

## Nível 3 — Webcam controlada

```bash
python -m munck_safety.app \
    --source 0 \
    --config config/example.json \
    --operation-active \
    --show-preview
```

**Checklist:**
- [ ] Zona desenhada corretamente na tela
- [ ] Pessoa fora → sem evento
- [ ] Pessoa entra → INTRUSION_START após 3 frames (≈ 0,2 s a 15 FPS)
- [ ] Pessoa sai → INTRUSION_END após 5 frames (≈ 0,33 s a 15 FPS)
- [ ] Snapshot salvo em `artifacts/`
- [ ] Dashboard acessível em http://localhost:8080

---

## Nível 4 — 4 fontes virtuais em paralelo

```bash
# Reproduzir 4 arquivos como câmeras virtuais simultâneas
python -m munck_safety.app --config config/four_virtual.json --operation-active
```

### `config/four_virtual.json`

```json
{
  "cameras": [
    { "camera_id": "cam_frente_esq", "source": "videos/cenario_01.mp4" },
    { "camera_id": "cam_frente_dir", "source": "videos/cenario_02.mp4" },
    { "camera_id": "cam_tras_esq",   "source": "videos/cenario_00.mp4" },
    { "camera_id": "cam_tras_dir",   "source": "videos/cenario_04.mp4" }
  ]
}
```

**Métricas a medir:**
- FPS efetivo por câmera
- Latência intrusão → alarme (câmera com evento)
- CPU/RAM no host de desenvolvimento
- Ausência de eventos duplicados entre câmeras

---

## Nível 5 — RTSP local simulado

```bash
# Instalar ffmpeg e servir arquivo como RTSP local
# (requer rtsp-simple-server ou mediamtx)
mediamtx &
ffmpeg -re -i videos/cenario_01.mp4 -c copy -f rtsp rtsp://localhost:8554/cam1

# Usar URL RTSP no config
# "source": "rtsp://localhost:8554/cam1"
```

---

## Nível 6 — Hardware real (Jetson + câmeras)

### Checklist de hardware

- [ ] Jetson Orin Nano com JetPack 6.x
- [ ] 4 câmeras IP com RTSP (resolução ≥ 720p, FPS ≥ 15)
- [ ] Switch PoE com portas suficientes
- [ ] Armazenamento ≥ 32 GB (SSD ou NVMe)
- [ ] Saída de áudio para alarme sonoro

### Instalação no Jetson

```bash
# Instalar dependências
sudo apt-get install -y python3-pip python3-venv

# Instalar PyTorch para Jetson (versão compatível com JetPack)
# Ver: https://forums.developer.nvidia.com/t/pytorch-for-jetson

pip install -e .

# Testar com 1 câmera antes de escalar para 4
python -m munck_safety.app \
    --source rtsp://192.168.1.10:554/stream \
    --config config/jetson.json \
    --operation-active
```

### Métricas de aceitação de campo

| Métrica | Meta |
|---------|------|
| FPS por câmera (4 simultâneas) | ≥ 10 |
| Latência intrusão → alarme | ≤ 3 s |
| Falso positivo / hora | < 2 |
| Falso negativo / entrada intencional | < 5% |
| Tempo de reconexão de câmera | ≤ 10 s |
| Uptime no turno (8h) | ≥ 99% |

---

## Métricas de regressão (executar após cada PR)

```bash
# Suite completa de testes unitários
pytest tests/ -v --tb=short

# Checar cobertura mínima dos módulos críticos
pytest tests/ --cov=munck_safety.rules --cov=munck_safety.ppe --cov-report=term-missing
```
