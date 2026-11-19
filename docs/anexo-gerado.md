# Anexo gerado: pacotes, comandos e pastas

> **Gerado por `python -m cronista.devtools.anexo`; não edite à mão.** O teste
> `test_anexo_gerado` falha se este arquivo ficar diferente do código. Fonte: docstrings dos
> pacotes, o `app` Typer e as pastas do repositório.

## Pacotes do engine (`services/engine/src/cronista/`)

| Pacote ou módulo | O que é |
|---|---|
| `api/` | API local do engine para o Studio (Fase 7). |
| `assembly/` | Montagem automática (Fase 6): do material relevante ao plano de cortes. |
| `audio/` | Análise de áudio (Fase 2): sinais numéricos, VAD, transcrição e eventos sonoros. |
| `bench_report.py` | Relatórios dos benchmarks em Markdown (`docs/benchmarks/`), gerados dos JSONs de `data/<env>/bench/`. |
| `cli.py` | CLI do Cronista (Typer). Os comandos ficam em `cronista.commands.*`; aqui só se monta o `app`. |
| `commands/` | Comandos da CLI, um módulo por domínio; `cronista.cli` só os registra no `app`. |
| `config.py` | Configuração por ambiente: `config/<env>.yaml` (versionado) + `config/<env>.local.yaml` (fora do git). |
| `contracts.py` | Gera o JSON Schema dos contratos (decisão D2: Pydantic é a fonte; o TypeScript é gerado a partir dele). |
| `db/` | Banco SQLite (SQLAlchemy 2 + Alembic). |
| `devtools/` | Ferramentas de desenvolvimento (fixtures sintéticas). |
| `domain/` | Entidades e contratos puros (sem banco, sem E/S). |
| `export/` | Exportação para o DaVinci Resolve: timeline OTIO e FCPXML (1B, tarefa 6). |
| `finishing/` | Acabamento automático e identidade do canal (Fase 8): brand kit, estilo por série e biblioteca pessoal. |
| `gabarito.py` | Gabarito (decisão D3): CSV `inicio,fim,classe,nota` anotado à mão, validado por este módulo. |
| `gates.py` | `GpuGate` reais: OBS gravando, jogo em tela cheia e (opcional) carga da GPU. |
| `ingest/` | Ingestão: validação, remux, proxy e extração de áudio. |
| `logging_setup.py` | Logs estruturados em JSON (uma linha por evento). |
| `media/` | FFmpeg num só lugar: linha base, execução, leitura de quadros brutos. |
| `mix/` | Mixagem básica (Fase 6B): ducking, cadeia de voz, stems e loudness. |
| `montage.py` | Plano de montagem de uma sessão: marcadores → janelas + os arquivos de onde elas saem. |
| `packaging/` | Embalagem do vídeo: títulos, painel e pasta de publicação (Fase 9). |
| `paths.py` | Pastas e arquivos de uma sessão em `data/`: a convenção num único lugar. |
| `pipeline/` | Orquestrador: etapas puras, cache por hash, jobs persistidos e retomada. |
| `preview/` | Prévia MP4 de uma sessão: um trecho por marcador, concatenado (1B, tarefa 5). |
| `profiles.py` | Perfis declarativos de jogo (Fase 3C-2): só dados, nunca código. |
| `recorder/` | Gravador de marcadores (opção A do plano): hotkeys + obs-websocket → marcador do OBS + diário. |
| `relevance/` | Motor de relevância (Fase 4). |
| `review/` | Revisão do criador: decisões por segmento, painel da série, aprendizado e reexportação (Fase 7). |
| `shorts/` | Shorts (Fase 6D): só candidatos; a finalização 9:16 é da Fase 9. |
| `story/` | Narrativa e roteiro (Fases 5 e 5A). |
| `thumbnails/` | Thumbnails do vídeo da série (Fase 9B). |
| `video/` | Análise de vídeo (Fase 3): quadros do proxy, sinais visuais e estados de tela. |
| `watch.py` | Serviço do engine: observa a pasta de gravação e ingere cada gravação quando ela termina (decisão D1). |

## Comandos da CLI (`cronista --help`)

