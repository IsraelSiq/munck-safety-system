# MUNCK SAFETY SYSTEM

Sistema de apoio a seguranca para operacoes com caminhao Munck. O objetivo e detectar pessoas em zonas de atuacao durante uma operacao, gerar alarmes apropriados e manter evidencias auditaveis.

Repositorio canonico: https://github.com/siqueiraisrael-wq/munck-safety-system

> Este projeto e um sistema auxiliar de sinalizacao. Ele nao controla o Munck, nao substitui procedimentos de seguranca e nao e uma certificacao de conformidade.

## Visao do produto

```text
4 cameras IP -> switch PoE -> Jetson Orin Nano
                         -> deteccao/tracking
                         -> zonas e estado da operacao
                         -> motor de regras
                         -> alarme sonoro, eventos e evidencias
```

A arquitetura separa a IA das regras de seguranca. O modelo informa deteccoes, confianca, posicao e `track_id`; o motor de regras decide se houve intrusao, se a operacao esta ativa, qual a severidade e qual resposta deve ocorrer.

## Fase 1 - Intrusao na area de atuacao

Quatro cameras devem cobrir os quatro cantos do Munck. Durante uma operacao ativa, uma pessoa entrando em qualquer zona de atuacao configurada deve gerar:

- alarme sonoro critico;
- evento com camera, zona, horario, confianca e `track_id` temporario;
- snapshot e, futuramente, clipe curto de evidencia;
- registro de reconhecimento/atendimento do alarme.

A Fase 1 inclui zonas estaticas inicialmente, confirmacao temporal, cooldown/histerese, reconexao de streams e alertas tecnicos para perda de cobertura. Falhas como `CAMERA_OFFLINE`, `STREAM_LOST`, `STORAGE_FULL` e `MODEL_UNAVAILABLE` nunca devem ser interpretadas como ausencia de pessoas.

## Fase 2 - EPI e gestao auditavel

Pessoas dentro da area e pessoas em zonas externas onde houver exigencia operacional podem ser avaliadas quanto aos EPIs obrigatorios. A ausencia de EPI gera alarme silencioso e nao conformidade auditavel, sem sirene.

A Fase 2 devera incluir requisitos de EPI por operacao/zona, confirmacao por janela temporal, dashboard, filtros, revisao manual, controle de acesso, retencao de imagens, trilha de auditoria e exportacao de relatorios. Reconhecimento facial esta fora do escopo; um `track_id` temporario e suficiente.

## POC v0.1 atual

A base inicial valida uma fonte por execucao (arquivo, webcam ou RTSP):

`video/RTSP -> pessoa -> zona poligonal -> operacao ativa -> evento -> snapshot`

- Deteccao inicial da classe `person` com YOLO.
- Zona configuravel por coordenadas normalizadas.
- Ponto inferior central da caixa como aproximacao dos pes.
- Evento `PERSON_ENTERED_OPERATION_ZONE` uma vez por entrada.
- Nenhum rele, CLP, sirene fisica ou comando do Munck nesta etapa.

## Validacao sem hardware

Antes de comprar cameras e testar no caminhao, o software deve aceitar as mesmas interfaces para:

1. videos MP4 licenciados ou gravados pela equipe;
2. webcam em ambiente controlado;
3. quatro videos reproduzidos em paralelo como cameras virtuais;
4. streams RTSP locais simulados a partir de arquivos;
5. cenarios sinteticos com overlays e trajetorias conhecidas.

Videos gerados por IA podem ajudar a exercitar interface e casos raros, mas nao devem ser a evidencia principal de desempenho. A validacao deve priorizar videos reais/licenciados e gravacoes controladas.

## YOLO-Pose e MediaPipe

A primeira implementacao deve usar detector de pessoa + tracking + ponto dos pes. YOLO-Pose sera avaliado posteriormente para keypoints, oclusao e associacao de EPI ao corpo; ele nao substitui tracking, zonas ou regras. MediaPipe pode ser usado como experimento de webcam/landmarks, mas nao e uma dependencia obrigatoria da arquitetura multicamera no Jetson.

## Execucao local

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -e .
python -m munck_safety.app --source 0 --config config/example.json --operation-active
```

Para arquivo, use `--source videos/teste_01.mp4`. Para RTSP, use a URL da camera. Eventos e snapshots sao gravados em `artifacts/`, que nao deve ser versionado.

## Documentacao

- [POC v0.1](docs/POC-v0.1.md): contrato, fluxo, criterios e limites.
- [Roadmap](docs/ROADMAP.md): fases, entregaveis e criterios de conclusao.
- [Validacao sem hardware](docs/VALIDATION.md): estrategia de videos, webcam, quatro fontes virtuais e metricas.
- [Modelagem do Munck](docs/MUNCK-MODEL.md): dados disponiveis, limites e informacoes ainda necessarias.
- [Referencias](docs/REFERENCES.md): projetos open source relacionados.

## Proximas etapas

1. Criar videos deterministas com entradas e saidas esperadas.
2. Validar a regra de intrusao com arquivo e webcam.
3. Adicionar alarm manager abstrato, health checks e metricas.
4. Reproduzir quatro fontes virtuais em paralelo.
5. Preparar validacao no Jetson Orin Nano/TensorRT.
6. Migrar para GStreamer/DeepStream quando a carga multicamera justificar.
