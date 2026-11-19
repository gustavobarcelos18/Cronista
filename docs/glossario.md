# Glossário do Cronista

**Status: proposta (10B, T4), aguardando aprovação do criador.** Depois de aprovado, o CLAUDE.md e o plano mestre passam
a citá-lo. A auditoria de 2026-11-18 achou termos sobrecarregados (ver `docs/auditoria/T-transversal.md`); cada linha abaixo
fixa um sentido só. Mudanças de nome **internas** (constantes, enums, docstrings) vão na 10C; as **públicas** (comandos da
CLI, valores gravados no banco) só com alias ou migração, nunca quebrando dados já salvos.

| Conceito | Termo | Definição |
|---|---|---|
| Quadro | **quadro** | Só o quadro de vídeo a 60 fps. Áudio usa **janela** e **hop**; nunca "quadro". Constantes: `AUDIO_SIGNAL_HOP` e `VIDEO_SAMPLE_HOP` (hoje as duas se chamam `HOP_FRAMES` e valem 6 e 12). |
| Faixa × trilha | **faixa** / **trilha** | **Faixa** = faixa de áudio do arquivo do OBS (1 = mix, 2 = jogo, 3 = microfone). **Trilha** = trilha da timeline do Resolve (V1, A2...). Um único enum `TimelineTrack`, com a lane do FCPXML como atributo (hoje há dois `Track`). |
| Segmento × trecho | **segmento** / **trecho** | **Segmento** = unidade da relevância (tem classe e nota). **Trecho** = segmento escolhido para a montagem (`EditItem`). |
| Capítulo | **marcador**, **dia**, **capítulo** | **Marcador** = ponto gravado pela hotkey ou capítulo gravado pelo OBS no arquivo. **Dia** = unidade fictícia da série (§ regras de produto). **Capítulo** = bloco narrativo de um dia na história. |
| Momento | **Momento**, **pico** | "Tecla Momento" e classe `momento`. Nos outros usos, **pico**. |
| Pacote | **story-pack**, **pacote do Resolve**, **pacote de publicação** | `story-pack`/`titulo-pack` = entrada das skills. Pacote do Resolve = saída da montagem (`data/export/montagem/<s>/versao-N`). Pacote de publicação = saída da embalagem (`publicacao/`). |
| Perfil | **perfil de jogo**, **perfil de voz**, **ambiente** | Perfil de jogo = YAML em `profiles/`. Perfil de voz = `voice-profile.json`. Ambiente = `dev`/`prod`. |
| Studio | **Studio**, **Resolve Studio** | **Studio** = o app (Next.js). **Resolve Studio** = a versão paga do DaVinci, sempre por extenso. |
| EDL × plano | **EDL**, **plano de montagem** | EDL = só o formato CMX. O plano interno (`edit_plan`) é o plano de montagem. |
| Decisões | `aceito` / `rejeitado` / `ajustado` / `padrao` | Um vocabulário só. Hoje: `aprovado`/`rejeitado` (Shorts), `aceito`/`removido` (acabamento), `aceito`/`rejeitado`/`ajustado` (segmentos). Exige migração Alembic de dados e aceite dos valores antigos na leitura. |
| Comandos da CLI | `<objeto>-<verbo>` | Objeto no plural (`shorts-decidir`, `titulos-escolher`, `thumbnails-escolher`), com alias para os nomes atuais. `export` fica deprecado em favor de `montagem` (§60). |

## Mapa de nomes atuais

- **Já resolvido na 10B:** `FPS` único em `domain/frames` (T1), FFmpeg em `media/ffmpeg` (T2) e pastas em `paths.py` (T3).
- **10C:** `AUDIO_SIGNAL_HOP`/`VIDEO_SAMPLE_HOP`, enum `TimelineTrack`, `kept_seconds`, remoção do painel antigo da série.
- **Público, com migração (a combinar):** vocabulário de decisões e renomeação dos comandos.
