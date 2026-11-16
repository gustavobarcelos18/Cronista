# Fase 2 — Análise de áudio

Plano de execução. Fonte de verdade do produto: [00-plano-mestre.md](00-plano-mestre.md) (seção 7, Fase 2; seções 3 e 5.2).
Decisões que alimentam esta fase: [histórico §36, §40 e §41](01-historico-de-decisoes.md).

Status: plano escrito em 2026-11-16, ainda sem código · Branch: `fase/2-audio` (a partir da `main` com a 1C integrada, PR #6).

## Divisão

Como a Fase 1, esta fase é dividida para separar o que roda em qualquer PC do que exige GPU, modelos baixados e o gabarito.

| Sub-etapa | Onde roda | Depende de | Entrega |
|---|---|---|---|
| **2A – Fundação e sinais numéricos** | `dev` e `prod` (CPU, sem modelo baixado) | só da `main` | Lacunas 2–4 do plano (variante de artefato, evidência, sinais em série temporal); sinais de energia, novidade e periodicidade; portas de VAD, transcrição e eventos sonoros com fakes; etapas e relatório HTML |
| **2B – Modelos reais e benchmark de desempenho** | `prod` (RTX 3060) | 2A | Ambiente de ML isolado, adaptadores reais (Silero VAD, faster-whisper, classificador de eventos), benchmark de velocidade/VRAM/convivência de CUDA |
| **2C – Qualidade contra o gabarito** | `prod` | 2B **e o gabarito anotado pelo criador** | WER com e sem DeepFilterNet, eventos de áudio, rotina, teclado/respiração; escolha dos modelos; benchmark de roteiro do `LocalScriptProvider` |

2A não depende de nada em aberto e pode ser feita inteira agora. 2B só precisa do PC de casa. **2C é a que trava no criador:**
sem o gabarito anotado (2–3 h; hoje `data/gabarito/teste.csv` tem só 2 linhas de exemplo) não há como medir WER nem falsos
positivos, e os modelos da fase não podem ser escolhidos (plano, Fase 2: "os modelos da fase são escolhidos por esses números").
Até lá, 2A e 2B entregam tudo o que é verificável sem gabarito, e os modelos ficam como **candidatos**.

## Premissas herdadas

- Nunca se analisa a faixa 1 (mix). Jogo = faixa 2 (`game.wav`), microfone = faixa 3 (`mic.wav`), já extraídas pela etapa `audio` da ingestão (RF64 acima de 4 GB).
- A faixa 3 sai com supressão de ruído na origem (ClearCast do Sonar ou RNNoise, um só; histórico §41). Teclado e respiração podem estar atenuados demais para serem detectados: **a 2C mede isso**; se não der, reabre-se uma fonte crua ou as classes `teclado`/`respiracao` saem do gabarito.
- Tempo em **quadros inteiros a 60 fps** (`domain.frames`); segundos só nas bordas (soundfile, modelos). Todo resultado da fase carrega quadros.
- Todo processamento pausa com o OBS gravando ou jogo em tela cheia (`ctx.wait_for_gpu()` entre blocos nas etapas longas).
- Saída de LLM/modelo sempre validada por Pydantic. Sem `if jogo == ...`: a fase não usa perfil de jogo (a linha de base é só **por sessão**; o recorte por contexto visual é da Fase 3).
- `dev` sem GPU: tudo da 2A roda em CPU com fixtures sintéticas; o que exige modelo ou GPU é `@pytest.mark.gpu` / `@pytest.mark.media`.

## 2A — Fundação e sinais numéricos

### Tarefas

1. **Variante de artefato (lacuna 3, antes de qualquer benchmark).** `Artifact` e `Job` hoje têm `UniqueConstraint(media_file_id, stage)`: dois modelos ou parâmetros da mesma etapa se sobrescrevem.
   - Coluna `variant` (texto, padrão vazio) em `artifact` e `job`; unicidade passa a `(media_file_id, stage, variant)`. Migração `0005` (SQLite: recriar a tabela em lote, sem perder as linhas existentes).
   - `Stage` ganha `variant: str = ""` opcional; o executor usa `nome` ou `nome:variante` como chave nos `needs`, nos logs e no relatório. A chave de cache continua incluindo versão e parâmetros.
   - Etapas existentes não mudam de comportamento; o teste de retomada e o de invalidação por parâmetro continuam passando.
2. **Evidência e evento (lacuna 2).** Modelo Pydantic `Evidence` em `domain/` (fonte, quadro inicial e final inteiros, citação literal opcional, confiança 0–1, modelo, versão do modelo, hash dos parâmetros) com validação `inicio <= fim`. Tabela `event` (migração `0006`): `media_file_id`, `stage`, `variant`, `kind`, `start_frame`, `end_frame`, campos da evidência e `payload` JSON; índice por `(media_file_id, start_frame)`. Reexecutar uma etapa **substitui** os eventos dela (apaga por `media_file_id + stage + variant`, depois insere), nunca duplica. Os campos são os que a 5A vai normalizar na tabela `evidence` (seção 7 do plano); a 5A não precisa quebrar nada.
3. **Sinais em série temporal (lacuna 4).** Decisão proposta: um sinal é um **array `float32` em `.npy` no cache do SSD**, referenciado pelo `result.json` do artefato (o banco não guarda amostras).
   - Grade: um sinal tem `hop_frames` (múltiplo inteiro de quadros; padrão 6 = 0,1 s = 10 Hz). A amostra `i` cobre os quadros `[i·hop, (i+1)·hop)`; conversão quadro ↔ amostra é aritmética inteira, sem float.
   - `SignalMeta`: `name`, `unit`, `hop_frames`, `length`, `path`, `source_track`, proveniência (modelo, versão, hash dos parâmetros).
   - Consulta: `load_signal(...)` devolve a série (memmap) e `slice(inicio_frame, fim_frame)`. Sem tabela nova.
   - Registrar a decisão no plano (seção 9) e no histórico.
4. **Leitura de áudio e dependências.** `numpy` e `soundfile` (libsndfile lê RF64: ⚠️ confirmar com um WAV RF64 gerado pelo `audio_extract_args`, que o plano pede na seção 2). Leitura em blocos (60 s), nunca o WAV inteiro na memória (10 h de 48 kHz estéreo).
5. **Sinais numéricos em CPU** (`audio/`), etapa `audio_signals` (`needs=("audio",)`, sem GPU), versão própria:
   - **Jogo:** `energy_db` (RMS por amostra de sinal, em dBFS); `onset` (fluxo espectral em 100 Hz, agregado a 10 Hz); `novelty` (`onset` relativo à **mediana móvel da sessão**, janela de ~5 min, em desvios; é a mudança, não a altura); `periodicity` (força do pico da autocorrelação do `onset` em janela de ~20 s, lag 0,3–4 s, em 0–1).
   - **Microfone:** `energy_db` e sua mediana móvel de sessão (para "aumento súbito em relação à média da sessão", seção 3).
   - Parâmetros (janelas, hop, limiares) na chave de cache; nenhum específico de jogo.
6. **Portas dos modelos** (`audio/ports.py`), com implementações falsas determinísticas para teste: `SpeechDetector` (VAD → trechos de fala), `Transcriber` (palavras com tempo, por trecho), `SoundEventClassifier` (rótulo, intervalo, pontuação). Entradas e saídas em Pydantic; tempos convertidos para quadros na borda.
7. **Etapas de fala e eventos.** `speech` (VAD → transcrição, só nos trechos de fala; saída com palavras e tempos) e `sound_events` (jogo e microfone; no microfone só os rótulos risada e grito, seção 3). Um **sink** grava os resultados como linhas de `event` com `Evidence`. Variantes por modelo, para o benchmark comparar lado a lado.
8. **Relatório HTML da sessão** (`cronista report <sessão>`): arquivo único, sem servidor, com gráfico de sinais × tempo (SVG inline), marcadores e eventos sobrepostos, trechos de fala com texto e uma tabela de avisos. Visibilidade desde cedo; o Studio só vem na Fase 7.
9. **CLI:** `cronista analyze <sessão>` (roda as etapas de análise de cada arquivo, respeitando o gate) e `cronista report`. `cronista status` passa a listar as etapas de análise e suas variantes.
10. **Documentos:** plano mestre (seção 7, status da Fase 2; seção 9, decisões das lacunas 2–4), histórico (nova entrada) e este arquivo.

### Critérios de aceite (2A)

- [ ] `uv run pytest`, `ruff`, `mypy` (e `mypy --platform linux`) passam sem GPU e sem modelo baixado; CI verde em Ubuntu **e** Windows.
- [ ] Duas variantes da mesma etapa coexistem para o mesmo arquivo, sem se sobrescrever; mudar o parâmetro de uma invalida só ela e as seguintes.
- [ ] A migração `0005`/`0006` aplica sobre um banco existente (inclusive o de `data/prod`) sem perder linhas.
- [ ] Sobre sinais sintéticos: trem de cliques regular tem `periodicity` alta e `novelty` baixa; uma explosão no meio de ruído estável gera pico de `novelty` e `periodicity` baixa; silêncio não gera eventos.
- [ ] WAV RF64 (> 4 GB, gerado sintético ou por `-rf64 always` em arquivo curto) é lido em blocos sem erro; memória não cresce com a duração.
- [ ] Reexecutar a análise não duplica eventos; retomada após interrupção refaz só a etapa interrompida.
- [ ] O relatório HTML abre sem rede e mostra sinais, marcadores e fala da fixture sintética.

### Testes (2A)

Unitários dos sinais (sintéticos, sem FFmpeg), da grade quadro ↔ amostra, da substituição de eventos e das portas com fakes; integração da migração a partir de um banco `0004` com dados; integração da etapa `audio_signals` sobre a fixture com três faixas; teste do relatório sobre a fixture.

## 2B — Modelos reais e benchmark de desempenho

Só em `prod`. Os modelos entram como **dependências opcionais** (grupo `ml` do `pyproject`, ou ambiente próprio), fora do `uv sync` do CI e do `dev`.

### Tarefas

1. **Ambiente de ML.** Decidir, com base no teste da 1C (`integrations/cuda/check_cuda.py`: torch + CTranslate2 conviveram na RTX 3060), se tudo vive no mesmo ambiente do engine ou se a transcrição roda em processo separado (exceção do CTranslate2, seção 5.2). Versões exatas registradas depois de verificadas (hoje só de memória). Os modelos baixam para `data/models/` (fora do git); registrar origem, licença e tamanho de cada um.
2. **Adaptadores reais**, atrás das portas da 2A.1: Silero VAD; faster-whisper (large-v3-turbo, int8, timestamps por palavra e `vad_filter` coerente com o VAD próprio); classificador de eventos sonoros (candidatos: PANNs, BEATs, CLAP; um por vez, escolhido pelo benchmark). DeepFilterNet entra só como candidato de pré-processamento (⚠️ pode não instalar com Python 3.12 e PyTorch recentes; falhar aqui não bloqueia).
3. **Benchmark de desempenho** (`integrations/bench/` ou `cronista bench`): tempo real por hora de áudio, pico de VRAM e de RAM, convivência de CUDA (torch + CTranslate2 no mesmo processo e em processos separados), com a RTX 3060 ocupada só pelo benchmark. Sobre a gravação de teste real (`claude_teste.mp4`, 37 min) e sobre uma versão concatenada para estimar 10 h. Resultado registrado no histórico (tabela por modelo).
4. **Pausa de GPU na prática:** testar `wait_for_gpu` entre blocos com o OBS gravando de verdade (item ainda não validado da 1C).
5. Testes `@pytest.mark.gpu` por adaptador (poucos segundos de áudio real pequeno, só `prod`).

### Critérios de aceite (2B)

- [ ] Cada adaptador processa a gravação de teste do início ao fim em `prod`, retomável, com a GPU pausando quando o OBS grava.
- [ ] Tabela de desempenho (velocidade × tempo real, VRAM, RAM) por modelo registrada no histórico, com a estimativa para 10 h de sessão.
- [ ] Decisão de ambiente (um só ou processo separado para a transcrição) registrada, com as versões verificadas.

## 2C — Qualidade contra o gabarito

**Bloqueada pelo gabarito anotado** (formato e ferramenta prontos: `cronista gabarito`, [gabarito.md](gabarito.md)). Meta do criador: 2–3 h, começando pela gameplay de teste de ~30 min, com a faixa 3 do `MIC` ativa (a gravação de teste anterior tinha a faixa 3 muda).

### Tarefas

1. **Ferramenta de métricas** (`cronista bench-quality`): lê o gabarito e as saídas da etapa; calcula **WER** (jiwer ou implementação própria, após normalização de texto), precisão/revocação de eventos por classe (risada, grito) com tolerância em quadros, **falsos positivos de `teclado` e `respiracao`** e acerto de rotina (`farm`) por sobreposição. Tudo em quadros.
2. **Benchmark de WER:** Whisper com e sem DeepFilterNet (decide se ele entra na cadeia), com e sem o VAD próprio; escolha de tamanho/quantização do modelo pelos números.
3. **Benchmark de eventos sonoros:** os candidatos da 2B.2 contra `risada`/`grito` e contra a ausência de evento em `teclado`/`respiracao`. Se a supressão na origem tiver apagado teclado e respiração, registrar e reabrir a decisão do histórico §41 (fonte crua na faixa 4 **ou** tirar as classes).
4. **Rotina:** o detector de periodicidade da 2A contra os trechos `farm`; ajuste de janelas e limiares por sessão, sem constantes por jogo.
5. **Números de corte.** O plano fala em "WER aceitável" sem número (item 8 de "Em aberto"). Definir os cortes **antes de rodar o benchmark final**, com o criador, e registrá-los no plano. Proposta inicial a validar (não decidida): WER ≤ 15% na fala do criador; teclado e respiração com no máximo 1 evento falso a cada 10 min; ≥ 70% das rotinas do gabarito detectadas.
6. **Benchmark de roteiro do `LocalScriptProvider`** (histórico §40): o experimento só vale se passar aqui. Recorte curto de um trecho real, LLM local (Ollama) escrevendo, avaliado pelo criador contra o `NullProvider` e a skill `/humanizar`; resultado (passa ou não) registrado. Sem passar, o padrão continua `NullProvider`.
7. **Escolha dos modelos** e fixação das versões no código e no plano (seção 5.2).

### Critérios de aceite (2C = aceite da fase, plano mestre)

- [ ] No gabarito, **teclado e respiração não geram eventos** (dentro do corte definido).
- [ ] Fala transcrita com **WER dentro do corte** definido com o criador.
- [ ] Trechos rítmicos (`farm`) detectados como rotina (dentro do corte).
- [ ] Relatório HTML da sessão real mostra o que o criador espera ver (revisão dele, não só do teste automatizado).
- [ ] Modelos escolhidos e versões registrados; resultado do benchmark de roteiro registrado.

## Riscos desta fase

| Risco | Efeito | Mitigação |
|---|---|---|
| Gabarito atrasa | 2C parada | 2A e 2B entregam sem ele; modelos ficam como candidatos; usar o `claude_teste.mp4` como primeira anotação |
| ClearCast/RNNoise apaga teclado e respiração | classes do gabarito indetectáveis | medir na 2C; reabrir §41 (fonte crua) ou tirar as classes |
| DeepFilterNet não instala (Python 3.12) | sem esse candidato | já previsto: só entra se melhorar o WER |
| CUDA do CTranslate2 conflita com PyTorch | VRAM/DLL em conflito | processo separado para a transcrição (exceção da seção 5.2) |
| WAV de 10 h estoura memória ou o RF64 não lê | análise falha em sessões longas | leitura em blocos e teste RF64 já na 2A |
| Pausa por GPU deixa a análise horas parada | atraso, não erro | retomada por etapa e log do motivo da pausa (já existe) |
| Sinais por sessão distorcem em sessão muito curta | baseline instável | aviso no relatório e janela mínima; o recorte por cena entra na Fase 3 |

## Fluxo git

Branch `fase/2-audio`. Commits pequenos por tarefa, Conventional Commits em pt-BR. PR para a `main` ao fim de **2A** (verificável sem GPU) e outro ao fim de 2B/2C, para não segurar a integração do que já está pronto esperando o gabarito. `/code-review` antes de cada merge (na 1C ele não foi rodado).

## Em aberto (precisa do criador)

1. Anotar o gabarito (2–3 h) e gravar um teste falando no `MIC` (faixa 3 com sinal).
2. Aprovar os números de corte da 2C.
3. Autorizar o download dos modelos (tamanho total a registrar na 2B.1) e do ambiente de ML.
