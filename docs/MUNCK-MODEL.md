# Modelagem do Munck

## Dados disponíveis — IM-45

| Parâmetro | Valor |
|-----------|-------|
| Comprimento total | 8,50 m |
| Largura | 2,60 m |
| Altura | 3,74 m |
| Carroceria | 3,85 m × 2,35 m |
| Alcance horizontal | 21,20 m ou 16,60 m (por variante) |
| Giro | 360° |
| Ângulo da lança | −90° a +75° |

## Estrutura de zonas (Fase 1 — estáticas)

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│   cam_frente_esq         cam_frente_dir             │
│   ┌────────────┐         ┌────────────┐             │
│   │ zona_FE    │         │ zona_FD    │             │
│   └────────────┘         └────────────┘             │
│                                                     │
│              ┌───────────────┐                      │
│              │   MUNCK (top) │                      │
│              └───────────────┘                      │
│                                                     │
│   ┌────────────┐         ┌────────────┐             │
│   │ zona_TE    │         │ zona_TD    │             │
│   └────────────┘         └────────────┘             │
│   cam_tras_esq           cam_tras_dir               │
└─────────────────────────────────────────────────────┘
```

Cada câmera cobre um quadrante. As coordenadas de zona são normalizadas `[0,1]`
no espaço do frame da câmera — independentes de resolução.

## Calibração de zonas

```bash
python scripts/calibrate_zone.py \
    --source 0 \
    --camera-id cam_frente_esq \
    --output config/zones_calibrated.json
```

Clique nos vértices com o mouse, Enter para salvar.

## Pendências para Fase 3

| Item | Motivo |
|------|--------|
| Variante exata do IM-45 | Confirmar alcance (21,20 m ou 16,60 m) |
| Dimensões dos estabilizadores | Definir zona física do chassi |
| Seções da lança | Calcular envelope por ângulo |
| Posição e lente das câmeras | FOV real, sobreposição, pontos cegos |
| Margem de segurança aprovada | Validar com técnico de ST antes de usar |
| Sensor de ângulo da lança | Protocolo: CAN, Modbus, RS-485? |

## Zonas planejadas para Fase 3

```
Zona física:    chassi + cabine + carroceria + estabilizadores abertos
Zona dinâmica:  f(ângulo_lança, carga, raio) → polígono calculado em runtime
Zona EPI:       área externa onde EPI é exigido (mesmo sem operação ativa)
```

**Importante:** nenhum valor de margem deve ser preenchido sem análise de risco
formal e validação no equipamento real. A tabela técnica não substitui o manual
do fabricante nem laudo de engenharia.
