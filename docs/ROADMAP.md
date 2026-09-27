# ROADMAP — MUNCK Safety System

> Estado: **v0.2.0 PRODUCTION READY**  
> Data: 27/09/2026  
> Próximo Release: **v0.3.0** (otimizações) → **v1.0.0** (Jetson)

## 📊 Timeline

AGORA (27/09):     v0.2.0: PRODUCTION
   └─ Demo executiva em nuvem ✅
   
PRÓXIMAS 2 SEMANAS:    v0.3.0: OTIMIZAÇÕES
   └─ Task 1: ByteTrack otimizado
   └─ Task 2: Type hints + error handling
   └─ Task 3: README.md completo
   └─ Task 4: Batch processing YOLO
   └─ Task 5: Logging estruturado
   
QUANDO JETSON CHEGAR:     v1.0.0: DEPLOYMENT
   └─ Converter YOLO11 → TensorRT
   └─ Deploy em Jetson Orin Nano
   └─ Teste 24h+ em produção

## ✅ CONCLUÍDO
- [x] Sistema funcional com 4 câmeras (v0.2.0)
- [x] 56 testes unitários passando
- [x] Simulação com vídeos MP4 em looping
- [x] Event store estruturado (events.jsonl + SQLite)
- [x] Dashboard web local (HTTP API)
- [x] Dashboard em nuvem (React + Vercel)

## 🎯 v0.3.0: OTIMIZAÇÕES (2 semanas)

### Task 1: ByteTrack Otimizado
**Objetivo:** Reduzir CPU em 30%
**Tempo:** 1-2h

### Task 2: Type Hints + Error Handling
**Objetivo:** Melhorar qualidade
**Tempo:** 2-3h

### Task 3: Batch Processing YOLO
**Objetivo:** 3x mais rápido
**Tempo:** 2h

### Task 4: Logging Estruturado
**Objetivo:** Logs com metadata
**Tempo:** 1-2h

### Task 5: Compression de Events
**Objetivo:** -60% disk space
**Tempo:** 1h

---

**Status:** Ready to Deploy  
**Próximo:** Aprovação do Chefe
