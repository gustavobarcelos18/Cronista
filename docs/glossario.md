# Glossário do Cronista

**Status: aprovado pelo criador em 2026-11-19 (10B, T4), com uma ressalva:** o vocabulário de decisões **não** será unificado
agora (ver a linha "Decisões"). O CLAUDE.md e o plano mestre citam este glossário. A auditoria de 2026-11-18 achou termos sobrecarregados (ver `docs/auditoria/T-transversal.md`); cada linha abaixo
fixa um sentido só. Os identificadores abaixo correspondem ao código da Fase 10.

| Conceito | Termo | Definição |
|---|---|---|
| Quadro | **quadro** | Só o quadro de vídeo a 60 fps. Áudio usa **janela** e **hop**; nunca "quadro". Constantes: `AUDIO_SIGNAL_HOP` e `VIDEO_SAMPLE_HOP` (passos de 6 e 12 quadros de vídeo, respectivamente). |
| Faixa × trilha | **faixa** / **trilha** | **Faixa** = faixa de áudio do arquivo do OBS (1 = mix, 2 = jogo, 3 = microfone). **Trilha** = trilha da timeline do Resolve (V1, A2...). O enum `domain.tracks.Track` define a lane do FCPXML de cada trilha. |
| Segmento × trecho | **segmento** / **trecho** | **Segmento** = unidade da relevância com nota e uma das classes `momento`, `dia`, `conversa`, `farm`, `jogo` ou `descartavel`. **Trecho** = segmento escolhido para a montagem (`EditItem`). |
| Capítulo | **marcador**, **dia**, **capítulo** | **Marcador** = ponto gravado pela hotkey ou capítulo gravado pelo OBS no arquivo. **Dia** = unidade fictícia da série (§ regras de produto). **Capítulo** = bloco narrativo de um dia na história. |
| Momento | **Momento**, **pico** | "Tecla Momento" e classe `momento`. Nos outros usos, **pico**. |
| Pacote | **story-pack**, **pacote do Resolve**, **pacote de publicação** | `story-pack`/`titulo-pack` = entrada das skills. Pacote do Resolve = saída da montagem (`data/export/montagem/<s>/versao-N`). Pacote de publicação = saída da embalagem (`publicacao/`). |
| Perfil | **perfil de jogo**, **perfil de voz**, **ambiente** | Perfil de jogo = YAML em `profiles/`. Perfil de voz = `voice-profile.json`. Ambiente = `dev`/`prod`. |
| Studio | **Studio**, **Resolve Studio** | **Studio** = o app (Next.js). **Resolve Studio** = a versão paga do DaVinci, sempre por extenso. |
| EDL × plano | **EDL**, **plano de montagem** | EDL = só o formato CMX. O plano interno (`edit_plan`) é o plano de montagem. |
| Decisões | três vocabulários, por tela | **Aprovado como está, sem unificar** (a unificação exigiria migração de dados; fica como possibilidade sem urgência). Alvo descartado por ora: `aceito` / `rejeitado` / `ajustado` / `padrao`. Hoje: `aprovado`/`rejeitado` (Shorts), `aceito`/`removido` (acabamento), `aceito`/`rejeitado`/`ajustado` (segmentos). No acabamento e nos Shorts, a ação `padrao` restaura a decisão padrão daquele item. |
| Comandos da CLI | `<objeto>-<verbo>` | Objeto no plural (`shorts-decidir`, `titulos-escolher`, `thumbnails-escolher`), com os aliases legados `short-decidir`, `titulo-escolher` e `thumbnail-escolher`. `export` fica deprecado em favor de `montagem` (§60). |

## Mapa de nomes atuais

- **Já resolvido na 10B:** `FPS` único em `domain/frames` (T1), FFmpeg em `media/ffmpeg` (T2) e pastas em `paths.py` (T3).
- **Montagem:** `cronista montar` gera o plano de cortes. `cronista montagem` exporta o pacote para o Resolve.
- **Duração:** o alvo padrão é 40 minutos. A faixa editorial de referência é de 30 a 50 minutos. A opção `--target-min` e o parâmetro `target_min` da API aceitam valores maiores que zero e de até 240 minutos.
- **Seleção de arquivo:** sem `--file`, a CLI usa o primeiro arquivo da sessão em ordem. Um nome exato tem preferência. Uma parte do nome precisa identificar um único arquivo. Em `bench-audio` e `bench-video`, a busca considera as gravações presentes no disco.
- **Publicação:** `cronista pacote-publicacao` reúne o material escolhido na pasta de publicação da sessão.
