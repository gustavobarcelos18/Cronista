# Auditoria 2026-11-18: divisão lógica, correções e melhorias

Auditoria só de leitura sobre a `fase/9-embalagem` (commit `1d66ce2`). O repositório foi dividido em 6 blocos lógicos,
auditados em paralelo. A auditoria procurou bugs, violações das regras do produto, redundância e ambiguidade, tanto no
código quanto nos documentos. Cada bloco tem o seu plano de correção nesta pasta, no mesmo formato dos `fase-N-*.md`:
tarefas, aceite e testes.

**Status:** as 7 decisões foram tomadas pelo criador em 2026-11-18 e registradas no histórico §60 e no plano mestre §9.
As marcas de "substituída" nas seções temáticas do plano mestre ficam para a etapa 10D.

**Andamento da 10A (2026-11-18):** concluída, com teste de regressão em cada item, exceto B11 (muda o contrato do painel; vai
junto com B10/B12 na 10C). O C10 só registra o erro no log; expor o motivo na API fica para depois. O A6 não passa o schema ao
adaptador do VLM (só rejeita texto livre). O D4 muda a chave de decisão dos Shorts para `<arquivo>-<início>-<fim>`: decisões
antigas ficam sem efeito (é a intenção). Próxima: 10B.

**Andamento da 10B (2026-11-18):** feitos T1 (`domain/frames` com `duration_frames` e `fcpxml_time`; `expected_fps` validado),
T2 (`media/ffmpeg.py`: `ffmpeg_cmd`, `run_ffmpeg`, `pipe_raw`, `grab_frame`, `video_args(quality)`) e T3 (`paths.py`:
`SessionPaths`). T4: `docs/glossario.md` escrito como **proposta, aguardando aprovação**; os renomes públicos dependem dela.

**Andamento da 10C (2026-11-18):** feitos B8, B9, B10, B11, B12, B13, B14, B16, B18, B19, C8 (só o pico), C12, C13 (já
vinha da 10B), C14, C15, D7, D9, D10, D11, D13 (só o engine único e a docstring), E13, E14 e E15. Detalhes:

- **Material mantido (B9):** `is_kept`/`kept_seconds` em `relevance/engine.py`, com `keep_score` lido do parâmetro. Vale
  nota ≥ `keep_score`, farm, dia ou trecho com marcador. Painel, arco e qualidade usam a mesma regra.
- **Painel (B10, B11, B12):** por projeto (`projetos[]` no contrato), e a CLI `series` usa `series_panel_full`. Abaixo de
  30 min a situação é `curto_ok` (arco com setup, meio e clímax) ou `abaixo_da_referencia`.
- **Lookback (B13):** campos `lookback_<tipo>` e `tail_s` em `RelevanceParams`; o perfil ajusta no grupo `relevance`.
- **Janelas de marcador (B14):** a fusão não passa de `max_s` e o `novo_dia` mantém o início do próprio trecho.
- **Trilha única (C15):** `domain/tracks.Track`, com a `lane` do FCPXML. **FCPXML (C12):** `export/fcpxml_base.py`.
- **CLI (D9, D10):** `titulos-escolher`, `thumbnails-escolher` e `shorts-decidir` são os nomes novos; os antigos ficam
  como alias escondido e deprecado. `export` é deprecado. `--decisao` é obrigatória e `--variacoes` vai de 2 a 3.
- **Pendentes da 10C:** D8 (dividir `cli.py`; os testes fazem monkeypatch em `cronista.cli`, então a divisão pede ajuste
  deles), D13 (um `APIRouter` por domínio), B17 (`StoryPack` como modelo Pydantic e `ExportStatusOut` único), C8 (foco
  x/y do zoom: precisa da saliência da Fase 3, só `prod`) e os renomes públicos que dependem da aprovação do glossário
  (T4). Os comandos `montar` e `montagem` ficam como estão até lá.

