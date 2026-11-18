# Plano A: Captura, ingestão e análise

Escopo: `ingest/`, `audio/`, `video/`, `recorder/`, `watch.py`, `gates.py`, `config.py`, `logging_setup.py`. Tudo roda em
`dev` (CPU) com fixtures sintéticas, salvo onde está marcado `prod`. Índice e ordem: [00-indice](00-indice.md).

**Diagnóstico:** o bloco é sólido e defensivo. O diário sobrevive a quedas, o remux usa `-map 0`, o WAV passa a RF64
acima de 4 GB e o mix nunca é analisado. Os riscos reais são quatro: o detector de grito reprovado continua ligado, há
duas fontes de verdade para os 60 fps, os caminhos não são normalizados no Windows e um erro do OBS é engolido.

## Correções (bugs e regras)

| # | Sev. | Onde | Problema | Correção | Esf. | Etapa |
|---|---|---|---|---|---|---|
| A1 | alta | `audio/stages.py:242-243`, `audio/scream.py:1-2` | `ScreamHeuristic` foi reprovado (0/8, §46), mas entra em toda análise com `min_score=0.0`. Os eventos `exclamacao` seguem para as fases seguintes. | Flag `audio.scream_enabled` (desligada por padrão) no `Settings`. Ajustar `test_audio_models.py:102-113`. **Decisão pendente 3.** | P | 10A |
| A2 | média | `config.py:32` × `domain/frames.py:10` | `expected_fps` pode ser mudado na config, mas toda a conta continua em `FPS = 60`. | Tirar `expected_fps` da config ou derivá-lo de `FPS`, com um validador que recuse outro valor. | P | 10B (T1) |
| A3 | média | `watch.py:80-86`, `ingest/service.py:196,229` | O mesmo arquivo chega como string diferente (sem `resolve()`, maiúsculas ou letra de unidade) e vira duas sessões. | Normalizar com `Path.resolve()` e `os.path.normcase` em `resolve_files`. Comparar `MediaFile.path` normalizado. | P | 10A |
| A4 | média | `recorder/obs.py:135-140`, `recorder/core.py:211-219` | `create_chapter` engole o `ObsError`. O `except` em `press` é código morto e o motivo real nunca chega ao criador. | Deixar o `ObsError` subir e mostrar a mensagem no feedback de `press`. | P | 10A |
| A5 | média | `ingest/service.py:215-221` | Com falha parcial, os marcadores são ingeridos com a lista incompleta. Isso gera avisos enganosos e um "dia implícito" errado. | Pular `ingest_markers` sempre que `report.failures` não estiver vazio. | P | 10A |
| A6 | média | `video/vlm.py:87-97`, `:58` | `parse_answer` aceita texto livre além do JSON. `Question.schema()` nunca chega ao modelo, o que afrouxa a regra de JSON Schema e Pydantic. | Contar o texto livre como inválido e passar o schema ao adaptador quando ele suportar saída restrita. | P/M | 10A |
| A12 | baixa | `audio/scream.py:56,93` | O tempo é calculado com `índice * frame_s`, mas o hop real é `int(frame_s*rate)`. Isso deriva ~16 s em 10 h a 44,1 kHz. | Converter com `hop / analysis_rate`, ou exigir divisão exata como em `dsp.hop_samples`. | P | 10A |
| A13 | média | `watch.py:174-177` | Uma gravação sem `recording_stopped` só vira "abandonada" pelo `mtime`, que no Windows pode estar defasado. | Consultar o `GetRecordStatus` do OBS (já existe em `gates.py`) antes de declarar abandono. | M | 10C |
| A15 | baixa | `ingest/ffmpeg.py:74,107` | `ffprobe` com código 0 e JSON truncado levanta `JSONDecodeError` fora do runner. | `try/except`: devolver `[]` em `probe_chapters` e `interrupted=True` no probe. | P | 10A |
| A16 | baixa | `recorder/hotkeys.py:337-339` | A detecção de tecla duplicada diferencia maiúsculas (`<F13>` × `<f13>`). | Comparar com `combo.lower()`. | P | 10A |
| A17 | baixa | `audio/stages.py:178,243` | O `ScreamHeuristic` (CPU) roda dentro de um estágio marcado `uses_gpu = True`. | `uses_gpu` por instância, conforme o classificador. | P | 10A |

## Redundância e ambiguidade

| # | Onde | Problema | Correção | Etapa |
|---|---|---|---|---|
| A7 | `ingest/ffmpeg.py`, `mix/service.py`, `video/frames.py`, `video/report.py`, `thumbnails/render.py` | O wrapper de FFmpeg está reimplementado ~6 vezes. A extração de um quadro existe em 3 versões, com precisões de `-ss` diferentes. | Usar `media/ffmpeg.py` ([T2](T-transversal.md)). | 10C |
| A8 | `watch.py:61,68-73`, `recorder/core.py:237-238`, `ingest/service.py:150-152`, `recorder/files.py:270-283` | A leitura do diário, `file_key` e a varredura de vídeos estão duplicadas. | `ingest/journal.py` com `journal_paths`, `journal_ended` e `list_videos`. | 10C |
| A9 | `audio/signals.py:24`, `video/frames.py:22`, `audio/dsp.py:29`, `audio/scream.py:30` | `HOP_FRAMES` vale 6 num módulo e 12 no outro. "Quadro" ora quer dizer quadro de 60 fps, ora janela de áudio. `FloatArray` e `Pause` são redefinidos em 5 módulos. | Renomear para `AUDIO_SIGNAL_HOP` e `VIDEO_SAMPLE_HOP`, levar os tipos comuns para `domain` e definir "quadro" no glossário ([T4](T-transversal.md)). | 10C |
| A10 | `video/stages.py:173`, `video/hud.py:18`, `video/vlm.py:21` | O vídeo importa a infraestrutura genérica de sinais e eventos de `cronista.audio`. | Mover para `cronista/analysis/` e reexportar em `audio` por compatibilidade. | 10C |
| A11 | `video/menus.py:107`, `video/broll.py:76` | Literais `60` no lugar de `FPS`. | `frame_to_seconds` / `FPS` ([T1](T-transversal.md)). | 10B |

## Testes a criar (10E)

- **A14:** ingestão com 2 faixas de áudio é rejeitada (fixture FFmpeg).
- **A14:** `is_unfinalized_mp4` com bytes sintéticos: arquivo vazio, caixa de 64 bits, `moof`.
- **A14:** `probe_chapters` com JSON inválido.
- **A14:** WAV vazio em `AudioSignalsStage` e em `ScreamHeuristic`.
- **A14:** aviso de "construção aberta" atravessando arquivos.
- **Regressão de cada bug acima:** caminho com maiúsculas diferentes vira uma sessão só (A3); falha parcial não ingere
  marcadores (A5); `ObsError` chega ao feedback (A4); texto livre do VLM é inválido (A6).

## Aceite

- Os testes novos falham antes da correção e passam depois. `pytest` (CPU), `ruff` e `mypy` limpos.
- Nenhum `60` literal de tempo fora de `domain/frames.py` (checagem por `grep` no CI, opcional).
- Com o detector de grito desligado, a análise não grava `exclamacao` (A1).
