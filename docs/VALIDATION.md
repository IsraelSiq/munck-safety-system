# Validacao sem hardware

Validar a Fase 1 antes de possuir quatro cameras, Munck ou Jetson. A fonte deve ser substituivel sem alterar o motor de regras.

## Fontes

- Videos proprios ou licenciados com entradas anotadas.
- Webcam em zona controlada.
- Quatro arquivos reproduzidos em paralelo como CAM01-CAM04.
- RTSP local simulado a partir de arquivos.
- Overlays e trajetorias programaticas para casos deterministas.

Videos gerados por IA podem exercitar interface e casos raros, mas nao devem medir desempenho principal.

## Dataset de aceitacao

Casos: pessoa fora; entrada/saida; permanencia; duas pessoas; operacao inativa; oclusao; baixa luz; perda de stream; armazenamento indisponivel; reinicio.

Cada video deve ter eventos esperados, por exemplo: entrada em t=8s e saida em t=15s devem produzir exatamente um `PERSON_ENTERED_OPERATION_ZONE`.

## Metricas

Precision/recall pessoa-na-zona, falso positivo por hora, falso negativo por entrada, latencia entrada-alarme, FPS por fonte, CPU/GPU/RAM, reconexao, disponibilidade e eventos duplicados.

## Promocao

Depois dos testes offline/virtuais: uma camera RTSP, switch PoE, Jetson Orin Nano, TensorRT/DeepStream, cameras graduais e teste de campo aprovado.
