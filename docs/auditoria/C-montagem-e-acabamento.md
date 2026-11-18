# Plano C: Montagem, exportação e acabamento

Escopo: `assembly/`, `export/`, `finishing/` (incluindo `render/`), `mix/`, `preview/` e `integrations/` (resolve, obs,
cuda, fifine). Índice e ordem: [00-indice](00-indice.md).

**Diagnóstico:** a arquitetura segue o plano: quadros inteiros a 60 fps, FCPXML no formato validado pelo spike, efeitos
acima do original e nada do Resolve Studio. Os riscos são três:

- **cache sem escrita atômica** no timelapse;
- **falas do roteiro perdidas** quando dois trechos se fundem;
- **promessas do acabamento que falham em silêncio:** LUT, foco do zoom e modos sem renderizador.

A dívida está nas conversões de tempo e no FCPXML, ambos duplicados.

## Correções (bugs e regras)

| # | Sev. | Onde | Problema | Correção | Esf. | Etapa |
|---|---|---|---|---|---|---|
| C1 | alta | `export/timelapse.py:29-44` | O FFmpeg grava direto no nome final. Um render interrompido deixa um MP4 parcial, que passa no teste `st_size > 0` e é reaproveitado para sempre. | Envolver com `render_to(target, ...)` (`finishing/render/atomic.py`), como já fazem o zoom e o overlay. | P | 10A |
| C2 | alta | `assembly/plan.py:246-253` + `mix/envelope.py:60` | Na fusão de trechos, o item guarda só o `segment_id` do primeiro. As falas do segundo somem do SRT e do ducking. | `EditItem.segment_ids: tuple[str, ...]` e indexação por todos os ids. `finishing/service.py:45` passa a usar o mesmo. | M | 10A |
| C3 | média | `export/montagem.py:129,165` | Sem a duração do master, o asset assume o `out_frame` do primeiro corte. Cortes posteriores geram um "problema" falso. | Usar o maior `out_frame` do arquivo em todo o plano, ou exigir a duração. | P | 10A |
| C4 | média | `assembly/service.py:61`, `export/pacote.py:218`, `export/timeline.py:30,58` | A duração em quadros é calculada com `round` em dois lugares e `int` no outro. O `round` pode passar 1 quadro do fim da mídia. | Uma única função `duration_frames()` (piso) em `domain/frames.py` ([T1](T-transversal.md)). | P | 10B |
| C5 | média | `finishing/apply.py:52-63`, `export/finish_fcpxml.py:121-149` | O LUT só é aplicado na V1. Os efeitos da V2 cobrem a V1 sem LUT e a cor "pula" durante cada efeito. | Aplicar também em `GetItemListInTrack("video", 2)`. No modo renderizado, passar `lut_filter` na cadeia do efeito. | P | 10A |
| C6 | média | `finishing/brand.py:137` × plano 6.5 l. 732 | O LUT sai `editavel` por padrão, mas no spike o `SetLUT` devolveu `false`. | Padrão `sugerir` até a conferência em `prod`, registrada no histórico. **Decisão pendente 2.** | P | 10A |
| C7 | média | `finishing/plan.py:348-351`, `export/finish_fcpxml.py:94-101` | `piada_visual`/`freeze_texto` em `editavel`/`renderizado` ocupam vaga no orçamento, mas nada os renderiza e não há aviso. | Rebaixar para `sugerir` com aviso quando o tipo está fora de `EDITABLE_KINDS`/`RENDERED`, ou recusar no `SeriesStyle`. | P | 10A |
| C8 | média | `finishing/service.py:47-60`, `finishing/render/video.py:158`, `finish_fcpxml.py:156-162` | `Moment.peak`, `foco_x` e `foco_y` nunca são preenchidos. O zoom fica sempre no meio do corte e no centro da imagem, contra a Fase 8 e o §6.4. | Levar o pico (marcador ou evento) e a saliência da Fase 3 ao `Moment`, e usar `position` nos keyframes editáveis. | M | 10C |
| C9 | baixa | `export/pacote.py:242-252`, `export/montagem.py:298` | Dois marcadores no mesmo quadro: até onde sei (**de memória, a verificar em `prod`**), o `AddMarker` recusa o segundo e ele some sem aviso. | Deslocar +1 quadro quando houver colisão antes de gerar o Lua. | P | 10A |
| C10 | média | `finishing/loader.py:35-38` | Um brand kit inválido vira `None` sem log. O Studio fica sem acabamento e sem explicação. | `log_event` com o erro de validação e o motivo exposto na API. | P | 10A |
| C16 | baixa | `export/montagem.py:334` | `if resources` testa o valor-verdade de um `Element`: dá falso quando ele não tem filhos e gera `DeprecationWarning`. | `if resources is not None`. | P | 10A |

