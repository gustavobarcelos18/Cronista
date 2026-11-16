# Guia de configuração do OBS para o Cronista

Fonte: plano mestre, seções 2 e 4; Fase 1, tarefa 3 da 1C. Versão do OBS conferida em 2026-11-16: **33.0.1** (Windows).
Marcado com ⚠️ o que veio de memória e precisa de confirmação na tela do OBS.

## 1. Gravação (Configurações → Saída → Gravação)

| Item | Valor | Por quê |
|---|---|---|
| Formato | **Hybrid MP4** (`hybrid_mp4`) | Sobrevive a queda (o arquivo é reparável) e aceita marcadores de capítulo |
| Codificador | **NVENC H.264** (`obs_nvenc_h264_tex`), CQP 21, keyint 2 s | 8-bit; o Resolve gratuito não decodifica bem 10-bit (plano 6.5) |
| Trilhas de áudio | **1, 2 e 3** (máscara `RecTracks=7`) | 1 = mix, 2 = jogo, 3 = microfone (com RNNoise) |
| Resolução | Base e saída 1920×1080 | |
| FPS | **Valor comum 60** (`FPSType=0`, `FPSCommon=60`), nunca "Fracionário" | 60 fps exatos; 59,94 é rejeitado pela ingestão |
| Formato de cor | **NV12**, espaço **Rec. 709**, intervalo **Parcial** | SDR 8-bit |
| Taxa de amostragem | 48 kHz | |

Em `basic.ini` do perfil, as chaves que conferem isso: `RecFormat2=hybrid_mp4`, `RecEncoder=obs_nvenc_h264_tex`,
`RecTracks=7`, `FPSType=0`, `FPSCommon=60`, `ColorFormat=NV12`, `ColorSpace=709`, `ColorRange=Partial`.
(`FPSNum=30` que aparece no arquivo é ignorado quando `FPSType=0`; a gravação real confirmou 60/1 no `ffprobe`.)

Sem facecam. Não grave o mix para análise: ele é só para ouvir (CLAUDE.md).

## 2. Fontes de áudio (a parte que mais dá errado)

Cada fonte de áudio avançada define em quais trilhas ela vai (Mixer → engrenagem → **Propriedades de áudio
avançadas**, coluna "Trilhas"):

| Fonte | Tipo | Trilhas | Observação |
|---|---|---|---|
| `AUDIO_GAME` | Captura de saída de áudio | **1 e 2** | O jogo, sem o microfone |
| `MIC` | Captura de entrada de áudio | **1 e 3** | O microfone, **com** supressão de ruído (filtro RNNoise) e ganho, **não silenciado** |

Decisão de 2026-11-16 (histórico §41): **não existe mais a fonte `MIC_RAW`**. Uma fonte só, `MIC`, nas faixas 1 e 3.

Regras:
- `MIC` fica com o ícone de alto-falante **ligado** (não mudo). Mudo silencia as trilhas dele na gravação: foi o que
  deixou a faixa 3 do `Cronista_Teste.mp4` vazia (−91 dB, silêncio digital).
- A análise usa só as faixas 2 e 3. Teclado e respiração ficam atenuados pelo RNNoise: se a detecção dessas classes
  falhar no benchmark da Fase 2, a alternativa é uma fonte crua na faixa 4 (decisão a reabrir).
- Como configurar no OBS: apague a fonte `MIC_RAW`; renomeie `MIC_MIX` para `MIC`, aponte para o microfone que você
  vai usar, em Propriedades de áudio avançadas marque as trilhas **1 e 3** (e só elas) e confira o filtro RNNoise.

**Estado do PC de casa em 2026-11-16 (lido do arquivo de cena às 13:16, não da tela; o OBS só grava as cenas ao fechar):**
`MIC_RAW` nas trilhas 3 (+7/8) e **mudo**; `MIC_MIX` na trilha 1, **sem filtros** e em **outro dispositivo** (o da FIFINE
SC3); `AUDIO_GAME` nas trilhas 1 e 2. Falta o ajuste acima.

## 3. Servidor WebSocket (para o gravador de marcadores)

Ferramentas → **Configurações do servidor WebSocket**:
- Ativar servidor, porta **4455**, autenticação ligada.
- Senha: copie para `obs_password` em `config/prod.local.yaml` (fora do git) ou para a variável de ambiente
  `CRONISTA_OBS_PASSWORD`. Nunca no YAML versionado.
- Estado em 2026-11-16: `server_enabled: false` no arquivo de configuração do plugin; ligar antes de testar o gravador.
- Requisição usada para marcar: `CreateRecordChapter` (obs-websocket 5.5+, incluída no OBS 30.2+; ⚠️ de memória).
  No OBS 33.0.1 deve existir; o teste da seção 6 confirma.

## 4. Jogo e OBS como administrador

Se o jogo roda elevado, ou o anti-cheat bloqueia teclas, um programa sem elevação não recebe as hotkeys globais
(plano, seção 4). Teste com cada jogo da série; se falhar: rode o terminal do gravador como administrador, ou use
a FIFINE/macropad (ver `integrations/fifine/`).

## 5. Pasta de gravação e `config/prod.local.yaml`

O OBS não informa o arquivo ao iniciar a gravação; o gravador o procura na pasta (`watch_dir`).

```yaml
# config/prod.local.yaml (fora do git)
data_dir: D:/EditorVideo/data/prod
watch_dir: "D:/GRAVAÇÃO BRUTA DOS VIDEOS SEM EDIÇÃO"
# obs_password: ...   # ou a variável CRONISTA_OBS_PASSWORD
```

## 6. Roteiro de teste (seguir do zero e anotar)

1. Aplicar as seções 1 a 3. Abrir um terminal em `services/engine` com `CRONISTA_ENV=prod`.
2. Conferir o ambiente: `uv run cronista record --help` e a conexão do gravador com o OBS aberto.
3. Gravar ~3 min: um `Novo dia`, dois `Momento`, uma pausa de ~20 s no meio, falar ao microfone, jogar algo com som.
4. Parar a gravação. Sem fechar o gravador, rodar `uv run cronista ingest <pasta>` e `uv run cronista status`.
5. Conferir no `ffprobe`: 3 faixas de áudio; faixa 3 com sinal (`ffmpeg -i x.mp4 -map 0:a:2 -af volumedetect -f null -`,
   `mean_volume` acima de -60 dB); capítulos com nome `tipo|id` (`ffprobe -show_chapters`).
6. `uv run cronista preview 1` e `uv run cronista export 1`; abrir o MP4 e importar o `.fcpxml` no Resolve.
7. Repetir com **gravação interrompida de propósito** (encerrar o OBS pelo gerenciador de tarefas): conferir o remux,
   as 3 faixas e se os capítulos sobreviveram. Registrar o resultado no histórico.

Critério de aceite da 1C: o passo 4 termina sem erro e sem aviso de formato.

## 7. O que a gravação real já provou (2026-11-16)

- `Cronista_Teste.mp4` e `testeia.mp4` (Hybrid MP4 do OBS 33): H.264 High, yuv420p, bt709/tv, 1920×1080, **60/1 exatos**,
  3 faixas AAC + 1 faixa de dados; ingestão sem aviso (normalize, proxy, áudio).
- Capítulos: o OBS grava um capítulo inicial `Iniciar` em 0 s e um final `Dummy`; capítulos criados à mão saem como
  `Sem nome N`. Eles viram `Momento` com aviso (marcador só no arquivo).
- Capítulos de `Cronista_Teste.mp4` usam base de tempo 1/48000 e os de `testeia.mp4` 1/1000: o engine converte a segundos.
