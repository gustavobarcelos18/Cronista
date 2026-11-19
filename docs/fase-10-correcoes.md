# Fase 10: correções da auditoria

Corrige bugs, redundância e ambiguidade encontrados na auditoria de 2026-11-18, antes de usar o app com uma série
real. Os achados e os planos por bloco estão em [auditoria/](auditoria/00-indice.md); as decisões do criador, no
[histórico §60](01-historico-de-decisoes.md) e na seção 9 do [plano mestre](00-plano-mestre.md).

Branch: `fase/10-correcoes`. Regra de todas as etapas: cada item de bug começa por um teste que o reproduz; se o teste
não falhar, o item é descartado.

## Status

| Etapa | O quê | Status |
|---|---|---|
| 10A | Bugs de severidade alta e de regra | Concluída (B11 foi para a 10C) |
| 10B | Fundação transversal (T1 a T4) | Feita (T4: glossário aprovado) |
| 10C | Consolidação | Quase toda feita; falta o C8 (só em `prod`); A13 feito. A9 feito; A10 adiado (H §63) |
| 10D | Documentação | Feita (2026-11-19) |
| 10E | Testes e CI | Feita (`next build` ok em 2026-11-19; falta o CI real no GitHub) |
| 10F | Narrativa por série | Implementada. A conferência com mídia real em `prod` está pendente |

## 10A. Bugs e regras (concluída)

Itens com teste de regressão: A1, A3 a A6, A12, A15, A16, B2 a B7, C1 a C3, C5 a C7, C9, C10, C16, D1 a D6, D13a, E1 a E5,
E7 e E16. Registros relevantes:

- O C10 só registra o erro no log; expor o motivo na API fica para depois.
- O A6 não passa o schema ao adaptador do VLM (só rejeita texto livre).
- O D4 muda a chave de decisão dos Shorts para `<arquivo>-<início>-<fim>`: decisões antigas ficam sem efeito.

## 10B. Fundação transversal

| Tarefa | Entrega | Status |
|---|---|---|
| T1 | `domain/frames`: `FPS`, conversões, `duration_frames`, `fcpxml_time`; `expected_fps` validado | Feita |
| T2 | `media/ffmpeg`: `ffmpeg_cmd`, `run_ffmpeg`, `pipe_raw`, `grab_frame`, `video_args` | Feita |
| T3 | `paths.SessionPaths`: pastas de sessão num só lugar | Feita |
| T4 | `docs/glossario.md` e renomes públicos | Glossário aprovado em 2026-11-19; comandos renomeados com alias (10C); vocabulário de decisões **não** unificado (decisão do criador) |

**Aceite:** só `media/ffmpeg.py` monta a linha base do FFmpeg; nenhuma outra definição de `FPS`; nenhum literal de pasta
de sessão fora de `paths.py`.

## 10C. Consolidação

**Feito**

- B9: critério único de "material mantido" (`is_kept`, `kept_seconds`), lendo `keep_score`.
- B10, B11, B12: painel da série por projeto; estados `curto_ok` e `abaixo_da_referencia`; a CLI usa o painel completo.
- B13, B14: lookback e `tail_s` em `RelevanceParams`, ajustáveis pelo grupo `relevance` do perfil; fusão de janelas
  limitada por `max_s` e sem atravessar `novo_dia`.
- B8, B16, B18, B19: ligação de conclusão a objetivo por fração de palavras-chave; `script_provider(settings)` com
  `NullProvider` por padrão; `plan_session` tolerante a arquivo não ingerido; limite de 28 palavras por fôlego.
- C8 (só o pico): o zoom centra no marcador do criador.
- C12, C13, C14, C15: esqueleto único de FCPXML (`export/fcpxml_base.py`); FFmpeg e encoder únicos; `Track` único com a
  lane do FCPXML (`domain/tracks.py`).
- B17: `StoryPack` (e `PackBeat`, `PackChapter`...) em `story/models.py`, validado ao montar o pacote e exportado nos
  contratos; `classe` do trecho e do pacote é `Literal` (`SegmentClass`); `ExportStatus` é um só modelo Pydantic,
  usado pelo engine e pela API (o tipo do Studio passou de `ExportStatusOut` a `ExportStatus`). `Segment.classe` do
  engine segue `str`; o `Literal` vale nas fronteiras (API e pacote).
- D8: `cli.py` só monta o `app`; os comandos ficam em `commands/` (`capture`, `narrative`, `assembly`,
  `packaging`, `devtools`), com `current_settings()` e `profile_objectives()` em `commands/common.py`. Nomes e opções
  não mudaram (comparados com a CLI anterior; `tests/test_cli_help.py`). Os testes que trocavam `cli.load_settings`
  passaram a trocar `cronista.commands.common.load_settings`.
- D13 (routers): `api/app.py` só monta o app; um `APIRouter` por domínio em `api/routes_*.py`, modelos em
  `api/schemas.py` e estado comum em `api/context.py`. Os testes de acabamento passaram a fazer monkeypatch em
  `cronista.api.routes_finishing`.
- D7, D9, D10, D11, D13 (engine único): `valid_thumbnail_choice`; nomes `<objeto>-<verbo>` com aliases deprecados e
  `export` deprecado; opções tipadas; `ShortsError`; um engine SQLAlchemy por app.
- E13, E14, E15: contratos sem títulos de campo; meta de 40 min numa constante; YAML só com o que muda por ambiente.

**Pendente**

| Item | O quê | Observação |
|---|---|---|
| C8 | Foco x/y do zoom a partir da saliência da Fase 3 | Só em `prod` |

**Aceite:** CLI e Studio mostram os mesmos números; a divisão do `cli.py` não muda nenhum nome de comando nem opção
(teste de fumaça com `--help` de cada comando).