| Comando | O que faz | Observação |
|---|---|---|
| `acabamento` | Plano de acabamento: zoom, SFX, música e overlays dentro do orçamento por minuto (Fase 8B). |  |
| `analyze` | Análise da sessão: áudio (sinais, fala, eventos) e vídeo (cenas, menu, loading, idle, câmera). |  |
| `api` | Sobe a API local que o Studio consome (Fase 7). |  |
| `bench-audio` | Benchmark de desempenho dos modelos de áudio (velocidade, VRAM, RAM). Qualidade é da Fase 2C. |  |
| `bench-audio-quality` | Compara fala e eventos sonoros com o gabarito: WER, precisão, revocação, tempo e VRAM. |  |
| `bench-quality` | Compara eventos e transcrição do banco com o gabarito (WER, risada, grito, teclado, farm). |  |
| `bench-relevance` | Momentos do gabarito no topo, farm como farm e compressão (meta: 85% dos momentos no topo). |  |
| `bench-report` | Gera os relatórios Markdown dos benchmarks (tabelas automáticas; a análise à mão é preservada). |  |
| `bench-video` | Benchmark dos modelos de embedding de quadro: velocidade, VRAM e acerto no gabarito pequeno. |  |
| `bench-video-quality` | Compara menu, loading, idle e HUD oculto do banco com o gabarito (precisão, revocação, bordas). |  |
| `bench-vision` | Estado de tela por VLM, leitura de HUD (OCR e VLM) e efeito da resolução (360p, 720p e 1080p). |  |
| `brand-check` | Valida o brand kit, o estilo da série e (opcional) a biblioteca pessoal (Fase 8A). |  |
| `broll-search` | Busca B-roll da sessão por texto (precisa de `analyze` com `video_embedder` na configuração). |  |
| `export` | DEPRECADO (use `cronista montagem`): timeline simples da Fase 1, como .fcpxml e .otio. | deprecado |
| `fixtures` | Gera as fixtures sintéticas de vídeo (FFmpeg) para testar sem gravação real. |  |
| `gabarito` | Valida o gabarito anotado à mão e resume o que há em cada classe (decisão D3). |  |
| `gabarito-ui` | Gera uma página para anotar o gabarito vendo o vídeo, com sugestões da análise já preenchidas. |  |
| `ingest` | Ingere uma sessão: valida, remuxa se preciso, gera proxy e WAVs. Retoma de onde parou. |  |
| `mixar` | Stems A1/A2 nivelados (ducking, cadeia de voz) e crus A6/A7, só dos trechos usados (Fase 6B). |  |
| `montagem` | Pacote para o Resolve: FCPXML multi-trilha, stems, SRT, marcadores em Lua e manifesto (Fase 6C). |  |
| `montar` | Plano de montagem em quadros a 60 fps: cortes, timelapses, B-roll e cartelas (Fase 6A). |  |
| `pacote-publicacao` | Reúne vídeo, Shorts aprovados, thumbnail e título numa pasta, com um LEIA-ME.md (Fase 9D). |  |
| `preview` | Gera o MP4 de prévia: uma janela (20 s antes, 10 s depois) por marcador, com o áudio do mix. |  |
| `record` | Gravador de marcadores: escuta as hotkeys e registra cada toque no OBS e no diário. Ctrl+C sai. |  |
| `relevance` | Segmenta a sessão, dá nota explicável a cada trecho e grava os segmentos (Fase 4). |  |
| `report` | Relatório HTML da sessão: sinais, marcadores, eventos e fala (arquivo único, abre sem rede). |  |
| `resolve-kit` | Gera o kit de teste do Resolve gratuito (clipes, FCPXML, EDL, SRT, LUT). |  |
| `revisao` | Fila de revisão: objetivos propostos ou incertos (nunca afirmados nem descartados). |  |
| `roteiro-import` | Valida o roteiro (segmento, espaço livre, antecipação justificada, sinais de IA) e gera o SRT. |  |
| `roteiro-lint` | Aponta sinais de texto de IA (padrões do /humanizar) numa narração. |  |
| `series` | Painel da série por projeto: horas gravadas e minutos de produto por sessão, e o acumulado. |  |
| `serve` | Serviço: ingere cada gravação quando ela termina (diário com recording_stopped). Ctrl+C sai. |  |
| `short-decidir` | Aprova ou rejeita um Short (só inserção; a última decisão vale). | deprecado, alias escondido |
| `shorts` | Lista os candidatos a Shorts: até 13 s, gancho nos 3 primeiros segundos (Fase 6D). Não grava nada: |  |
| `shorts-decidir` | Aprova ou rejeita um Short (só inserção; a última decisão vale). |  |
| `shorts-render` | Renderiza os Shorts 9:16 com legenda gravada e margens seguras (Fase 9A). |  |
| `shorts-status` | Lista os Shorts da sessão com a chave, o MP4 e a decisão do criador (Fase 9D). |  |
| `status` | Mostra projetos, sessões e o estado dos jobs. |  |
| `story` | Capítulos, beats, objetivos e `story-pack.json` para o roteiro (Fases 5 e 5A). |  |
| `thumbnail-escolher` | Registra a thumbnail escolhida (só inserção; a última vale). | deprecado, alias escondido |
| `thumbnails` | Gera 2 a 3 variações de thumbnail a partir dos picos do vídeo e do modelo do brand kit (Fase 9B). |  |
| `thumbnails-escolher` | Registra a thumbnail escolhida (só inserção; a última vale). |  |
| `titulo-escolher` | Registra o título escolhido (só inserção); o texto do criador sempre vale mais que o sugerido. | deprecado, alias escondido |
| `titulos` | Gera o `titulo-pack.json` compacto para o /titular escrever sugestões de título (Fase 9C). |  |
| `titulos-escolher` | Registra o título escolhido (só inserção); o texto do criador sempre vale mais que o sugerido. |  |
| `titulos-import` | Valida as sugestões (limite de 70 caracteres, repetição, clichê) e guarda `titulos.json`. |  |

## Pastas do repositório

- `apps/`: `studio/`
- `packages/`: `brand-kit/`, `contracts/`
- `integrations/`: `cuda/`, `fifine/`, `mypy.ini`, `obs/`, `resolve/`
- `profiles/`: `exemplo.yaml`, `profile.schema.json`
- `config/`: `dev.yaml`, `prod.yaml`
- `.claude/skills/`: `humanizar/`, `roteirizar/`, `titular/`
