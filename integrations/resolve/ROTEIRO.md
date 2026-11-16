# Roteiro de checagem do DaVinci Resolve gratuito (spike da 1C)

Origem: checklist do plano mestre, seção 6.5. Preencha **Resultado** (OK / parcial / falhou) e **Observação** de
cada item. Os itens com ⚠️ no plano ganham resposta aqui e depois são movidos para a seção 6.5 (critério de aceite da 1C).
Nada deste roteiro foi executado ainda: o Resolve não está instalado no PC de casa em 2026-11-16.

## Preparação

1. Instalar o DaVinci Resolve **gratuito** (anotar a versão exata: ________).
2. Copiar `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\README.txt` para
   `docs/referencias/resolve-scripting-README.txt` (consulta em qualquer PC).
3. Gerar o kit (cria `data/prod/kit-resolve/`, não versionado):
   ```bash
   cd services/engine
   CRONISTA_ENV=prod uv run cronista resolve-kit
   ```
4. Projeto do Resolve: **1920×1080, 60 fps** (Configurações do Projeto → Master Settings → Timeline frame rate = 60).
   Conferir que está em **60** e não em 59,94.

O kit tem três FCPXML separados de propósito: se um falhar, o item culpado fica claro.

| Arquivo | Contém |
|---|---|
| `01-basico.fcpxml` | dois cortes, volume -6 dB, marcador e marcador de capítulo, relink |
| `02-recursos.fcpxml` | título "Dia 1", velocidade 2x, zoom/posição com keyframe, transição, overlay com alfa, clipe HEVC |
| `03-audio.fcpxml` | faixas de áudio do MP4 por canal, canal desativado |
| `marcadores.edl` | três marcadores coloridos (azul, vermelho, verde) |
| `roteiro.srt` | três falas |
| `teste.cube` | LUT que esquenta a imagem |
| `clips/` | `A_h264` (3 faixas: 440, 660 e 880 Hz), `B_h264`, `C_hevc`, `overlay_alfa.mov` |

## A. Importação de FCPXML (File → Import → Timeline)

| # | Item | Como conferir | Resultado | Observação |
|---|---|---|---|---|
| A1 | `01-basico.fcpxml` importa sem erro | Timeline criada, 2 clipes, 10 s | | |
| A2 | Timeline fica em 60 fps exatos | Configurações da timeline | | |
| A3 | Volume -6 dB do primeiro clipe | Inspetor → Áudio | | |
| A4 | Marcador "Momento" em 2 s, nota `momento\|teste-001` | Marcadores da timeline | | |
| A5 | **Relink**: renomear `clips` para `clips_x`, reimportar, apontar para a pasta certa | Resolve pede e aceita o relink | | |
| A6 | `02-recursos.fcpxml` importa (anotar o que falta se for parcial) | | | |
| A7 | Velocidade 2x (clipe 2 dura 5 s e mostra 10 s da fonte) | Inspetor → Velocidade | | |
| A8 | Zoom e posição **com keyframes** (clipe 3) | Inspetor → Transformar, losangos de keyframe | | |
| A9 | Transição Cross Dissolve entre os clipes 3 e 4 | Linha do tempo | | |
| A10 | Título "Dia 1" editável (vira Text+? título simples?) | Duplo clique, trocar para "Dia 2" | | |
| A11 | Overlay com alfa (retângulo vermelho) numa trilha **acima** | V2 transparente, sem fundo preto | | |
| A12 | Clipe HEVC 8-bit importa, toca e renderiza | Tocar e exportar 5 s | | |
| A13 | `03-audio.fcpxml`: faixa 2 do MP4 em A1 e faixa 3 em A2 (ouvir: 660 Hz em A1, 880 Hz em A2) | Solo em cada trilha | | |
| A14 | Canal marcado `enabled="0"` chega desativado (A6/A7 do plano 6.3) | Trilha silenciada/desativada | | |
| A15 | Em que trilhas o Resolve põe V1–V5 e A1–A7? Dá para criar A3/A4 vazias? | Anotar o layout | | |
| A16 | Rodar o mesmo teste com o FCPXML do app: `cronista export 1` (`data/prod/export/sessao-1.fcpxml`) | Importa igual aos do kit? | | |

## B. Marcadores, legenda e cor

| # | Item | Como conferir | Resultado | Observação |
|---|---|---|---|---|
| B1 | `marcadores.edl` (Timeline → Import → Timeline Markers from EDL) | Três marcadores, cores azul/vermelha/verde, nome e duração | | |
| B2 | Se o B1 falhar: o mesmo resultado pelo script interno (`AddMarker` com cor) | Ver `resultado-script.txt` | | |
| B3 | `roteiro.srt` alinhado com a timeline | Legenda aos 1 s, 4 s e 8 s | | |
| B4 | Cartela "Dia N": trocar o número no Resolve pelo FCPXML (A10) e pelo script interno | | | |

## C. Script interno (Workspace → Scripts)

1. Copiar `integrations/resolve/cronista_kit_teste.py` para
   `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`.
2. Rodar por **Workspace → Scripts → cronista_kit_teste** com um projeto vazio aberto.
3. Colar aqui o conteúdo de `data/prod/kit-resolve/resultado-script.txt`.

| # | Item | Resultado | Observação |
|---|---|---|---|
| C1 | O script roda de dentro do Resolve, sem janela própria (19.1+ pode restringir a UI) | | |
| C2 | Criar projeto, importar mídia, timeline, marcadores com cor, LUT | | |
| C3 | `ImportTimelineFromFile` funciona pela API | | |
| C4 | Rodar de fora (`python cronista_kit_teste.py` no terminal): bloqueado no gratuito? | | |
| C5 | A API de keyframes não existe (confirmar); `SetProperty` de zoom/pan estático funciona | | |

## D. Desempenho e render

| # | Item | Como medir | Resultado | Observação |
|---|---|---|---|---|
| D1 | Decodificação H.264 por GPU no gratuito | Tocar `Cronista_Teste.mp4` (1080p60) na timeline; abrir o Gerenciador de Tarefas (GPU → Decode de vídeo) ou `nvidia-smi dmon -s u` (coluna `dec`) | | |
| D2 | Fluidez: master H.264 × proxy DNxHR | Gerar um DNxHR LQ do trecho; tocar os dois sem cache; anotar quadros perdidos | | |
| D3 | HEVC 8-bit do OBS (gravar 30 s com HEVC, se o codec estiver disponível) | Importar, tocar, exportar | | |
| D4 | Hybrid MP4 após queda: abrir o remuxado (`ffmpeg -map 0 -c copy`) sem recodificar; 3 faixas continuam | Roteiro do OBS, passo 7 | | |
| D5 | Página Deliver oferece ProRes no Windows? | Listar codecs de exportação | | |
| D6 | Render de 10 min de timeline pela CPU (H.264) | Cronômetro: ______ min | | |
| D7 | Rota intermediário DNxHR SQ + NVENC (`ffmpeg -c:v h264_nvenc`) para os mesmos 10 min | Cronômetro: ______ min; tamanho do intermediário: ______ GB | | |

## E. Conclusão

- Rota A (importar FCPXML pelo menu) basta? ____________
- Rota B (script interno) é necessária para: ____________
- Render final: rota 1 (CPU no Resolve) ou 2 (intermediário + NVENC)? ____________
- Itens do plano 6.5 respondidos (mover para a seção 6.5): ____________
- Bloqueios para a Fase 6: ____________
