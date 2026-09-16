# Roadmap do MUNCK SAFETY SYSTEM

## Fase 0 - Requisitos e modelagem

Definir modelo exato do Munck, estabilizadores, envelope da lanca, zonas estaticas por camera, estado de operacao, severidade, cooldown, privacidade e retencao.

## Fase 1 - Intrusao na area de atuacao

Detectar pessoa dentro da zona durante operacao ativa, gerar alarme sonoro e registrar evidencia. Evolucao: arquivo/webcam, zona, regra, eventos, alarm sink, duas e quatro fontes virtuais, health checks, reconexao, camera RTSP real e Jetson.

Conclusao: quatro streams, zonas calibradas, alarme independente do dashboard, sem eventos duplicados, operacao inativa sem alarme critico, falhas tecnicas explicitas e metricas de falso positivo, falso negativo, latencia, FPS e recuperacao.

## Fase 2 - EPI e gestao

Configurar EPIs por zona/operacao, associar deteccoes ao `track_id`, confirmar ausencia por janela temporal, gerar `PPE_NON_COMPLIANT` sem sirene, adicionar evidencia, dashboard, filtros, revisao, acesso, retencao, exportacao e auditoria.

## Fase 3 - Operacao e produto

Envelope dinamico com lanca/estabilizadores, DeepStream/TensorRT, telemetria, atualizacao remota e validacao de campo.

## Fora do escopo inicial

Reconhecimento facial, controle automatico do Munck, uso do alcance maximo como zona final sem analise, video gerado por IA como validacao principal e dashboard como unico caminho do alarme.
