# Fase 9 — Embalagem e distribuição

Plano de execução (2026-11-18; histórico §58). Fonte: plano mestre, seção 7 (Fase 9) e seções 6.6 (Shorts) e 6.7 (thumbnails e
títulos). Roda em `dev` (CPU) com mocks e fixtures sintéticas; o que exige mídia real, GPU ou conferência visual é
`@pytest.mark.media` ou conferência manual em `prod`. Entrada: candidatos a Short da Fase 6D, palavras do Whisper (Fase 2), brand
kit e estilo da série (Fase 8A), a montagem e o arco narrativo (Fases 5 e 6). Saída: Shorts 9:16 prontos, thumbnails e sugestões de
título para o vídeo da série.

## Regras que valem para toda a fase

- **Sem facecam, sem IA generativa de imagem, sem voz sintética.** Shorts e thumbnails usam frames e áudio da própria gravação.
- **Nada do Studio do Resolve:** reenquadramento, legenda e loudness saem do FFmpeg; thumbnails de FFmpeg/Pillow.
- **Identidade vem do brand kit** (paleta, fontes, loudness-alvo); nada de cor ou fonte fixa no código.
- **Texto sem "cara de IA":** títulos e textos de thumbnail passam pela skill `/humanizar`; texto escrito pelo criador sempre
  ganha do sugerido.
- **Decisão do criador só por inserção** (padrão da 7C/8E) e **determinístico**: mesma entrada → mesmos arquivos (nome com hash).
- **Renders atômicos e reaproveitados** (`render_to`, nome com hash do filtro, da legenda e do encoder); esperam o `GpuGate`.
- Número de dia nunca fixo em imagem: selo "Dia N" lê os dias ajustados no Studio.

## Sub-etapas

### 9A — Shorts finalizados (`shorts/render.py`; puro + FFmpeg)

- Entrada: `ShortCandidate` (até 13 s, gancho nos 3 primeiros segundos). Saída: MP4 1080×1920, 60 fps, H.264, áudio AAC 48 kHz.
- **Reenquadramento 9:16** em dois modos: `desfoque` (padrão: gameplay inteira no centro sobre ela mesma ampliada, desfocada e
  escurecida; não perde nada da tela) e `recorte` (janela vertical em torno de `focus_x`; perde bordas e resolução, ~1,8×).
  O seguidor de saliência da seção 6.6 **não existe ainda** (não há dado de região de ação no banco): o foco é fixo e fica
  como melhoria futura, sem bloquear a fase.
- **Legenda gravada** (ASS, queimada com o filtro `ass`): palavras do Whisper em grupos de 3, cada palavra acende na cor de
  destaque do brand kit enquanto é falada, fonte do brand kit. Sem palavras na janela → Short sem legenda e aviso.
- **Margens seguras:** gameplay e legenda formam um bloco centrado entre as margens (topo 250 px, base 450 px, direita 140 px,
  esquerda 60 px; ⚠️ valores de memória da interface de YouTube Shorts/TikTok/Reels, conferir na prática e ajustar `SafeZone`).
- **Áudio:** a faixa 1 (o mix de entrega; nunca para análise) com `loudnorm` no alvo do canal (`sonic.loudness_lufs`) e corte
  suave de 0,15 s no fim (ajuda o loop e evita estalo).
- CLI: `cronista shorts-render <sessão> [--top N, padrão 5] [--serie S] [--reframe desfoque|recorte] [--focus-x X]`, que também grava o
  `shorts-<sessão>.json` com os candidatos.
- Aceite: testes das partes puras (legenda, layout, filtros, nome com hash, cancelamento sem arquivo parcial); em `prod`,
  `pytest -m media tests/test_shorts_render.py` e olhar 3 Shorts reais (legenda legível, nada sob a interface, loudness).

### 9B — Thumbnails (`thumbnails/`; puro + FFmpeg/Pillow)

- **Modelo do canal ainda a definir com o criador** (plano 6.7 e "Em aberto" 4): o app entrega o **mecanismo** e um modelo
  declarativo em YAML dentro do brand kit (`thumbnail.yaml`: tamanho 1280×720, posição e tamanho do texto, moldura, selo de dia,
  filtros de cor), para o layout ser trocado sem mexer no código.
