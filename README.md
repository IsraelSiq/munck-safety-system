# 🚀 MUNCK Safety System v0.2.0

> **Sistema de Monitoramento e Detecção de Intrusões para Operações com Grua**  
> Demonstração Executiva com 4 Câmeras | 56 Testes Passando | Pronto para Jetson Orin Nano

## 📊 Status Atual

| Componente | Status | Detalhes |
|-----------|--------|----------|
| **Fase 1: Intrusão** | ✅ PRODUCTION | Detecta pessoas em zonas com YOLO11 + ByteTrack |
| **Fase 2: EPI + Dashboard** | ✅ IMPLEMENTADA | API REST, Web UI, SQLite event store |
| **Fase 3: Jetson TensorRT** | 📋 PRONTO | Awaiting hardware |
| **Testes** | ✅ 56/56 PASSANDO | 2.28s (pytest) |
| **Demo em Nuvem** | 🚀 LIVE | Vercel + React (vídeos em looping) |

## 🎬 Demo Executiva (Nuvem)

**Assista o sistema em ação: [munck-safety-demo.vercel.app](https://munck-safety-demo.vercel.app)**

## 🏃 Quick Start (Local)

### 1️⃣ Gerar Vídeos de Teste
\\\powershell
python scripts/generate_test_videos.py --output videos --duration 30
\\\

### 2️⃣ Executar Simulação 4 Câmeras
\\\powershell
python scripts/simulate_4cameras.py \
  --videos videos/test_cam_frente_esq.mp4 videos/test_cam_frente_dir.mp4 \
           videos/test_cam_tras_esq.mp4 videos/test_cam_tras_dir.mp4 \
  --config config/example.json
\\\

### 3️⃣ Acessar Dashboard Local
\\\
http://localhost:8080
\\\

## 📈 Resultado da Simulação (27/09/2026)

✅ 75 Eventos Gerados
- OPERATION_START: 3 ✅
- SYSTEM_READY: 3 ✅
- HEARTBEAT: 44 ✅
- INTRUSION_START: 2 ✅
- INTRUSION_END: 2 ✅
- STREAM_LOST: 19 ⚠️

## 🧪 Testes

\\\powershell
python -m pytest tests/ -v
# ========================= 56 passed in 2.28s =========================
\\\

## 🚀 Deployment

### Local
\\\powershell
python -m munck_safety.app --config config/example.json
\\\

### Nuvem (Vercel)
Ver CLOUD_DEMO.md para instruções completas

---

**Desenvolvido para Operações de Grua Seguras**  
GitHub: https://github.com/IsraelSiq/munck-safety-system
