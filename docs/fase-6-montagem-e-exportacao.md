# Fase 6 — Montagem e exportação

Plano de execução (2026-11-17; histórico §53). Fonte: plano mestre, seção 7 (Fase 6) e seções 6.3, 6.4 e 6.5. Roda em
`dev` (CPU) com fixtures sintéticas; o que exige mídia real ou o Resolve é `@pytest.mark.media` / conferência manual em `prod`.
Entrada: segmentos classificados (Fase 4), arco, story-pack e `roteiro.json` validado (Fase 5), B-roll (Fase 3B),
WAVs e masters da ingestão. Caminho de mão única: o que o Resolve aceita é o que o app gera.

## Premissas já medidas no spike (plano 6.5, histórico §39)

- FCPXML 1.9 escrito à mão importa (V1, A1, A2, título editável "Texto - Dia 1", velocidade, zoom, transição, overlay alfa).
  Um recurso recusado derruba o arquivo inteiro: **cada recurso é validado isoladamente antes de entrar no export**.
- **Marcadores só entram por script**: Lua de uma linha colado no Console do Resolve (sem `io`/`require`). O app gera esse
  Lua; limite de tamanho do que cabe colado a medir.
- SRT: gerar com uma fala vazia em 0 s (evita o deslocamento de 1 s).
- HEVC é recusado; sem impacto (OBS grava H.264).

## Sub-etapas

### 6A — Plano de montagem (`montage/` evolui; puro, CPU)

- **EDL de decisões** (`edit_plan`): lista ordenada de itens `{fonte, in, out, trilha, modo, razão}`, tudo em **quadros
  inteiros a 60 fps**. Modos: `ao_vivo` (gameplay + fala), `montagem` (marcos do esforço), `timelapse` (N×), `broll`.
- **Seleção por orçamento:** o tempo-alvo por capítulo (arco, Fase 5) escolhe os segmentos de maior nota até caber; o
  vídeo mais curto com arco completo continua válido (histórico §40).
- **Folga e limites de fala:** 1–2 s antes/depois; nunca corta no meio de palavra (timestamps do Whisper); remove silêncio
  morto da fala do criador; cortes J/L pelos limites da fala.
- **Montagem inteligente como padrão** (início/objetivo, marcos, descoberta, consequência); trecho repetitivo e sem valor
  narrativo vira `timelapse` (4×–50×) por trecho.
- **Timelapse pré-renderizado** com FFmpeg (NVENC em `prod`, libx264 em `dev`), sem áudio do jogo, sem recurso do Studio.
- **B-roll em V3** a partir dos candidatos da 3B; **cartelas** de capítulo (V5) com o número do dia só como sugestão.
- Aceite: determinístico (mesma entrada → mesmo plano); invariantes testadas (sem sobreposição em V1, quadros inteiros,
  total ≈ orçamento, nenhum corte dentro de palavra).

### 6B — Mixagem básica (`mix/`)

- **Decisão proposta (histórico §53, item 3):** os stems A1/A2 cobrem **só os trechos usados** (WAV por item da EDL,
  concatenado), não a sessão inteira: ~10× menos disco e a conferência no Resolve é a mesma. Ficam no HD em `exports`.
- **Cadeia de voz** (A2): parte da faixa 3 (já com RNNoise do OBS); `arnndn`/`afftdn` do FFmpeg, DeepFilterNet se instalar;
  escolhida ouvindo, não por benchmark.
- **Ducking** do jogo sob a voz ao vivo e sob os trechos de narração previstos no `roteiro.json` (sidechain calculado no
  app a partir dos intervalos, sem depender de plugin); stems nivelados entre si com folga.
- **Loudness:** medir (BS.1770) e reportar; o alvo de −14 LUFS é conferido só na mixagem final (Resolve ou `cronista render`).
- A6/A7 recebem os stems crus **desativados** (desfazer a mixagem = trocar A1/A2 por A6/A7).
- Aceite: medição de LUFS/pico dos stems em teste sintético; ducking reduz o jogo no intervalo e volta depois (rampas).

### 6C — Exportação (`export/`)

- **FCPXML 1.9 multi-trilha** com o layout fixo da seção 6.3: V1 gameplay/timelapse, V2 e V4 vazias, V3 B-roll, V5 cartelas
  (título editável), A1/A2 stems, A3–A5 vazias, A6/A7 crus desativados. ⚠️ Se o Resolve não criar trilhas vazias, o Lua cria.
- **Relink** para os masters do HD (caminho relativo ao `exports`, configuração em `config/*.local.yaml`).
- **Marcadores coloridos** por tipo (+ nota: fala sugerida, sugestão de edição) gerados como **Lua de uma linha** para o
  Console; também gravados em `marcadores.json`.
- **SRT do roteiro remapeado para tempo de timeline** (resolve a pendência da Fase 5) com fala vazia em 0 s.
- **Pacote de exportação:** `exports/<série>/<versão>/` com `.fcpxml`, `.srt`, `marcadores.lua`, stems, timelapses, `LEIA-ME.md`
  de importação passo a passo e `manifesto.json` (hashes, versão do plano, o que cada trilha contém). Reexportar não
  apaga versão anterior.
- **Validação antes de entregar:** `check_fcpxml` estendido (ids, duração = soma, quadros inteiros, assets existentes) e
  relatório de avisos legível.
- Aceite: importar no Resolve gratuito sem erro, mídia linkada, marcadores visíveis (conferência manual em `prod`).

### 6D — Candidatos a Shorts (`shorts/`)

- Até 13 s, gancho nos 3 primeiros segundos, a partir dos momentos de maior nota; só lista com janelas e razão
  (finalização 9:16 fica na Fase 9). Aceite: lista determinística, nenhum candidato > 13 s.

### 6E — CLI e integração

- `cronista montar <série>` (6A), `cronista mixar` (6B), `cronista export` evoluído (6C), `cronista shorts` (6D); `cronista
  montagem` encadeia tudo e roda retomável pelo cache por hash (padrão do pipeline).
- Respeita a pausa quando o OBS grava ou há jogo em tela cheia (render e timelapse usam a GPU).

## Pré-requisitos do criador (spike que falta, bloco D do roteiro)

Antes de fechar 6C em `prod`: relink (A5), FCPXML do próprio app com trilhas (A16), cartela editável trocando o número,
qual faixa do MP4 cai em A1/A2 **de ouvido**, tamanho máximo do Lua colado no Console, desempenho da timeline, tempo de
render de 10 min (CPU × intermediário + NVENC) e se a página Entrega exporta ProRes. A 6A, 6B e 6D não dependem disso.

## Ordem sugerida

6A → 6B → 6C → 6D → 6E. Cada uma em commits próprios, `ruff`, `mypy src tests` e `pytest` verdes antes do push.

## Aceite da fase

Importar no DaVinci Resolve gratuito sem erro, com mídia linkada e marcadores visíveis; vídeo com duração dentro do orçamento
do capítulo; stems nivelados; SRT alinhado.