**Andamento da 10E (2026-11-19):** feitos E8 (CI do Studio em Ubuntu e Windows com `vitest` e `next build`; `ruff` e
`mypy` não estrito em `integrations/`, com `integrations/mypy.ini`), E9 (Vitest + Testing Library: `lib/api.ts`,
`Waveform`, que saiu de `revisao.tsx` para `waveform.tsx`, e os estados de erro da Revisão), D12 (`compare_metadata == []`
e `downgrade base`), A14 (caixas MP4 sintéticas, `probe_chapters`/`probe_media` com JSON inválido, 2 faixas de áudio, WAV
vazio) e B20 (sessão sem `novo_dia` nem fala, painel com 2 projetos). A14, B20, C18 e D15 já tinham boa parte coberta
pelos testes de regressão da 10A/10C. **Ainda não rodado:** `next build` e o CI no GitHub (só `tsc`, `eslint` e `vitest`
passaram aqui). Próxima: 10F (narrativa por série).

## Divisão lógica do projeto

| Bloco | Escopo | Tamanho aprox. | Plano |
|---|---|---|---|
| A. Captura, ingestão e análise | `ingest/`, `audio/`, `video/`, `recorder/`, `watch.py`, `gates.py`, `config.py` | ~7,5 mil linhas | [A](A-captura-e-analise.md) |
| B. Relevância, história e narrativa | `relevance/`, `story/`, `review/`, `domain/`, `pipeline/`, `montage.py`, `profiles.py`, skills | ~3,5 mil | [B](B-relevancia-e-narrativa.md) |
| C. Montagem, exportação e acabamento | `assembly/`, `export/`, `finishing/`, `mix/`, `preview/`, `integrations/` | ~4,5 mil | [C](C-montagem-e-acabamento.md) |
| D. Embalagem e orquestração | `packaging/`, `thumbnails/`, `shorts/`, `api/`, `db/`, `cli.py` | ~5 mil | [D](D-embalagem-e-orquestracao.md) |
| E. Studio, contratos e infraestrutura | `apps/studio`, `packages/*`, `contracts.py`, CI, `config/`, README | ~5 mil | [E](E-studio-contratos-infra.md) |
| F. Documentação | plano mestre, histórico, fases, CLAUDE.md, skills | ~3,8 mil linhas de doc | [F](F-documentacao.md) |
| T. Transversal (redundância e ambiguidade) | o que atravessa vários blocos: tempo/60 fps, FFmpeg, caminhos, vocabulário | — | [T](T-transversal.md) |

O fluxo de dados segue a ordem A → B → C → D, e E é a superfície de tudo. O bloco T é o alicerce das refatorações: ele
cria os pontos únicos (`domain/frames`, `media/ffmpeg`, `SessionPaths`, glossário) que os planos A–D passam a usar.

## Panorama

- **Regras inegociáveis.** Nenhuma violação grave. Não há `if jogo ==`, caminho fixo, recurso do Resolve Studio nem
  serviço pago, e o mix nunca é analisado. As exceções são pequenas:
  - o detector de grito reprovado continua ligado (A1);
  - o roteiro local pode invadir a fala ao vivo (B3, B4, B5);
  - o LUT editável depende de um `SetLUT` que o spike mostrou falhar (C6).
- **Bugs reais**, concentrados em quatro pontos:
  - **identidade de artefatos:** Shorts escolhidos por `mtime`, manifesto sobrescrito, decisão presa a uma chave
    incompleta, `segment_id` instável;
  - **cache sem escrita atômica** (timelapse);
  - **perda silenciosa de informação:** falas de trechos fundidos, erros do OBS, brand kit inválido, `fetch` no Studio;
  - **regex** "não consegui" lido como conclusão.
- **Divergência de produto.** A narrativa e a montagem trabalham **por sessão**, mas o produto é **um vídeo por série**
  (plano §4.1). Nenhum documento registra essa lacuna (B1, F2). É o maior item, e é uma decisão do criador.
- **Redundância.** A conversão de tempo a 60 fps aparece em cerca de 8 lugares, há 6 cópias do wrapper de FFmpeg, 2
  escritores de FCPXML, 3 critérios de "material mantido", 2 painéis da série, a convenção de pastas espalhada em 14
  pontos e a URL do engine copiada em 9 componentes.
- **Ambiguidade.** Termos sobrecarregados: dia/capítulo, momento, trecho/segmento, pacote, perfil, Studio (app) e Resolve
  Studio, EDL e `edit_plan`, `Track`, `HOP_FRAMES`, "quadro". Também há comandos quase homônimos (`montar`, `montagem`,
  `export`) e três vocabulários de decisão diferentes.