- Candidatos a frame: picos do vídeo (maiores notas, chefes, antes/depois de construção), com nitidez e composição medidas por
  heurística simples (sem modelo); 2–3 variações por vídeo (frame, texto, posição).
- Texto de 2–4 palavras, sugerido (humanizado) e editável no Studio.
- Aceite: variações geradas de forma determinística a partir de uma montagem sintética; modelo carrega e valida (campo
  desconhecido, cor inválida e fonte ausente são recusados).
- **Como ficou (2026-11-18):** pacote `thumbnails/` com `model.py` (modelo Pydantic `extra=forbid`; cores são papéis da paleta
  ou `#RRGGBB`; 16:9 obrigatório; `thumbnail.yaml` + `thumbnail.schema.json` no brand kit, sem o arquivo vale o modelo
  padrão), `frames.py` (puro, numpy), `render.py` (FFmpeg) e `service.py` (banco e disco). Fluxo:
  `cronista thumbnails <sessão> [--texto "..."]… [--dia N] [--variacoes 1-3]` lê o `story-pack.json`, amostra 5 instantes em
  cada um dos 8 beats de maior nota (segmentos longos só em volta do meio, 60 s), mede cada frame (480×270 em cinza, via
  FFmpeg) e escolhe os melhores (um por segmento, nunca dois a menos de 20 s no mesmo arquivo). Nota do frame = 60% a nota do
  momento + 40% a qualidade (nitidez por Laplaciano, contraste, exposição que zera a nota de tela preta ou estourada, e
  composição pela posição do centro de massa das bordas em relação aos pontos de terço). Variação N = N-ésimo frame + N-ésimo
  texto + N-ésima posição (`text.positions`), cada lista volta ao começo. Saída: `data/packaging/<sessão>/thumbnails/*.jpg`
  (nome com hash do filtro, da moldura e da qualidade; reaproveitado se existe) + `thumbnails.json` (manifesto). JPEG tenta
  `-q:v` 3, 6 e 10 até caber em 2 MB (limite do YouTube); só a versão que coube fica. `cronista thumbnail-escolher <sessão>
  --variacao N` registra a escolha (tabela `thumbnail_choice`, migração 0013, só inserção; vale a última linha).
- **Texto da thumbnail:** o `/titular` também escreve `thumbnail_texts` em `titulos.json` (2 a 4 palavras, até 28 caracteres;
  vazio, repetido, fora do tamanho ou com clichê são erros; texto de IA é aviso). O `--texto` do criador ganha do sugerido e só
  esbarra no que não cabe na imagem (`text.max_words` do modelo, 4 por padrão; até 6).
- **Ainda fora (de propósito):** "antes/depois de construção" e chefes como critério de frame (não há esse dado nos beats; a
  nota do momento já o reflete); o modelo real do canal (decisão do criador); edição do texto no Studio (9D).
- ⚠️ **Contradição apontada com o plano:** o selo "Dia N" devia ler "os dias ajustados no Studio", mas o app não guarda número de
  dia em lugar nenhum (decidido na edição). O número vem de `--dia` na hora de gerar e o selo nasce desligado.

### 9C — Sugestões de título (`packaging/titles.py`)

- 3–5 títulos por vídeo a partir do arco narrativo e dos momentos de maior nota, sem clichê ("você não vai acreditar"), passando
  pela skill `/humanizar` (mesmo caminho do roteiro: `NullProvider` por padrão; Claude só via Claude Code, sem API).
- O criador escolhe e edita; só a escolha dele (por inserção) fica registrada, para o app aprender o gosto.
- Aceite: pacote de entrada compacto e determinístico; títulos acima do limite (YouTube ~70 caracteres úteis) são recusados.
- **Como ficou (2026-11-18):** `packaging/titles.py` (puro) e `packaging/service.py` (banco e disco). Fluxo, igual ao do roteiro:
  `cronista titulos <sessão>` recorta o `story-pack.json` em `titulo-pack.json` (objetivo confirmado, arco por capítulo, abertura,
  desfecho e os 6 momentos de maior nota; sem número de dia) → skill `/titular` (que chama `/humanizar`) escreve `titulos.json` →
  `cronista titulos-import <sessão> titulos.json` valida e guarda (a versão anterior vira `titulos.v<N>.json`) →
  `cronista titulo-escolher <sessão> --sugestao N [--texto "..."]` registra a escolha na tabela `title_choice` (migração 0012,
  só inserção: `sugerido`, `editado` ou `proprio`; vale a última linha).
