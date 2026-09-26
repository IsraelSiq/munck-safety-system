# Roadmap — Munck Safety System

## Visão geral

```
Fase 0  Requisitos e modelagem         ✅ Concluída
Fase 1  Detecção de intrusão           ✅ Concluída
Fase 2  EPI e gestão auditável         🔄 Em andamento
Fase 3  Envelope dinâmico e produto    📋 Planejada
```

---

## ✅ Fase 0 — Requisitos e modelagem

**Objetivo:** definir contratos, limites e critérios antes de escrever código de produção.

**Entregues:**
- Escopo delimitado: sistema auxiliar de sinalização, sem controle do Munck
- Modelagem inicial do IM-45 (dimensões, alcance, giro)
- Pipeline de dados definido: câmera → detecção → zona → regra → alarme → evidência
- Separação explícita entre IA (detector) e regras de segurança (motor)
- Estratégia de validação sem hardware (arquivos, webcam, 4 fontes virtuais)
- POC v0.1: uma fonte, uma zona, intrusão, snapshot

---

## ✅ Fase 1 — Detecção de intrusão multi-câmera

**Objetivo:** detectar pessoa na zona durante operação ativa, soar alarme e registrar evidência auditável com 4 câmeras.

**Entregues:**
- `models.py` — contratos de dados: `Detection`, `SafetyEvent`, `Zone`, `CameraHealth`
- `config.py` — configuração JSON validada por Pydantic (câmeras, zonas, regras)
- `logging_cfg.py` — logging estruturado JSON/colorido (structlog)
- `camera/capture.py` — thread por câmera, reconexão automática, fila sem bloqueio
- `detector/person_detector.py` — YOLO11 + ByteTrack, wrapper seguro (nunca lança exceção)
- `rules/engine.py` — motor de regras determinístico e testável:
  - teste de ponto dos pés dentro de polígono (Shapely)
  - confirmação temporal: N frames consecutivos antes de disparar
  - cooldown por `(track_id, zone_id)`: sem flooding
  - histerese: M frames fora da zona antes de encerrar evento
  - estado de operação: intrusão só ocorre com operação ativa
- `alarm/manager.py` — alarme sonoro + snapshot JPG + log JSONL auditável
- `utils/health.py` — heartbeat, `CAMERA_OFFLINE`, `STORAGE_FULL`, `MODEL_UNAVAILABLE`
- `app.py` — orquestrador com graceful shutdown (SIGINT/SIGTERM)
- `scripts/calibrate_zone.py` — calibração de zonas com mouse
- 30 testes unitários, 30/30 passando

**Critérios de conclusão — todos atendidos:**
- [x] 4 câmeras simultâneas com zonas independentes
- [x] Operação inativa → nenhum alarme crítico
- [x] Falhas técnicas sempre explícitas (nunca silenciadas)
- [x] Cooldown e histerese sem eventos duplicados
- [x] Reconexão automática de streams
- [x] Graceful shutdown sem perda de evidências

---

## 🔄 Fase 2 — EPI e gestão auditável

**Objetivo:** verificar conformidade de EPI por zona, persistir todos os eventos em banco auditável e expor dashboard para revisão e exportação.

**Implementado (pendente testes de campo):**

### 2.1 Detecção de EPI
- `ppe/detector.py` — detecta capacete, colete, luvas, botas e óculos com YOLO especializado
- Associação de EPI ao `track_id` correto por IoU entre bounding boxes
- **Fail-safe:** modelo indisponível → resultado inconclusivo, nunca acusa

### 2.2 Monitor de conformidade
- `ppe/monitor.py` — confirma ausência por **janela temporal** (não por frames)
- `PPE_NON_COMPLIANT` com severidade `WARNING` — sem sirene, apenas evidência
- Cooldown por `(track_id, zone_id)` — sem flooding de não-conformidades
- `PPE_COMPLIANT` fecha o ciclo quando o operador coloca o EPI

