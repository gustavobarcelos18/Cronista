# Plano B: Relevância, história e narrativa

Escopo: `relevance/`, `story/`, `review/`, `domain/`, `pipeline/`, `montage.py`, `profiles.py`, `gabarito.py`,
`contracts.py`, as skills `/roteirizar`, `/humanizar` e `/titular`. Índice e ordem: [00-indice](00-indice.md).

**Diagnóstico:** o motor de relevância e o pipeline são puros, explicáveis e testados. As fragilidades estão na
narrativa:

- ela trabalha por sessão, e não por série;
- o orçamento de tempo não fecha;
- a fala do roteiro local pode invadir a fala ao vivo;
- uma regex lê "não consegui" como conclusão.

Também há três critérios diferentes de "material mantido" e dois painéis da série.

## Correções (bugs e regras)

| # | Sev. | Onde | Problema | Correção | Esf. | Etapa |
|---|---|---|---|---|---|---|
| B1 | alta | `story/service.py:46-101`, `story/arc.py:57,97-104` | `build_story(session_id)` aplica o alvo inteiro (40 min) a cada sessão. Com 3 sessões o vídeo pode chegar a 120 min, e um dia que atravessa sessões vira capítulo novo. Isso contradiz o plano §4.1 e §2. | `build_series_story(project_id)`: sessões em ordem, alvo único, dias contínuos entre sessões. `montagem`, `acabamento`, `titulos` e as skills passam a aceitar o projeto. **Decisão pendente 1.** | G | 10F |
| B2 | média | `story/arc.py:104` | O piso `MIN_CHAPTER_S` (30 s) é aplicado sem renormalizar: com 100 capítulos, a soma passa do alvo. | Aplicar o piso, redistribuir o restante proporcionalmente e limitar cada capítulo ao `product_s` real (§40: não "preencher tempo"). | P | 10A |
| B3 | alta | `story/script.py:215-233` | `max_words` é calculado sobre a soma das lacunas, mas a fala é posicionada em `gaps[0][0]`. Uma fala de 20 s cai numa lacuna de 3 s, em cima da fala ao vivo. | Usar a maior lacuna (ou uma fala por lacuna) e calcular `max_words` só por ela. | P | 10A |
| B4 | média | `story/script.py:116-128`, `story/service.py:151` | `validate_script` não confere se `start_s`/`est_s` cabem numa lacuna. Falas sem `start_s` saem sobrepostas. Segmento sem lacuna gera só aviso. | Validar o encaixe por lacuna e encadear as falas sem `start_s`. Segmento sem lacuna passa a ser **erro**. | M | 10A |
| B5 | média | `story/service.py:69`, `story/pack.py:37` | As lacunas ignoram risada, exclamação e voz que o ASR descartou. A narração pode cair sobre uma risada ao vivo. | Incluir os kinds `EMOTION` em `taken` dentro de `free_gaps`. | P | 10A |
| B6 | alta | `story/objectives.py:84-87,113-119` | `\bconsegui\b` casa dentro de "nao consegui". Com um marcador de conquista perto, uma falha é confirmada como conclusão. | Testar `FAILURE` primeiro e pular `CONCLUSION` no mesmo trecho, ou usar lookbehind negativo. | P | 10A |
| B7 | média | `story/objectives.py:232-234` | A idempotência só funciona com um candidato por objetivo. Reexecutar duplica linhas, alterna o estado e pode sobrescrever uma decisão `origin=humano`. | Deduplicar por (objetivo, estado, citação). Nunca substituir uma linha humana. | M | 10A |
| B8 | média | `story/service.py:62`, `story/objectives.py:116-118` | `known` é calculado antes do loop, e basta uma palavra em comum para ligar uma conclusão a um objetivo. O título é a frase inteira, então variações viram duplicatas. | Atualizar `known` a cada candidato e exigir ≥ 2 palavras-chave (ou Jaccard mínimo). | M | 10C |
| B11 | média | `review/panel.py:62-101` | O painel soma todos os projetos num único total e numa única situação. | Totais e situação por `project_id`. | P | 10A |
| B14 | baixa | `relevance/engine.py:196-200,235-238` | Janelas fundidas passam de `max_s`. Um `novo_dia` fundido a um `momento` anterior desloca o corte do capítulo. | Cortar janelas acima de `max_s` e nunca fundir através de `novo_dia`. | M | 10C |
| B15 | média | `story/models.py:47-49` | `segment_id = "arquivo:início_s"` muda quando a relevância é recalculada. O `roteiro.json` fica órfão sem aviso. | Id estável (hash da janela original ou `marker_id`), mais uma checagem de roteiro órfão no `story`. | M | 10F |
| B16 | média | `story/script.py:167-185` | `NullProvider` e `LocalScriptProvider` não são usados em `src/`. O fallback é implícito (`script=None`) e nada bloqueia o modelo local antes do benchmark. | Fábrica `script_provider(settings)`: `NullProvider` por padrão, e `local` só com o benchmark aprovado registrado. | P | 10C |