## 10D. Documentação (F1 a F8)

**Feito (2026-11-19):** F15 (CLAUDE.md: Pydantic é a fonte dos contratos) e regra de substituição/revisão de fase; F11
(tabela de status única em plano mestre §7, com ponteiros nas fases 1 a 3, no README e no cabeçalho do plano); F1, F3, F4,
F6, F7, F8 e F9 marcados como substituídos onde ainda apareciam como vigentes; F13 (`render` marcado "não implementado",
nomes de comandos e gabarito corrigidos) e F21; F14 (árvore da 5.5 conforme o código, a antiga mantida e marcada);
README com setup; C17. Glossário aprovado e citado no CLAUDE.md, README e plano mestre (F17). **F12 feito (2026-11-19):** "Em aberto" virou tabela (EA-1 a EA-30) no plano mestre §9. **Redundância feita (2026-11-19):** duplicatas dentro da §9 do plano mestre marcadas como "DUPLICADA" com o item que vale (cartelas, benchmarks da Fase 2, microfone); trilhas e spike com fonte única declarada (seções 6.3 e 6.5); CLAUDE.md com ponteiros para o plano. **F20 feito (2026-11-19):** o §50 do histórico perdeu as decisões da 3C, que foram para o §50A (numeração mantida; nota de
leitura no cabeçalho e no §59); a §9 do plano mestre ganhou um guia cronológico, sem reordenar os blocos. **F18 feito (2026-11-19, H §64):** ⚠️ do plano mestre marcados como resolvidos ou ainda abertos. O histórico preserva a numeração original. A edição de texto de thumbnail no Studio ficou fora de escopo (D14, H §63). **F14 anexo feito (2026-11-19):** `docs/anexo-gerado.md`, gerado por
`cronista.devtools.anexo`, com teste de defasagem.

**Escopo original da 10D, para consulta histórica**

- Aprovar e publicar `docs/glossario.md`; citá-lo no CLAUDE.md e no plano mestre.
- Marcar como "substituída" as contradições do plano mestre: lookback de 60 a 90 s, FCPXML via OTIO, Remotion,
  automação de efeitos, `MIC_RAW`, Pillow, `--out` e LUT `editavel`.
- Status único das fases (hoje desatualizado em 5 lugares).
- Árvore da seção 5.5 conforme o código; README com setup e estado atual (parou na "Fase 0").
- CLAUDE.md: corrigir a direção dos contratos (Pydantic é a fonte; JSON Schema e TypeScript são gerados).
- C17 (kit de teste do Resolve superado pelo Console Lua) e D14 (texto editável da thumbnail: pendência da 9D ou fora de
  escopo).

**Aceite:** nenhuma contradição sem marca de substituída; o glossário é citado pelos documentos de entrada.

## 10E. Testes e CI

- Cobertura prevista na 10E: A14, B20 (7 casos), C18 (6 casos), D12 (`upgrade head`, `compare_metadata` e `downgrade base`), D15
  (6 casos) e E9.
- CI: job do Studio em Ubuntu e Windows com `pnpm --filter @cronista/studio build`; `ruff` e `mypy` também em
  `integrations/**/*.py` (E8).
- Studio: Vitest e Testing Library, com cobertura mínima de `lib/api.ts`, `Waveform` e dos estados de carga e erro da
  Revisão (E9).
- Acessibilidade (E17): teclado no waveform, `aria-label` nos `textarea`, ordem dos títulos, formulário inline no lugar
  de `prompt()`.
  **Feita (2026-11-19):** o waveform é um `slider` com teclado (setas ±5 s, PageUp/PageDown ±30 s, Home/End); `aria-label` nos
  `textarea`; títulos do painel lateral sem salto de nível; `AjusteForm` (`app/ajuste.tsx`) no lugar do `prompt()`.

**Aceite:** o CI roda `eslint`, `tsc`, `next build` e `vitest` em Ubuntu e Windows; os invariantes de B (nenhuma fala
sobre fala ao vivo, soma do orçamento ≤ alvo, decisão humana nunca sobrescrita) estão testados.

## 10F. Narrativa por série (B1, B2, B15)

A história por sessão continua disponível. Para o vídeo da série, `cronista story --projeto N` aplica um único alvo ao projeto inteiro. A última sessão do projeto é a âncora (histórico §62).

- `build_series_story(project_id)`: sessões em ordem, alvo único, dias contínuos entre sessões.
- `montagem` e `acabamento` aceitam `--projeto N`. Roteiro, títulos, thumbnails e pacote de publicação usam o ID da sessão âncora. Os Shorts são gerados por sessão.
- B15 mantém o identificador `arquivo:início_s`. A validação religa a fala ao segmento do mesmo arquivo que contém o início antigo e informa erro se o roteiro ficar órfão.
- A implementação reutiliza as tabelas existentes e as funções de caminhos em `paths.py`. O plano original de criar um identificador por hash e um modelo novo foi substituído pela decisão do histórico §62.

**Aceite:** com 3 sessões, a soma do vídeo não passa do alvo, e um dia que atravessa sessões continua o mesmo capítulo.

## Conferência em `prod`

Não dá para fazer em `dev` (sem GPU e sem Resolve):

- importar o pacote no Resolve gratuito e conferir o LUT na V1 e na V2;
- conferir marcadores no mesmo quadro (C9);
- foco x/y do zoom (C8), quando existir.

## Fechamento

`/code-review` feito em 2026-11-19; 4 achados corrigidos (histórico §65).

Revisão com `/code-review` e PR para a `main`. Decisões novas vão para o plano mestre (seção 9) e para o histórico.
