# POC v0.1 - Uma fonte, pessoa e zona

## Objetivo

Provar a regra central da Fase 1 sem depender do Munck ou de quatro cameras fisicas:

> Se a operacao esta ativa e uma pessoa entra em uma zona de atuacao configurada, o sistema gera uma condicao de alarme e uma evidencia auditavel.

A POC e apenas de sinalizacao; nao assume controle da maquina.

## Fluxo

1. Abrir uma fonte de video: arquivo, webcam ou RTSP.
2. Executar deteccao da classe `person`.
3. Acompanhar pessoas com um `track_id` temporario quando o tracker estiver habilitado.
4. Usar o ponto inferior central da caixa como aproximacao dos pes.
5. Testar o ponto contra o poligono configurado.
6. Confirmar a entrada por uma janela temporal e respeitar cooldown/histerese.
7. Quando houver entrada durante operacao ativa, emitir `PERSON_ENTERED_OPERATION_ZONE`.
8. Salvar snapshot e JSON do evento.

O alarme sonoro deve ser representado inicialmente por um `AlarmSink` de console ou simulador. A integracao com sirene fisica fica fora da POC.

## Configuracao

As coordenadas do poligono sao normalizadas entre 0 e 1: `[x, y]`. Isso permite reutilizar a configuracao quando a resolucao do stream mudar.

A zona da POC e estatica e deve ser calibrada manualmente na imagem. Zonas dependentes da posicao da lanca, calibracao 3D ou correlacao entre cameras ficam fora deste marco.

A operacao deve ser um estado explicito. `--operation-active` habilita a regra critica; sem esse estado, uma pessoa na zona nao dispara intrusao sonora.

## Criterios de aceite

- O processo inicia com arquivo, webcam ou RTSP.
- Uma pessoa fora da zona nao gera intrusao.
- Uma pessoa que entra na zona durante operacao ativa gera um evento por entrada, nao um evento por frame.
- Uma pessoa na zona durante operacao inativa nao gera alarme critico.
- Perda ou encerramento da fonte termina com falha clara, sem simular sucesso.
- O comportamento e repetivel em videos deterministas e webcam.

## Validacao sem hardware

Executar com videos proprios/licenciados, webcam, quatro arquivos como fontes virtuais e RTSP local simulado. Videos gerados por IA podem ajudar em testes visuais, mas nao devem ser a evidencia principal de desempenho.

## YOLO-Pose e MediaPipe

A baseline e detector de pessoa + tracking. YOLO-Pose deve ser comparado quando houver necessidade de keypoints, oclusao ou associacao de EPI. MediaPipe pode ser usado em experimento de webcam, mas nao e requisito multicamera no Jetson.

## Riscos

A POC nao e certificacao de seguranca. O modelo generico pode falhar em oclusao, chuva, noite, vibracao e EPIs. A imagem do IM-45 permite modelagem conceitual, mas nao define sozinha estabilizadores, cameras, margem ou zona final.
