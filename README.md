# Munck Safety System

> Sistema auxiliar de sinalização para operações com guindaste hidráulico (Munck).
> **Não controla o equipamento, não substitui procedimentos normativos e não é certificação de conformidade.**

---

## ✨ O que é

Visão computacional embarcada que monitora a área de atuação do Munck em tempo real, detecta pessoas em zonas de risco, verifica conformidade de EPI e mantém trilha de auditoria completa.




**Arquitetura:** IA fornece detecções. Motor de regras (determinístico) decide respostas.

---

## 📊 Status (27/09/2026)

| Fase | Descrição | Status | Testes |
|------|-----------|--------|--------|
| **1** | Intrusão em zona | ✅ PRODUCTION | 30/56 ✓ |
| **2** | EPI + Dashboard | ✅ IMPLEMENTADA | 26/56 ✓ |
| **3** | TensorRT + Jetson | 📋 PLANEJADA | - |
| | **TOTAL** | | **56/56 ✓** |

---

## 🚀 Quick Start

### Instalação
```bash
pip install -e ".[dev]"
python -m pytest tests/ -v  # 56/56 ✓
```

### Webcam ao vivo
```bash
python -m munck_safety.app --source 0 --config config/example.json --operation-active
```

### Simulação com 4 vídeos (NOVO)
```bash
python scripts/simulate_4cameras.py \
    --videos cam01.mp4 cam02.mp4 cam03.mp4 cam04.mp4 \
    --config config/example.json
```

### Dashboard
http://localhost:8080

---

## 📚 Docs
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - Design completo
- [`docs/ROADMAP.md`](docs/ROADMAP.md) - Timeline
- [`docs/VALIDATION.md`](docs/VALIDATION.md) - Estratégia de testes

---

**GitHub:** https://github.com/IsraelSiq/munck-safety-system
