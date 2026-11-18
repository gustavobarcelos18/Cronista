# Fase 8 — Acabamento automático e identidade do canal

Plano de execução (2026-11-18; histórico §57). Fonte: plano mestre, seção 7 (Fase 8) e seções 6.3 e 6.4. Roda em `dev` (CPU)
com fixtures sintéticas; o que exige mídia real, GPU ou o Resolve é `@pytest.mark.gpu` / `@pytest.mark.media` ou conferência
manual em `prod`. Entrada: a montagem da Fase 6 (plano em quadros, trilhas V1/V3/V5/A1/A2), os segmentos com nota (Fase 4,
já com as decisões do Studio) e o arco narrativo (clima dos capítulos). Saída: efeitos nas trilhas fixas da seção 6.3 (V2, V4,
A3–A5), **sempre acima do original e reversíveis**.

## Regras que valem para toda a fase

- **Três modos por efeito** (`sugerir` só marcador · `editavel` via FCPXML/Lua · `renderizado` feito pelo app), escolhidos por
  série e controlados no Studio.
- **Orçamento de efeitos por minuto**, por efeito e somado; intensidade ligada à nota do momento; nota abaixo do mínimo = nada
  é aplicado; biblioteca sem item adequado = nada é aplicado (histórico §40).
- **Nada do Studio do Resolve** (sem Speed Warp, Magic Mask etc.): zoom, shake e LUT saem do FFmpeg ou do FCPXML nativo.
- **Determinístico:** mesma entrada → mesmo plano de acabamento (escolha de SFX/música por ordem de `id`, não aleatória).
- Número de dia nunca fixo em imagem: cartelas e contador leem os dias ajustados no Studio.

## Sub-etapas

### 8A — Brand kit, estilo por série e biblioteca pessoal (`finishing/`; puro, CPU)

- **Brand kit** em `packages/brand-kit/brand.yaml` (paleta, fontes, LUT, cartela "Dia N", contador de mortes, molduras,
  identidade sonora por `id` da biblioteca, alvo de loudness), validado por Pydantic e com JSON Schema gerado
  (`uv run python -m cronista.finishing.brand` → `brand.schema.json` e `series.schema.json`).
- **Estilo por série** (Q18) em `packages/brand-kit/series/<nome>.yaml`: sobrepõe paleta, LUT e trilhas por clima e define modo,
  orçamento por minuto e nota mínima de cada efeito (`EffectKind` × `EffectPolicy`). Padrão conservador: humor e impacto
  (`sfx_meme`, `piada_visual`, `shake`, `freeze_texto`) nascem só como `sugerir`.
- **Inventário da biblioteca pessoal** (`<library_dir>/inventario.yaml`, fora do git): id, arquivo, tipo, tags, origem,
  **licença obrigatória**, `commercial_use`, BPM (obrigatório em música) e humor. `check_library` acusa arquivo ausente, fora da
  pasta, de formato desconhecido ou sem registro; `check_brand_references` acusa id do brand kit que não existe ou sem licença
  comercial.
- `cronista brand-check [--serie NOME] [--biblioteca]`.
- Aceite: exemplo carrega; campos desconhecidos, cor inválida, id repetido, música sem BPM e licença vazia são recusados; série
  só muda o que declara; consulta à biblioteca é determinística.

### 8B — Plano de acabamento (`finishing/plan.py`; puro, CPU)

- Para cada momento da montagem (nota, tipo, clima do capítulo), decide **quais efeitos** aplicar, com modo, quadro de início e
  duração, respeitando o orçamento por efeito e o teto somado por minuto; intensidade proporcional à nota (morte boba = zoom
  leve; chefe = pacote completo). Escolhe SFX e música na biblioteca (`Library.find`), com música cortada no beat (BPM).
- Saída `acabamento.json` versionado com o hash da entrada (mesmo padrão de retomada da Fase 6E).
- Aceite: invariantes testadas (orçamento por minuto nunca estourado, nada abaixo da nota mínima, determinismo, nada aplicado
  sem item na biblioteca).