- **Validação das sugestões:** 3 a 5 títulos; vazio, repetido, acima de 70 caracteres ou com clichê de isca de clique ("você não
  vai acreditar", "mudou tudo", "chocante", caixa alta, "!!", "o que aconteceu depois") são **erros** (nada é gravado); sinais de
  texto de IA do `lint_text` e título sem `reason` (o fato do pacote em que se apoia) são **avisos**. O título do próprio
  criador só esbarra no limite duro do YouTube (100 caracteres): o texto dele sempre ganha do sugerido.
- Sem `LocalScriptProvider` equivalente: o `NullTitleProvider` é o padrão e o título é tarefa do Claude Code (plano Pro), como o
  roteiro. A exceção de LLM local (histórico §40) não cobre títulos.

### 9D — Pacote de publicação e Studio

- Painel de embalagem no Studio: prévia dos Shorts, aprovar/rejeitar cada um (por inserção), escolher thumbnail e título.
- Pasta final com vídeo-alvo, Shorts aprovados, thumbnail e título escolhido, mais um `LEIA-ME.md` do que foi gerado.
- Aceite da fase: o vídeo da série publicado com thumbnail, título e pelo menos 3 Shorts gerados pelo app e aprovados pelo
  criador.
- **Como ficou (2026-11-18):** `packaging/publish.py` (aprovação e pasta), `packaging/panel.py` (dados do painel), endpoints na
  API e o painel `apps/studio/app/embalagem.tsx` (montado na tela de revisão, abaixo do acabamento).
  - **Aprovação dos Shorts** na tabela `short_decision` (migração 0014), só inserção: `aprovado`, `rejeitado` ou `padrao` (volta a
    pendente); vale a última linha por Short. A chave do Short é `<arquivo>-<quadro inicial>`. Aprovar exige o MP4 renderizado.
    CLI: `cronista shorts-status <sessão>` (lista chave, decisão e MP4) e `cronista short-decidir <sessão> <chave> [--decisao]`.
  - **Pasta de publicação** (`cronista pacote-publicacao <sessão> [--video arquivo] [--out pasta]`, padrão
    `data/packaging/<sessão>/publicacao/`): `titulo.txt`, `thumbnail.jpg`, `short-01.mp4`… (só os aprovados, na ordem da nota, com
    os arquivos do pacote anterior trocados), o vídeo da série se vier em `--video` (senão mantém o da vez anterior) e um
    `LEIA-ME.md` com o que há, de onde veio (origem do título, texto da thumbnail, razão de cada Short) e o **que falta** (vídeo,
    título, thumbnail, menos de 3 Shorts). O que falta nunca é erro: a CLI sai com código 2 e lista; a pasta sai assim mesmo.
  - **API:** `GET /sessions/{id}/packaging` (títulos sugeridos, textos de thumbnail, variações, Shorts e o que falta),
    `POST .../packaging/title`, `.../thumbnail`, `.../shorts/{chave}/decision` (cada um devolve o painel atualizado),
    `POST .../packaging/publish` e as mídias `GET .../thumbnails/{nome}` e `.../shorts/{chave}/video` (com `Range`; só nomes do
    manifesto são servidos). Erros de escolha viram 422, sessão inexistente 404.
  - **Studio:** título (cada sugestão é editável, contador de 70 caracteres, "Usar", campo para título próprio), thumbnails com
    prévia e "Escolher", Shorts com player e Aprovar/Rejeitar/Voltar a pendente, contagem de aprovados contra o mínimo de 3 e
    botão "Montar pasta de publicação". O vídeo do Resolve só entra pela CLI (o painel não pede caminho de arquivo).

## Ordem sugerida

9A → 9C → 9B → 9D (os Shorts já têm entrada pronta; o modelo de thumbnail depende de decisão do criador). Cada uma em commits
próprios, `ruff`, `mypy src tests` e `pytest` verdes antes do push.

## Estado (2026-11-18)

| Parte | Código | Verificado |
|---|---|---|
| 9A legenda ASS, layout, filtros, nome com hash (`shorts/render.py`) | sim | sim (pytest em `dev`) |
| 9A palavras do Whisper do banco, `render_session_shorts`, `cronista shorts-render` | sim | palavras e CLI (`--help`) sim; **render real em `prod`** |
| 9A FFmpeg real (1080×1920, 60 fps, legenda, loudnorm) | sim | só `@pytest.mark.media`; **conferir em `prod`** |
| 9B modelo, heurística de frames, filtro, variações, nome com hash, limite de 2 MB, escolha por inserção, CLI | sim | sim (pytest em `dev`, FFmpeg trocado por falso; migração 0013 incluída) |
| 9B FFmpeg real (corte 16:9, `drawtext`, moldura, `vignette`, 1280×720) | sim | só `@pytest.mark.media`; **conferir em `prod`** |
| 9B heurística de frame em jogo real (nitidez/composição) | sim | **em `prod`**: ver se as 3 variações são boas escolhas |
| 9C pacote de títulos, validação, clichês, escolha por inserção, CLI, skill `/titular` | sim | sim (pytest em `dev`, migração 0012 incluída) |
| 9C qualidade dos títulos que o Claude escreve | sim (skill) | **em `prod`**: rodar `/titular` num vídeo real e ver se o validador recusa demais ou de menos |
| 9D aprovação de Shorts, pasta de publicação, LEIA-ME, API (migração 0014 incluída) | sim | sim (pytest em `dev`) |
| 9D painel do Studio (`embalagem.tsx`) | sim | `tsc` e `eslint` sem erros; **ver no navegador em `prod`** (player, imagens, fluxo) |

### Conferir em `prod` (9D)

1. Abrir o Studio com o engine no ar, ir ao painel "Embalagem" de uma sessão com Shorts e thumbnails gerados: os vídeos tocam,
   as imagens aparecem, escolher/aprovar atualiza o painel.
2. `cronista pacote-publicacao <sessão> --video <vídeo do Resolve>` e abrir a pasta: arquivos certos e `LEIA-ME.md` legível.
3. Critério de aceite da fase: publicar o vídeo da série com a thumbnail, o título e pelo menos 3 Shorts vindos desta pasta.

### Conferir em `prod` (9B)

1. `uv run pytest -m media tests/test_thumbnails.py`.
2. `cronista thumbnails <sessão> --texto "MORRI DE NOVO"` e abrir as 3 variações: frame bom (nítido, ação visível), texto
   legível, nada cortado, fonte do brand kit (declare `fonts.files`; `text.font: body` usa a 2ª).
3. Ver em tamanho pequeno (como na lista de recomendados) e definir o layout real junto com o criador em `thumbnail.yaml`
   (posição, tamanho, moldura, selo, correção de cor). `max_line_chars` e a largura média do caractere (0,6) são estimativas:
   ajustar se a fonte do canal for mais larga ou estreita.
4. Se a heurística escolher frames ruins (HUD cheio, tela de carregamento), ajustar os pesos em `thumbnails/frames.py`.

### Conferir em `prod` (aspa no `drawtext`)

Rodar `cronista thumbnails <sessão> --texto "Caí no d'água"` e ver a aspa no JPEG. O escape novo (`'\''`) veio do
`/code-review` e não foi conferido com FFmpeg real; se falhar, o contador da Fase 8 usa o mesmo `drawtext_escape`.

### Conferir em `prod` (9A)

1. `uv run pytest -m media tests/test_shorts_render.py` (FFmpeg precisa do filtro `ass`, ou seja, libass; o build do Gyan tem).
2. `cronista shorts-render <sessão>` e assistir: legenda legível e dentro das margens, fonte do brand kit aplicada
   (declare `fonts.files` no `brand.yaml`; sem arquivo a legenda usa a fonte padrão do sistema), gameplay nítida, áudio no
   alvo (-14 LUFS), corte final sem estalo, 60 fps exatos.
3. Ver o Short no celular dentro do app de cada plataforma e ajustar `SafeZone`, `font_size` e `blur`.
4. `recorte` com `--focus-x` diferente em um jogo onde a ação não está no centro; se o recorte for comum, priorizar o
   seguidor de saliência.
