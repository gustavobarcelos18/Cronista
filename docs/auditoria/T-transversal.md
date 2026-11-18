# Plano T: Transversal (redundância e ambiguidade entre blocos)

Problemas que se repetem em mais de um bloco. Resolvê-los primeiro (etapa 10B) evita corrigir a mesma coisa várias
vezes. Índice e ordem: [00-indice](00-indice.md).

## T1. Tempo e 60 fps num único lugar (`domain/frames.py`)

**Hoje:**
- `FPS = 60` está definido em `domain/frames.py:10`, `export/timeline.py:14` e `finishing/plan.py:32`;
- há `60` literal em `mix/stems.py:21`, `export/pacote.py:218,276`, `assembly/service.py:61`, `video/menus.py:107` e
  `video/broll.py:76`;
- `_frames()` está repetido em 3 módulos e `_t()` em 3 escritores de FCPXML;
- `expected_fps` na config é uma segunda fonte de verdade;
- a duração do arquivo em quadros é calculada com `round` em uns lugares e `int` em outros.

Origem: A2, A11, C4, C11.

**Tarefas:**
1. `domain/frames.py` exporta:
   - `FPS`;
   - `seconds_to_frame` (arredondamento único e documentado);
   - `frame_to_seconds`;
   - `duration_frames(duration_s)` (sempre piso, para nunca passar do último quadro real);
   - `fcpxml_time(frames)`.
2. Trocar todas as ocorrências acima. `expected_fps` é removido ou derivado de `FPS`, com um validador que recuse outro
   valor.
3. Checagem no CI (opcional): `grep` que falha com `\b60\b` em contexto de tempo fora de `domain/frames.py`, com uma
   lista de exceções.

**Aceite:** um teste de propriedade garante `frame_to_seconds(seconds_to_frame(t))` dentro de meio quadro, e que
`duration_frames` nunca passa de `duration_s*60`. Nenhuma outra definição de `FPS`.

## T2. FFmpeg num único lugar (`media/ffmpeg.py`)

**Hoje:**
- o wrapper `[ffmpeg, -hide_banner, -loglevel, error …]`, com o tratamento de stderr e do código de saída, foi
  reimplementado em `ingest/ffmpeg.py`, `mix/service.py`, `video/frames.py`, `video/report.py`, `thumbnails/render.py`
  e `shorts/render.py`;
- a extração de um quadro existe em 3 versões, com precisões de `-ss` diferentes;
- a seleção de encoder (`video_args`) não é usada pelo timelapse nem pelos Shorts.

Origem: A7, C13.

**Tarefas:**
1. `cronista/media/ffmpeg.py` com:
   - `run_ffmpeg(settings, args, *, log_to)`;
   - `pipe_raw(...)`;
   - `grab_frame(path, frame) -> bytes` (usando `frame_to_seconds`);
   - `video_args(settings, quality)`.
2. `ingest/ffmpeg.py` reexporta por compatibilidade. Os outros módulos migram.
3. Toda saída que vai para o cache passa por `render_to` (escrita atômica, ver C1).

**Aceite:** só `media/ffmpeg.py` monta a linha de comando base do FFmpeg. O timelapse e os Shorts usam o mesmo
`video_args` da prévia.

## T3. Pastas de sessão (`SessionPaths`)

**Hoje:**
- `"packaging"`, `"shorts"` e `"story" / str(session)` aparecem 14× na CLI e em vários pontos da API e dos serviços;
- `f"shorts-{id}.json"` aparece em 4 lugares;
- o `--out` cria caminhos que nenhum passo seguinte enxerga.

Origem: D1, D7.

**Tarefas:**
1. `cronista/paths.py` com `SessionPaths(settings, session_id)`: `story_dir`, `roteiro`, `packaging_dir`,
   `titulos`, `thumbnails`, `shorts_dir`, `shorts_manifest` e `publish_dir`.
2. CLI, API e serviços usam somente `SessionPaths`. Remover o `--out` (decisão pendente 5).
3. Quando a narrativa por série existir (B1), acrescentar `ProjectPaths` no mesmo módulo.

**Aceite:** um `grep` pelos literais de pasta fora de `paths.py` não acha nada.

## T4. Vocabulário único (`docs/glossario.md` + código)

| Conceito | Hoje | Proposta |
|---|---|---|
| Quadro | Ora quadro de 60 fps, ora janela de áudio, ora amostra; `HOP_FRAMES` vale 6 ou 12 | "Quadro" = só o quadro de vídeo a 60 fps. Áudio usa "janela" e "hop". Constantes `AUDIO_SIGNAL_HOP` e `VIDEO_SAMPLE_HOP` |
| Trilha | Dois enums `Track`; "faixa" de áudio do OBS | "Faixa" = faixa de áudio do arquivo do OBS (1/2/3). "Trilha" = trilha da timeline do Resolve. Um único enum `TimelineTrack` com a lane do FCPXML |
| Trecho × segmento | Sinônimos | "Segmento" = unidade da relevância (tem classe e nota). "Trecho" = segmento escolhido para a montagem (`EditItem`) |
| Capítulo | Capítulo do OBS × dia × unidade genérica | "Marcador" = ponto gravado pela hotkey ou capítulo do OBS. "Dia" = unidade fictícia da série. "Capítulo" = bloco narrativo de um dia na história |
| Momento | Tecla × classe × tipo | "Tecla Momento" e classe `momento`. Nas outras ocorrências, "pico" |
| Pacote | story-pack, titulo-pack, exportação, publicação, efeitos | `story-pack`/`titulo-pack` (entrada das skills), "pacote do Resolve" (saída da montagem), "pacote de publicação" (saída da embalagem) |
| Perfil | Jogo, voz, dev/prod | "Perfil de jogo" (YAML), "perfil de voz", "ambiente" (dev/prod) |
| Studio | App × Resolve Studio | "Studio" = app. "Resolve Studio" sempre por extenso |
| EDL | Formato CMX × `edit_plan` | EDL = só o formato CMX. O plano interno é "plano de montagem" |
| Decisões | `aprovado/rejeitado` (Shorts), `aceito/removido` (acabamento), `aceito/rejeitado/ajustado` (segmentos) | Um vocabulário só: `aceito`/`rejeitado`/`ajustado`/`padrao`. Migração Alembic de dados e aceite dos valores antigos na leitura |
| Comandos da CLI | `montar`/`montagem`/`export`; singular e plural misturados | Convenção `<objeto>-<verbo>` com o objeto no plural (`shorts-decidir`, `titulos-escolher`, `thumbnails-escolher`), aliases para os nomes antigos e `export` deprecado |

**Tarefas:**
1. Escrever `docs/glossario.md` com as definições acima, depois da aprovação do criador.
2. Renomear no código só o que é interno: constantes, enums, docstrings.
3. Renomear o que é público (comandos, valores gravados no banco) só com alias ou migração, nunca quebrando dados já
   salvos.

**Aceite:** o glossário é citado pelo CLAUDE.md e pelo plano mestre. Os comandos antigos continuam funcionando, com aviso
de depreciação.