### 8C — Render dos efeitos (`finishing/render/`; FFmpeg e Remotion)

- **Zoom/punch-in** centrado na região de ação (saliência da Fase 3) com easing; **shake**; **LUT** de série (`.cube`) — em V2
  (clipe renderizado logo acima do original) quando o modo é `renderizado`; como transformação nativa do FCPXML quando `editavel`.
- **Overlays** (mudou, histórico §57 itens 18-19): o contador de mortes sai de um MOV com alfa feito com `drawtext` do FFmpeg
  (`render/overlay.py`), **sem Remotion** (licença não verificada, §45); `packages/vfx-templates/` não foi criado. Cartela de dia
  segue como título editável. Freeze-frame + texto e piada visual ficam só como sugestão; barra de progresso fica fora da fase.
- **Legendas pontuais** (Q25): **adiadas para depois da Fase 8** (precisam das palavras do Whisper por momento); o plano avisa.
- **Música:** corte no beat (já no plano) e, no modo `renderizado`, stem A4 com `sidechaincompress` contra o stem de voz
  (`render/audio.py`); no `editavel`, arquivo da biblioteca com volume fixo.
- Aceite: render de overlay com canal alfa importável no Resolve (conferência manual em `prod`); tempo de render medido.

### 8D — Exportação (`export/`)

- FCPXML com V2, V4, A3–A5 populadas conforme os modos; marcadores de `sugerir` entram no Lua; `manifesto.json` e `LEIA-ME.md`
  descrevem cada efeito e como desfazê-lo.
- Aceite: importar no Resolve gratuito sem erro, efeitos visíveis e desativáveis (conferência manual em `prod`).

### 8E — Studio

- Painel de acabamento: modo e orçamento por efeito, prévia do que será aplicado por momento, aceitar/tirar efeito (decisão do
  criador só por inserção, padrão da 7C), re-exportar pelo cache por hash.

## Ordem sugerida

8A → 8B → 8C → 8D → 8E. Cada uma em commits próprios, `ruff`, `mypy src tests` e `pytest` verdes antes do push.

## Aceite da fase

Vídeo exportado precisando só de narração gravada e ajustes finos; efeitos reversíveis no Resolve.

## Estado (2026-11-18)

**8A a 8E escritas.** Verificado com um venv descartável no PC do trabalho (Python 3.14, pydantic, SQLAlchemy, Typer, FastAPI,
pytest, ruff, mypy; `opentimelineio` e `pynput` simulados por stubs fora do repositório; Node com `tsc` e `eslint` do Studio):
`ruff check`, `ruff format --check` e `mypy src tests` limpos; `pytest`: 466 passam; `tsc --noEmit` e `eslint` do Studio limpos;
schemas e `types.ts` dos contratos regenerados. Falham só 4 testes que exigem FFmpeg ou `pynput` reais (ambiente), e os testes
`@pytest.mark.media` do render (só em `prod`).

| Parte | Código | Verificado |
|---|---|---|
| 8A brand kit, série, biblioteca (`brand.py`, `library.py`, `effects.py`, `brand-check`) | sim | sim |
| 8B plano de acabamento (`plan.py`, `service.py`, `cronista acabamento`) | sim | sim |
| 8C zoom e shake (`render/video.py`) | sim | filtros e executor com FFmpeg simulado; **FFmpeg real em `prod`** |
| 8C overlay do contador (`render/overlay.py`) e música com ducking (`render/audio.py`) | sim | idem; **alfa do MOV e ducking ouvidos em `prod`** |
| 8D FCPXML com V2, V4, A4, A5 (`export/finish_fcpxml.py`), LUT por Lua, manifesto e LEIA-ME (`finishing/apply.py`) | sim | estrutura e `check_plan_fcpxml` sim; **importação no Resolve em `prod`** |
| 8D marcadores de sugestão no Lua (`markers.py`) | sim | sim |
| 8E tabelas e migração 0011, API, reexportação, painel do Studio (`acabamento.tsx`) | sim | API e banco com pytest; Studio com `tsc` e `eslint`; **tela em `prod`** (`pnpm dev`) |

