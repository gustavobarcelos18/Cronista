# Plano D: Embalagem e orquestração

Escopo: `packaging/`, `thumbnails/`, `shorts/`, `api/`, `db/` (com as migrações), `devtools/`, `cli.py` e
`pyproject.toml`. Índice e ordem: [00-indice](00-indice.md).

**Diagnóstico:** a camada de serviço é coesa e bem testada, e a CLI e a API já delegam a ela. O que não está seguro:

- **Identidade dos Shorts:** o clipe é escolhido pela data de modificação do arquivo, dois comandos gravam o mesmo
  manifesto e a decisão fica presa a uma chave incompleta.
- **Pastas:** a convenção está espalhada pelo código e o `--out` é enganoso.
- **Tamanho:** `cli.py` (1532 linhas) e `api/app.py` (863 linhas) são monolíticos.
- **Migrações:** consistentes hoje (0001→0014, conferidas à mão), mas sem teste automático de divergência.

## Correções (bugs)

| # | Sev. | Onde | Problema | Correção | Esf. | Etapa |
|---|---|---|---|---|---|---|
| D1 | alta | `cli.py:1110,1149,1191,1266` × `cli.py:1217-1396`, `api/app.py:451-454`, `thumbnails/service.py:89` | `--out` em 4 comandos gera material que nenhum passo seguinte enxerga. `thumbnails --out X` procura `titulos.json` em X. | Remover o `--out` (**decisão pendente 5**) e usar só `SessionPaths` ([T3](T-transversal.md)). | P | 10A |
| D2 | média | `packaging/publish.py:62-74`, `shorts/render.py:238-240,335-337` | O MP4 de cada Short é escolhido pelo `mtime` mais recente. Voltar a um estilo antigo, ou um render que falhou, faz o pacote pegar o clipe errado. | Gravar no `shorts-<s>.json` o nome do clipe de `result.clips` e ler dali. | P | 10A |
| D3 | média | `cli.py:1106-1185`, `shorts/service.py:63-67` | `shorts` (top 10) e `shorts-render` (top 5) gravam o mesmo manifesto. Rodar `shorts` depois do render deixa candidatos "sem MP4" e decisões órfãs. | `shorts` só lista ou grava em outro arquivo. O manifesto passa a ser exclusivo do `shorts-render`. | P | 10A |
| D4 | média | `packaging/publish.py:120-134` | A decisão fica presa a `<arquivo>-<quadro inicial>`. Um Short com outro fim herda o "aprovado" sem revisão. | Incluir `end_frame` (ou o hash do clipe) na chave, ou invalidar a decisão quando o clipe mudar. | M | 10A |
| D5 | baixa | `packaging/publish.py:202-209` | Refazer com `--video novo.mp4` deixa o vídeo anterior na pasta de publicação. | Apagar os `*.mp4` que não são Short antes de copiar. | P | 10A |
| D6 | média | `packaging/panel.py:82,103-129`, `thumbnails/service.py:112-117`, `publish.py:49-54` | Um manifesto corrompido faz o `GET /packaging` devolver 500, contra a docstring "nunca erro". | Levantar `ThumbnailError`/`PublishError` ao carregar e tratar como já é feito com os títulos. | P | 10A |
| D13a | baixa | `api/app.py:710-724` | `GET/PUT /sessions/{id}/script` não verifica se a sessão existe. O PUT cria `data/story/<qualquer id>/`. | `_require_session` nas duas rotas. | P | 10A |

## Redundância, ambiguidade e estrutura

| # | Onde | Problema | Correção | Etapa |
|---|---|---|---|---|
| D7 | 14× em `cli.py`, `api/app.py:451-454,712,721`, `publish.py:50,250`, `panel.py:110-118`, `shorts/service.py:65` | A convenção de pastas `data/{packaging,shorts,story}/<s>` e `shorts-<s>.json` está espalhada. A regra "escolha de thumbnail válida" está duplicada. | `SessionPaths` ([T3](T-transversal.md)) e uma função `valid_thumbnail_choice()`. | 10B/10C |
| D8 | `cli.py` inteiro | ~60 repetições de `echo erro + Exit(1)`. `load_settings_profile` + `(objetivos, regras)` aparece 5×. Imports misturados. | Pacote `cli/` com sub-apps Typer (`ingest`, `analise`, `bench`, `montagem`, `embalagem`, `api`), um helper `_fail()`/context manager de erro e `profile_objectives(settings)`. Os nomes dos comandos não mudam. | 10C |
| D9 | `cli.py:207,965,1048`; nomes de comandos | `montar`, `montagem` e `export` são quase homônimos. Singular e plural misturados (`shorts-status`/`short-decidir`, `titulos`/`titulo-escolher`). Três vocabulários de decisão. | Deprecar `export` (**decisão pendente 4**). Fixar a convenção de nomes ([T4](T-transversal.md)), com aliases para os nomes antigos. | 10C |
| D10 | `cli.py:1159,1172,1264,1359`, `api/app.py:228` | `short-decidir` aprova por padrão. `--decisao`/`--reframe` são `str` validados à mão. `--variacoes` aceita 1, e a API aceita 1–9. | `StrEnum` nas opções, `--decisao` obrigatória e limites alinhados (2–3). | 10C |
| D11 | `shorts/service.py:36,59,74,115` | Os Shorts usam `StoryError`. | Criar `ShortsError`. | 10C |
| D13 | `api/app.py:1,47,303-304`, `db/session.py:46-54` | Importa o privado `montage._load_source`. Cria um engine SQLAlchemy por requisição. A docstring diz "só leitura". O arquivo é monolítico. | Tornar `load_source` público, um engine único em `app.state` e `APIRouter` por domínio (sessões, revisão, acabamento, embalagem). | 10C |
| D14 | plano 5.5 l. 394-406, `fase-9` l. 40,47 | O layout de dados e os módulos citados divergem do código. Fala em Pillow. O texto de thumbnail "editável no Studio" não tem endpoint. | Ver [F](F-documentacao.md). Registrar o texto editável como pendência da 9D ou como fora de escopo. | 10D |

## Testes a criar (10E)

- **D12:** `test_db` roda `upgrade head` e confere `compare_metadata(...) == []`. Também roda `downgrade base`.
- **D15:** um clipe antigo reaproveitado não é escolhido (D2).
- **D15:** rodar `shorts` depois do `shorts-render` não estraga o manifesto (D3).
- **D15:** uma decisão não passa para um clipe com outro fim (D4).
- **D15:** manifesto corrompido devolve 200 com aviso (D6).
- **D15:** nenhum vídeo antigo sobra no pacote (D5).
- **D15:** PUT de roteiro em sessão inexistente devolve 404.

## Aceite

- Toda pasta de sessão é resolvida por `SessionPaths`, sem nenhum literal `"packaging"`/`"shorts"`/`"story"` fora dele.
- O pacote de publicação tem exatamente os Shorts aprovados, cada um com o clipe registrado no manifesto.
- A divisão de `cli.py` não muda nenhum nome de comando nem opção (teste de fumaça com `--help` de cada comando).