- **Documentação.** O plano mestre tem contradições sem a marca de "substituída" (lookback, FCPXML via OTIO, Remotion,
  automação de efeitos, `MIC_RAW`, Pillow). O status das fases está desatualizado em 5 lugares. O README parou na
  "Fase 0". O CLAUDE.md dá a direção dos contratos invertida.

## Ordem de execução sugerida

Uma branch `fase/10-correcoes`, aberta depois do merge da Fase 9, com sub-etapas na mesma lógica das outras fases.

| Etapa | O quê | Por quê nessa ordem |
|---|---|---|
| **10A** | Bugs de severidade alta e de regra, com teste que reproduz cada um: A1, A3, A5, B3, B4, B5, B6, C1, C2, C5, C6\*, C7, D1, D2, D3, E1, E2, E3 | Pequenos (P), isolados e com risco real para o vídeo final |
| **10B** | Fundação transversal T1–T4 (`domain/frames`, `media/ffmpeg`, `SessionPaths`, decisões de vocabulário) | Destrava a remoção de redundância sem espalhar mudanças duas vezes |
| **10C** | Consolidação: B9, B10, B11, B16, B17, C11–C15, D7, D8, D13, E6, E14 | Usa a fundação da 10B |
| **10D** | Documentação F1–F8 (glossário, status único, marcas de substituída, árvore 5.5, CLAUDE.md, README) | Depois do código, para registrar o estado final |
| **10E** | Testes faltantes e CI (A14, B20, C18, D12, D15, E8, E9) | Fecha as lacunas que deixaram os bugs passarem |
| **10F** | Narrativa por série (B1, B2, B15), **somente se aprovada** | Esforço G, com mudança de modelo de dados |

\* depende de decisão pendente.

## Decisões (tomadas em 2026-11-18, histórico §60)

**Resultado:** o criador escolheu a recomendação em todas as 7: série na 10F com a lacuna registrada já; LUT em
`sugerir`; detector de grito atrás de flag desligada; `export` deprecado; `--out` removido; estados `curto_ok` e
`abaixo_da_referencia`; lookback de 25/20/30 s ajustável por perfil. O texto abaixo é o registro original das perguntas.

1. **Narrativa por série (B1).** Implementar agora `build_series_story(project_id)`, com alvo único e dias atravessando
   sessões, ou registrar formalmente que ela é "por sessão até a Fase X"? Recomendação: registrar a lacuna agora (10D) e
   implementar em 10F, porque a primeira série real com várias sessões vai esbarrar nisso.
2. **LUT no gratuito (C6).** Mudar o padrão de `editavel` para `sugerir` até uma nova conferência em `prod`?
   Recomendação: sim.
3. **Detector de grito (A1).** Desligar por padrão atrás de uma flag, ou manter ligado e corrigir a docstring?
   Recomendação: flag desligada, já que foi reprovado (0/8) e não tem corte aprovado (§46).
4. **`cronista export` da Fase 1 (C12, D9).** Deprecar em favor de `montagem`, ou fazê-lo delegar a `montagem`?
   Recomendação: deprecar e marcar como substituído.
5. **`--out` dos comandos de embalagem (D1).** Remover, ou criar um resolvedor de pastas que todos os passos usem?
   Recomendação: remover. Ninguém usa e ele gera material órfão.
6. **Situação "faltando" abaixo de 30 min (B12).** Trocar por `abaixo_da_referencia`, ou criar o estado `curto_ok` (§40)?
7. **Lookback (B13, F3).** Aceitar os 20–30 s por tipo do código como valor vigente (marcando os 60–90 s como
   substituídos) e expor o valor no perfil?

## Limites desta auditoria

- Feita em `dev`, sem GPU e sem mídia real. Achados marcados "de memória, a verificar" (ex.: `AddMarker` no mesmo
  quadro, C9) precisam de conferência em `prod`.
- Os achados vieram de leitura do código. Os de alta severidade foram conferidos por amostragem, mas nenhum teste foi
  executado. Cada tarefa de bug começa por um teste que reproduz o problema; se o teste não falhar, o item é descartado.