### Fora da fase (decidido, histórico §57 itens 18-19)
- **Barra de progresso** e **legenda pontual**: dependem dos dias ajustados no Studio e das palavras do Whisper por momento. O plano
  avisa quando estão ligados.
- **Freeze + texto** e **piada visual** só como sugestão (o texto é decisão do criador).
- **LUT em modo `renderizado`**: não gerado (a V1 por baixo ficaria sem cor); o render avisa e o modo padrão é `editavel`.
- Templates **Remotion**: não adotados (licença, §45).

### O que o plano decide hoje
Zoom, shake, SFX, SFX de meme, piada visual, congelar + texto, contador de mortes (com o número real da morte, mesmo que o
overlay seja cortado pelo orçamento), cartela de dia, música por clima (compassos inteiros no BPM) e LUT. Orçamento: espaçamento
mínimo de `60/max_per_minute` s por efeito + teto somado por minuto (só para o que é aplicado); `sugerir` não entra no teto; maiores
notas ganham as vagas; rodízio de SFX/música (menos usado primeiro); sem item na biblioteca, nada é aplicado e o plano avisa.

### Conferir em `prod` (checklist antes de confiar)
1. `uv sync`; `uv run pytest` (inclui `-m media` para o render real: `uv run pytest -m media tests/test_finishing_video.py`);
   `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src tests`; no Studio `pnpm install`, `pnpm typecheck`, `pnpm lint`.
2. Render real: um clipe de zoom e um de shake (1920x1080, 60 fps, quadros exatos, primeiro e último quadro iguais ao original),
   o MOV do contador (alfa visível sobre a gameplay) e o stem A4 (a música abaixa quando você fala). Medir o tempo de render.
3. Resolve gratuito: importar o `montagem.fcpxml` com acabamento e ver se (a) as lanes 1, 3, -4 e -5 caem em V2, V4, A4 e A5;
   (b) os keyframes de zoom/shake editáveis funcionam (a unidade da posição do tremor é a parte mais incerta); (c) desativar a V2
   devolve a gravação; (d) o Lua do LUT (`SetLUT`) funciona na versão gratuita. Anotar o que falhar no plano, seção 6.5.
4. Studio: abrir o painel de acabamento, mudar o modo de um efeito, aceitar/tirar um item e re-exportar (a versão nova deve
   refletir; a anterior continua na pasta).
5. Clima por beat (`BEAT_MOOD`), limites padrão (`DEFAULT_EFFECTS`), nível da música (`MUSIC_BED_DB` = -20 dB) e parâmetros do
   tremor são palpites: ajustar vendo e ouvindo um vídeo real. Inventário real da biblioteca pessoal (`library_dir`) e
   `finishing_series` em `config/*.local.yaml`.

### Limites conhecidos (viram melhorias depois)
- Pico dos momentos: hoje é o meio do corte (`Moment.peak` existe, mas não é preenchido); o zoom já lê `foco_x`/`foco_y` do item
  (padrão: centro), falta o plano preencher a região de ação (saliência da Fase 3).
- Marcadores do criador em cortes fundidos pela montagem: só os do primeiro trecho chegam ao acabamento.
- Trilha de música mais curta que o capítulo: o resto fica sem música (o export avisa); o plano ainda não conhece a duração do arquivo.
- Tirar um item no Studio não libera a vaga do orçamento para outro (o plano não é refeito). A decisão fica presa ao item e
  ao momento: se o plano mudar muito (outro alvo de duração), as decisões antigas deixam de valer e a prévia mostra o padrão.
- O render de timelapse (Fase 6, `export/timelapse.py`) ainda escreve direto no arquivo final; os renders novos já são atômicos.
- O ducking da música usa só o stem de voz ao vivo (A2); a narração complementar ainda não gravada entra quando existir.
- `opentimelineio` não tem wheel para Python 3.14; no projeto vale o 3.12 (o código novo do FCPXML não usa OTIO, só escrita de XML).
