# POC v0.1 — Uma câmera, uma pessoa e uma zona

## Objetivo e limites

Demonstrar a regra central da Fase 1 sem conectar o sistema ao Munck: com a
operação ativa, uma pessoa detectada entrando na zona configurada gera
`INTRUSION_START`, alarme de demonstração e evidência; ao sair, gera
`INTRUSION_END`.

Esta é uma prova de conceito de **sinalização**. Não controla a máquina, não é
certificação de segurança e não deve ser usada como proteção operacional. A
detecção genérica pode falhar por oclusão, iluminação, chuva, movimento da
câmera e outros fatores. A detecção de EPI permanece desabilitada nesta POC;
validá-la exige um modelo adequado e um protocolo separado.

## Preparar a demonstração

1. Instale o projeto e suas dependências no ambiente Python:

   ```bash
   python -m pip install -e .
   ```

2. Grave ou obtenha vídeos de uso autorizado com uma câmera fixa e uma pessoa
   real. Para a sequência principal, use uma pessoa visível que começa fora da
   zona, entra nela, permanece alguns instantes e sai. Prepare também, se
   possível, vídeos separados de uma pessoa que permanece fora da zona e de
   uma pessoa na zona com a operação inativa. Não publique imagens sem
   autorização dos participantes.

   Use vídeo real controlado como evidência principal. O script
   `scripts/generate_test_videos.py` desenha retângulos e serve apenas para
   verificar visualmente o fluxo; não valida a capacidade do detector.

3. Calibre o polígono em `config/poc-single-camera.json` para o enquadramento
   utilizado. Os pontos são coordenadas normalizadas de 0 a 1; os valores
   incluídos são apenas um exemplo e não representam uma zona real de operação.

4. O dashboard nesta configuração escuta somente em `127.0.0.1`. Mantenha-o
   nessa interface durante a demonstração: o servidor não tem autenticação.
   Não altere o host para `0.0.0.0` nem exponha a porta 8080 à rede pública.

Para usar a webcam definida como fonte padrão, omita `--source`: o valor `"0"`
da configuração é convertido no índice inteiro da webcam pelo capturador.

## Executar os cenários

### Positivo: fora → dentro → fora, operação ativa

Com um vídeo controlado chamado `videos/poc_entrada_saida.mp4`:

```bash
python -m munck_safety.app \
  --config config/poc-single-camera.json \
  --source videos/poc_entrada_saida.mp4 \
  --operation-active
```

Confirme no dashboard ou no log que `INTRUSION_END` foi emitido **antes** de
interromper o processo; isso confirma que a pessoa saiu e que a histerese foi
observada. Se o arquivo terminar antes disso, a rodada não demonstrou o
encerramento da intrusão.

Ao chegar ao fim de um arquivo, a thread de captura registra `video_finished`
e termina, mas o loop principal do app permanece ativo. Após confirmar os
eventos esperados (ou registrar a rodada como incompleta), pressione `Ctrl+C`
para encerrar o processo.

### Negativo: pessoa fora da zona, operação ativa

Use um vídeo real em que a pessoa permaneça fora do polígono:

```bash
python -m munck_safety.app \
  --config config/poc-single-camera.json \
  --source videos/poc_fora_zona.mp4 \
  --operation-active
```

Resultado esperado: nenhum `INTRUSION_START` para essa passagem.

### Negativo: pessoa na zona, operação inativa

Execute sem `--operation-active` com uma pessoa visível na zona:

```bash
python -m munck_safety.app \
  --config config/poc-single-camera.json \
  --source videos/poc_dentro_sem_operacao.mp4
```

Resultado esperado: nenhum `INTRUSION_START`. Podem existir eventos
informativos/de saúde, que não são alarmes de intrusão.

Todos os cenários usam `artifacts/poc/` nesta configuração. Para manter as
evidências separadas, encerre o app após cada rodada e arquive essa pasta antes
da próxima. Por exemplo, após o cenário positivo:

```bash
mv artifacts/poc artifacts/poc-entrada-saida
```

Repita após cada cenário com um destino distinto, como `artifacts/poc-fora-zona`
e `artifacts/poc-sem-operacao`. A próxima execução recria `artifacts/poc/`; se
o destino já existir, escolha outro nome. Cada pasta preserva conjuntamente
snapshots, JSONL e SQLite. Não apague as evidências até confirmar que há cópia.

## Conferir e registrar evidências

- Abra `http://127.0.0.1:8080` na máquina que executa a POC e confirme os
  eventos no dashboard.
- Confira `artifacts/poc/events.jsonl` e a base `artifacts/poc/events.db`.
- No cenário positivo, procure `INTRUSION_START` e `INTRUSION_END`, além do
  snapshot JPG associado ao início da intrusão em `artifacts/poc/`.
- Registre para cada cenário: vídeo/fonte, configuração e zona usadas,
  horários, eventos esperados e observados, snapshots e qualquer falha ou
  detecção perdida.
- Faça várias passagens e teste os negativos; uma demonstração visual isolada
  não estima taxa de falsos positivos/negativos nem comprova desempenho em
  campo.

O alarme sonoro depende do dispositivo de áudio e pode degradar para um beep
de terminal. A POC não integra sirene física.

## Critérios de aceite da demonstração

- A câmera e o detector iniciam com a fonte escolhida.
- Com operação ativa, uma entrada confirmada gera `INTRUSION_START` uma vez,
  evidência e, após a saída confirmada, `INTRUSION_END`.
- A passagem inteiramente fora da zona não gera `INTRUSION_START`.
- Uma pessoa na zona com operação inativa não gera `INTRUSION_START`.
- Os eventos e snapshots podem ser conferidos no dashboard e nos arquivos
  locais.
- Falhas, perda de detecção e resultados divergentes são registrados como
  limitações/falhas da rodada, não apresentados como sucesso.

## Próximas validações

Após a POC controlada, repetir com webcam/RTSP e diferentes condições de
iluminação, oclusão e movimento de câmera. Validar quatro câmeras, hardware
Jetson, calibração física da área de risco e EPI em etapas independentes antes
de qualquer decisão de uso operacional.