### 2.3 Persistência e dashboard
- `dashboard/store.py` — SQLite com WAL; filtros por kind/severity/câmera/zona; paginação; exportação CSV; purge por retenção configurável
- `dashboard/server.py` — HTTP puro stdlib (sem deps adicionais); SPA inline; acesso em `http://localhost:8080`

### 2.4 Testes
- 26 novos testes (PPE monitor, EventStore, config Fase 2)
- Total: 56/56 passando

### Pendências da Fase 2

| Item | Prioridade | Descrição |
|------|-----------|-----------|
| Modelo PPE de campo | Alta | Treinar ou selecionar modelo YOLO para capacete/colete no contexto real |
| Vídeos de validação | Alta | Gravar cenários com/sem EPI para medir precision/recall |
| Métricas de latência | Alta | Medir tempo intrusão → alarme com 4 streams no Jetson |
| Reconhecimento de operador | Média | Associar `track_id` a função (operador vs. terceiro) |
| Retenção de clipes | Média | Gravar clipe de 10s ao redor de cada evento (não só snapshot) |
| Autenticação no dashboard | Média | Login básico para acesso na rede local |
| Notificação externa | Baixa | Webhook ou e-mail ao acumular N violações no turno |

---

## 📋 Fase 3 — Envelope dinâmico e produto

**Objetivo:** tornar o sistema pronto para operação contínua em campo com zonas que acompanham a posição da lança.

### 3.1 Envelope dinâmico
- Integrar leitura do ângulo da lança (sensor ou encoder via CAN/Modbus)
- Calcular zona de atuação em tempo real: `f(ângulo, carga, raio)`
- Zonas estáticas permanecem como fallback quando o sensor falha
- Validar envelope contra dados reais do IM-45 com técnico de segurança

### 3.2 TensorRT / DeepStream no Jetson
- Converter modelo YOLO11 para `.engine` (TensorRT FP16)
- Avaliar GStreamer + DeepStream para pipeline multicâmera nativo
- Meta: ≥ 15 FPS por câmera com 4 streams simultâneos no Orin Nano
- Benchmark de latência: intrusão → alarme ≤ 2 s

### 3.3 Fusão cross-câmera
- Detectar mesma pessoa transitando entre campos de visão de câmeras adjacentes
- Evitar dupla contagem e duplo alarme para o mesmo evento físico
- Estratégia inicial: sobreposição de zona + tolerância temporal

### 3.4 Hardening e operação
- Watchdog externo (systemd) com restart automático e alerta de falha
- Política de retenção de evidências com rotação automática
- Atualização OTA do modelo sem reiniciar o sistema
- Log de auditoria imutável (append-only, hash encadeado)
- Documentação de instalação e manutenção em campo

### 3.5 Validação de campo
- Testes com Munck real, operador certificado e câmeras instaladas nos 4 cantos
- Cenários: operação normal, intrusão deliberada, perda de câmera, EPI faltando
- Aprovação por técnico de segurança do trabalho antes de uso operacional
- Registro de resultados com vídeo, métricas e laudo

---

## Fora do escopo (permanente)

- Reconhecimento facial ou identificação biométrica
- Controle automático ou intertravamento do Munck
- Certificação normativa substituta (NR-11, NR-12, ISO 13849)
- Dashboard como único canal de alarme (alarme sonoro é independente)
- Vídeo gerado por IA como evidência principal de desempenho

---

## Métricas de referência por fase

| Métrica | Fase 1 meta | Fase 2 meta | Fase 3 meta |
|---------|-------------|-------------|-------------|
| FPS por câmera | ≥ 10 | ≥ 10 | ≥ 15 |
| Latência intrusão → alarme | ≤ 3 s | ≤ 3 s | ≤ 2 s |
| Falso positivo / hora | < 2 | < 1 | < 0,5 |
| Falso negativo / entrada | < 5% | < 5% | < 2% |
| Disponibilidade | — | — | ≥ 99% turno |
| Tempo de reconexão | ≤ 10 s | ≤ 10 s | ≤ 5 s |