## Redundância e ambiguidade

| # | Onde | Problema | Correção | Etapa |
|---|---|---|---|---|
| C11 | `export/timeline.py:14,17`, `finishing/plan.py:32,200`, `mix/stems.py:21`, `export/pacote.py:218,276`, `assembly/service.py:61`, `assembly/plan.py:152`, `fcpxml.py:26`, `montagem.py:63`, `finish_fcpxml.py:64` | Três `FPS`, três `_frames()`, três `_t()` e vários `60` literais, contra `domain/frames.py:3-5` ("o arredondamento ser um só"). | `domain/frames` mais um `fcpxml_time()` único ([T1](T-transversal.md)). | 10B |
| C12 | `export/fcpxml.py` + `export/timeline.py` × `export/montagem.py` | Dois escritores de FCPXML, sem critério documentado e com contagem de ids divergente. A promessa de "OTIO/EDL" não existe. | Construtor comum de `resources`/`library`. Marcar `cronista export` como legado. **Decisão pendente 4.** | 10C |
| C13 | `mix/service.py:64-74`, `export/timelapse.py:41`, `shorts/render.py:232` | O wrapper de FFmpeg e a seleção de encoder estão repetidos. O timelapse usa NVENC sem `-cq` e sai com qualidade diferente. | Usar `run_ffmpeg` e `video_args` em todos os pontos ([T2](T-transversal.md)). | 10C |
| C14 | `export/pacote.py:81-84,128-133`, `mix/service.py:160` | `next_version_dir` repete `_version_numbers`, e `40*60.0` aparece no lugar de `DEFAULT_TARGET_S`. | Reutilizar a função e a constante. | 10C |
| C15 | `assembly/plan.Track` × `finishing/plan.Track`, `montagem.py:42-44`, `finish_fcpxml.py:29-30` | Dois enums `Track` e o mapa trilha→lane espalhado. | Um único enum de trilha, com a lane do FCPXML como atributo. | 10C |
| C17 | `fase-6` l. 50-52 × `montagem.py:90`; `integrations/resolve/cronista_kit_teste.py:3-4` | O doc pede caminho relativo e `marcadores.json`, mas o código usa URI absoluta. O kit ainda manda instalar em `Scripts\Utility`. | Atualizar o doc da fase e marcar o kit como superado pelo Console Lua (ver [F](F-documentacao.md)). | 10D |

## Testes a criar (10E)

- **C18:** render de timelapse interrompido não é reaproveitado (simular um arquivo parcial).
- **C18:** fusão de trechos com fala de roteiro no segundo trecho.
- **C18:** master sem `duration_frames` com dois cortes.
- **C18:** LUT aplicado na V2 (Lua gerado).
- **C18:** modo `editavel` para um tipo sem renderizador gera aviso e é rebaixado.
- **C18:** colisão de marcadores no mesmo quadro.
- **Fixtures:** parte delas deve passar `MediaFileInfo` **sem** duração.

## Aceite

- Nenhum artefato em cache é escrito fora de `render_to`.
- Toda fala de roteiro de um trecho incluído aparece no SRT e no ducking.
- Todo efeito com modo diferente de `sugerir` é de fato aplicado ou é rebaixado com aviso.
- **Conferência em `prod`:** importar o pacote no Resolve gratuito, conferir o LUT na V1 e na V2 e conferir os
  marcadores no mesmo quadro (C9).