## Redundância e ambiguidade

| # | Onde | Problema | Correção | Etapa |
|---|---|---|---|---|
| B9 | `relevance/engine.py:63`, `relevance/service.py:100-110`, `relevance/quality.py:49,61`, `story/arc.py:16,47-50` | Três critérios de "material mantido" (`product_seconds`, `is_kept`, `quality.kept`). `RelevanceParams.keep_score` existe, mas nunca é lido. O painel e o aviso de capítulo com pouco material divergem. | Uma função única `kept_seconds(seg, params)` em `relevance`, lendo `params.keep_score`. | 10C |
| B10 | `relevance/service.py:113-133` × `review/panel.py:55`, `cli.py:708` | Dois painéis da série: o da CLI ignora as decisões do criador. | A CLI passa a usar `series_panel_full`; apagar o antigo. | 10C |
| B12 | `review/panel.py:100-101` | `situacao="faltando"` abaixo de 30 min contradiz o §40. | `abaixo_da_referencia` ou `curto_ok`. **Decisão pendente 6.** | 10C |
| B13 | `relevance/engine.py:37-48`, `profiles.py:29` | O lookback está fixo no módulo, enquanto o plano promete "ajustável no perfil" e cita 60–90 s. | Mover `LOOKBACK_S`/`TAIL_S` para `RelevanceParams`, aceitar o grupo `relevance` em `THRESHOLD_GROUPS` e atualizar o plano. **Decisão pendente 7.** | 10C |
| B17 | `contracts.py:38-69`, `api/app.py:122` × `review/reexport.py:31` | `story-pack`, `Script`, `titulo-pack` e as classes de segmento estão fora de `packages/contracts`. `classe`/`kind` são `str`, e `ExportStatusOut` duplica `ExportStatus`. | Modelo Pydantic `StoryPack` exportado, tipos `Literal` e um único modelo de status. | 10C |
| B18 | `montage.py:1-4,101` | A docstring diz "compartilhado com a exportação", mas a exportação principal usa `story/assembly`. A tolerância a arquivo não ingerido é diferente da de `load_masters`. | Corrigir a docstring (prévia e export legado) e igualar a tolerância. | 10C |
| B19 | `.claude/skills/roteirizar/SKILL.md:22` × `story/script.py:68`, `story/pack.py:76` | A skill fala em 25 palavras por fôlego e o lint usa 28. `antecipacoes` é sempre `[]`. | Uma constante só, citada nas skills. Remover ou preencher o campo vazio. | 10C |

## Testes a criar (10E)

- **B20:** "não consegui" com marcador de conquista por perto.
- **B20:** reexecução com 2 candidatos por objetivo.
- **B20:** soma de `allocate_time` ≤ alvo (propriedade).
- **B20:** fala do provedor local maior que a primeira lacuna.
- **B20:** sessão sem `novo_dia` e sem fala.
- **B20:** painel com 2 projetos.
- **B20:** janelas fundidas acima de `max_s`.

## Aceite

- Invariantes testados:
  - nenhuma fala do roteiro sobrepõe fala ao vivo ou evento de emoção;
  - a soma do orçamento por capítulo nunca passa do alvo;
  - uma decisão humana nunca é sobrescrita.
- Um único critério de "mantido", usado pelo painel, pelo arco e pela qualidade. CLI e Studio mostram os mesmos números.
