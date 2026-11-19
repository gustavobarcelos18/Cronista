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
| 10B | Fundação transversal (T1 a T4) | T1 a T3 feitas; T4 (glossário) aguarda aprovação |
| 10C | Consolidação | Quase toda feita; faltam B17 e C8 |
| 10D | Documentação | Não iniciada |
| 10E | Testes e CI | Não iniciada |
| 10F | Narrativa por série | Não iniciada |

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
| T4 | `docs/glossario.md` e renomes públicos (comandos com alias, valores do banco com migração) | Proposta escrita; **aguarda aprovação do criador** |

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
| B17 | `StoryPack` como modelo Pydantic exportado, tipos `Literal`, um só modelo de status | Muda os contratos gerados |
| C8 | Foco x/y do zoom a partir da saliência da Fase 3 | Só em `prod` |

**Aceite:** CLI e Studio mostram os mesmos números; a divisão do `cli.py` não muda nenhum nome de comando nem opção
(teste de fumaça com `--help` de cada comando).

## 10D. Documentação (F1 a F8)

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

- Testes que faltam: A14, B20 (7 casos), C18 (6 casos), D12 (`upgrade head`, `compare_metadata` e `downgrade base`), D15
  (6 casos) e E9.
- CI: job do Studio em Ubuntu e Windows com `pnpm --filter @cronista/studio build`; `ruff` e `mypy` também em
  `integrations/**/*.py` (E8).
- Studio: Vitest e Testing Library, com cobertura mínima de `lib/api.ts`, `Waveform` e dos estados de carga e erro da
  Revisão (E9).
- Acessibilidade (E17): teclado no waveform, `aria-label` nos `textarea`, ordem dos títulos, formulário inline no lugar
  de `prompt()`.

**Aceite:** o CI roda `eslint`, `tsc`, `next build` e `vitest` em Ubuntu e Windows; os invariantes de B (nenhuma fala
sobre fala ao vivo, soma do orçamento ≤ alvo, decisão humana nunca sobrescrita) estão testados.

## 10F. Narrativa por série (B1, B2, B15)

Hoje `build_story(session_id)` aplica o alvo de 30 a 50 min a cada sessão. O produto é um vídeo por série.

- `build_series_story(project_id)`: sessões em ordem, alvo único, dias contínuos entre sessões.
- `montagem`, `acabamento`, `titulos` e as skills passam a aceitar o projeto; `ProjectPaths` entra em `paths.py`.
- B15: `segment_id` estável (hash da janela original ou `marker_id`) e checagem de roteiro órfão.
- Esforço grande, com mudança de modelo de dados.

**Aceite:** com 3 sessões, a soma do vídeo não passa do alvo, e um dia que atravessa sessões continua o mesmo capítulo.

## Conferência em `prod`

Não dá para fazer em `dev` (sem GPU e sem Resolve):

- importar o pacote no Resolve gratuito e conferir o LUT na V1 e na V2;
- conferir marcadores no mesmo quadro (C9);
- foco x/y do zoom (C8), quando existir.

## Fechamento

Revisão com `/code-review` e PR para a `main`. Decisões novas vão para o plano mestre (seção 9) e para o histórico.
