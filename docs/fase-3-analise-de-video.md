# Fase 3 — Análise de vídeo e perfis de jogo

Plano de execução. Fonte de verdade do produto: [00-plano-mestre.md](00-plano-mestre.md) (seção 7, Fase 3; seções 3, 5.2 e 6.2).
Decisões que alimentam esta fase: [histórico §36, §38 e §45](01-historico-de-decisoes.md). Padrões herdados da Fase 2:
[fase-2-analise-de-audio.md](fase-2-analise-de-audio.md) (variante de artefato, `Evidence`/`event`, sinais `.npy`, portas, gate de GPU).

**Status vigente: tabela única em [plano mestre §7](00-plano-mestre.md). O texto abaixo é o registro da época e pode estar superado.**

Status (2026-11-17): **3A implementada** em `fase/3-video`: leitor de frames, sinais visuais, heurística de menu/loading/idle, câmera e cortes, seção de vídeo no relatório HTML (faixa de estados, 4 gráficos, miniaturas dos trechos mais longos) e `analyze --only audio|video` (histórico §47). `pausa` passou para a 3B (precisa de embeddings); `orbita` ainda não. **Pendente da 3A:** conferir os resultados reais contra o vídeo (olho do criador) e calibrar na 3C. **3B implementada** (contextos, `novelty_ctx`, benchmarks, B-roll com utilidade/clima/HUD, tipos de menu, HUD oculto e `idle` pela cena parada com HUD inteiro; histórico §48–§50). **Pendente da 3B:** conferir contextos e B-roll de olho em mais sessões e provar o HUD oculto com um trecho real (F1/modo diretor). 3C não começou.

## Objetivo e aceite

Entender **o que está na tela** sem nenhum conhecimento do jogo: cenas, movimento, menu/loading/pausa/idle, contexto visual
(cenas parecidas agrupadas), tomadas cinematográficas para a biblioteca de B-roll e, opcionalmente, texto de HUD por OCR.

✅ **Aceite do plano mestre:** menus, loading e idle detectados com alta precisão no gabarito **sem nenhum perfil de jogo**;
perfil de jogo plugável sem tocar no núcleo. "Alta precisão" não tem número: a proposta está em "Números de corte" e **precisa
da sua aprovação antes do benchmark final** (item 8 de "Em aberto" do plano).

## Divisão

Mesma lógica da Fase 2: separar o que roda sem GPU, sem modelo e sem gabarito do que exige.

| Sub-etapa | Onde roda | Depende de | Entrega |
|---|---|---|---|
| **3A – Frames, cenas e sinais visuais** | `dev` e `prod` (CPU, fixtures sintéticas) | só da `main` | Leitura de frames do proxy, detecção de cena, sinais de movimento e de "tela parada", heurística universal de menu/loading/idle, eventos com `Evidence`, seção de vídeo no relatório HTML |
| **3B – Embeddings, contexto visual e B-roll** | `prod` (RTX 3060) | 3A | SigLIP/CLIP a 1–2 fps atrás de porta, agrupamento de cenas parecidas, linha de base do áudio **por contexto**, tags e biblioteca de B-roll, benchmark de desempenho |
| **3C – Perfis, OCR, VLM e qualidade** | `prod` | 3B **e o gabarito com `menu`/`loading`/`idle`** | Perfil genérico + perfis YAML, RapidOCR em regiões de HUD, VLM só em candidatos, métricas contra o gabarito, números de corte |

3A e boa parte da 3B (porta + fake) rodam sem nada em aberto. **A 3C trava no gabarito**: o `teste.csv` tem 2 linhas, nenhuma
de `menu`/`loading`/`idle`. O gabarito da Fase 2 (2–3 h) deve incluir essas classes para servir às duas fases.

## Premissas herdadas

- **Proxy 360p** (SSD) para tudo que é barato e global: cenas, movimento, embeddings. **Master** só para o que precisa de
  detalhe (OCR de HUD). Nunca decodificar o master inteiro por padrão: 10 h de H.264 60 fps é o gargalo.
- Tempo em **quadros inteiros a 60 fps**; amostrar frames é `frame = i · passo`, aritmética inteira. Segundos só nas bordas.
- Todo resultado vira `Evidence` (fonte `cena`/`sinal`/`evento`) e linhas de `event`; séries temporais viram `.npy` com
  `SignalMeta` (mesmo padrão da 2A). Variante por modelo/parâmetro para o benchmark comparar lado a lado.
- Todo processamento pausa com o OBS gravando ou jogo em tela cheia (`ctx.wait_for_gpu()` entre blocos).
- **Universal:** nenhum `if jogo == ...` no núcleo. O que for específico vai para perfil YAML declarativo (3C).
- **Sem facecam**, SDR 8-bit: sem tratar HDR nem webcam.
- `dev` sem GPU: 3A inteira em CPU com vídeo sintético gerado por FFmpeg (`devtools/fixtures.py`); o que usa GPU ou mídia real
  é `@pytest.mark.gpu` / `@pytest.mark.media`.
- Dependências de ML novas entram só no grupo opcional `ml` (histórico §44); a CI e o `dev` não as instalam.

## 3A — Frames, cenas e sinais visuais

### Tarefas

1. **Leitor de frames amostrados** (`video/frames.py`): FFmpeg (pipe `rawvideo`, tons de cinza e RGB 360p) lendo o proxy em
   blocos, a taxa de amostragem configurável (padrão 5 fps para movimento, 1 fps para o que vem depois). Memória constante;
   retomável por bloco; nunca o vídeo inteiro em RAM. ⚠️ Confirmar se o proxy atual preserva o timestamp exato (60 fps) e se
   a contagem de frames bate com o master.
2. **Detecção de cena** (`video/scenes.py`): PySceneDetect (⚠️ versão e API a verificar; de memória, `ContentDetector`/`AdaptiveDetector`)
   **ou** implementação própria sobre a diferença de histograma; decidir pelo custo e pela facilidade de testar. Saída: cortes em quadros.
   Em jogo em primeira pessoa quase não há cortes; os que existem (menu, loading, cinemática, morte, teleporte) são o sinal.
3. **Sinais visuais em série temporal**, etapa `video_signals` (`needs=("proxy",)`, CPU), `hop_frames` como na 2A:
   `motion` (diferença média entre quadros amostrados), `flow_global` (fluxo óptico denso em baixa resolução: magnitude e
   direção média, separa parado/panorâmica/órbita), `still` (fração da tela que não mudou; tela congelada), `luma_mean`/`luma_std`
   (tela preta, branca, clareando: fades de loading), `edge_density` (menus têm muito texto e bordas retas).
4. **Linha de base visual por sessão** (mediana móvel, como o `novelty` do áudio): o que importa é a mudança em relação ao
   normal da sessão, não o valor absoluto.
5. **Heurística universal de estado de tela** (`video/screen_state.py`): combina os sinais acima em candidatos de
   `menu`, `loading`, `idle` e `pausa`, **sem rótulo por jogo**. Regras iniciais (a calibrar na 3C, sem constante por jogo):
   - `loading`: tela quase preta/estável por vários segundos, ou barra/animação pequena sobre fundo estático (`still` alto com `edge_density` baixo).
   - `menu`: `still` alto, `edge_density` alto, sem fluxo global, com mudanças locais pequenas (cursor).
   - `idle`: câmera e cena paradas (`flow_global` ≈ 0) mas a tela **não** é menu nem loading.
   - `pausa`: igual a menu com o fundo do jogo congelado e escurecido.
   Cada candidato sai com confiança e com os sinais que o justificaram no `payload` (explicável, vai para a nota da Fase 4).
6. **Eventos e etapa de cenas** (`video_scenes`): `event` com `kind` = `cena`, `menu`, `loading`, `idle`, `pausa`, `movimento_camera`
   (`parada`/`panoramica`/`orbita` no `payload`) e `Evidence` completa. Reexecutar substitui os eventos da etapa (regra da 2A).
7. **Seção de vídeo no relatório HTML** (`cronista report`): faixa de estados de tela sobre o tempo, sinais visuais em SVG,
   miniaturas dos candidatos de menu/loading/idle (frame no meio do trecho) para você conferir de olho.
8. **CLI:** `cronista analyze` passa a rodar também as etapas de vídeo (`--only video|audio`); `cronista status` lista as variantes.
9. **Fixtures sintéticas** (FFmpeg): vídeo com "gameplay" (ruído em movimento), trecho preto (loading), trecho estático com
   texto (menu), trecho parado com câmera fixa (idle) e cortes conhecidos. Verdade de campo gerada junto, para teste automático em `dev`.
10. **Documentos:** plano (status da Fase 3, seção 9), histórico (nova entrada) e este arquivo.

### Critérios de aceite (3A)

- [ ] `uv run pytest`, `ruff`, `mypy` (e `mypy --platform linux`) passam sem GPU; CI verde em Ubuntu e Windows.
- [ ] Nas fixtures sintéticas, cada trecho de loading/menu/idle é detectado dentro de 1 s e sem falso positivo na "gameplay".
- [ ] `cronista analyze` e `report` rodam no `claude_teste.mp4` (37 min, `prod`) e o relatório mostra estados plausíveis de olho (a validação de número fica para a 3C).
- [ ] Processa em bem menos que o tempo real (meta a medir; ver riscos) e retoma depois de interrompido.
- [ ] Nenhum parâmetro nem regra menciona um jogo.

## 3B — Embeddings, contexto visual e B-roll

### Tarefas

1. **Porta `FrameEmbedder`** (`video/ports.py`) com fake determinístico para teste e adaptador real **SigLIP ou CLIP**
   (⚠️ escolher por benchmark; ONNX Runtime ou PyTorch, conforme o padrão da seção 5.2). 1–2 fps sobre o proxy, em lotes, com o gate de GPU.
   Embeddings como `.npy` (N × D, `float16`) no cache; só a referência no `result.json`.
2. **Contexto visual (e tipo de menu):** agrupar cenas parecidas (clustering sobre os embeddings, p. ex. por similaridade de cosseno com limiar, ou HDBSCAN;
   ⚠️ decidir e registrar) em **contextos** numerados por sessão (ex.: "base", "mina", "menu", "mundo aberto"), sem nome por jogo.
   Saída: `event` `contexto` com id do grupo e confiança; um frame representativo por contexto.
3. **Linha de base do áudio por contexto** (promessa da seção 3 do plano): recalcular `novelty` do jogo com a mediana
   móvel **dentro do contexto**, não da sessão inteira. Entra como variante de sinal (`novelty_ctx`) ao lado da `novelty` da 2A,
   para comparar. Contexto com pouco tempo cai para a linha de base da sessão (aviso).
4. **Biblioteca de B-roll** (seção 6.2): para trechos com câmera parada/panorâmica/órbita e HUD oculto, calcular um preditor de
   beleza simples (estético sobre os embeddings) e **busca por texto** ("pôr do sol", "vista da base") via embedding de texto do mesmo modelo.
   Tabela `broll_clip` (migração nova): arquivo, intervalo em quadros, movimento, nota de beleza, tags, frame de capa. Uso real na Fase 6.
5a. **Tipo de menu e `idle` de verdade:** menus parecidos agrupados por embedding (configuração, inventário, diálogo, mapa) e nomeados pelo VLM só nos grupos; peso por tipo na Fase 4. `idle` (personagem parado com o jogo rodando) só volta aqui, porque a heurística de 3A não o separa de página de texto escura (histórico §47).
5. **Detecção de HUD oculto** (universal): regiões de borda sem estrutura estável por longos períodos; confiança baixa, serve de pista para B-roll.
6. **Benchmark de desempenho** (`cronista bench-video`): fps de embeddings, VRAM, tempo para 10 h extrapolado de 10 min, como o `bench-audio`; registrar no histórico.
7. **Relatório:** mapa de contextos (miniatura + tempo total) e a galeria de B-roll candidato.

### Critérios de aceite (3B)

- [ ] (código e testes em CPU prontos, histórico §48) Embeddings da sessão de teste em `prod`, retomáveis, com a GPU pausando quando o OBS grava.
- [ ] Contextos coerentes de olho na sessão de teste; `novelty_ctx` coexiste com `novelty` sem sobrescrevê-la (variante).
- [ ] Busca por texto devolve tomadas plausíveis na sessão de teste.
- [x] Tabela de desempenho e a escolha SigLIP × CLIP registradas, com versões verificadas (histórico §49, `docs/benchmarks/`).

## 3C — Perfis, OCR, VLM e qualidade contra o gabarito

**Bloqueada pelo gabarito** com `menu`/`loading`/`idle` (e `cinematica`, `construcao` se possível).

### Tarefas

1. **Perfil genérico universal e perfis declarativos** (`profiles/*.yaml`): o núcleo roda com o perfil genérico; um perfil de
   jogo só **acrescenta** (regiões de HUD, limiares ajustados, rótulos de contexto, `camera_tools`: ferramentas de câmera do jogo para sugerir gravação de B-roll, histórico §50). Validado por Pydantic/JSON Schema; sem código por jogo.
   Interface `GameAdapter` apenas esboçada (leitores de mods ficam fora do escopo, seção 7 do plano).
2. **OCR de HUD** (RapidOCR, ONNX), **só em regiões definidas no perfil**, lido em frames do **master** (no proxy 360p o texto fica ilegível).
   Amostragem baixa (ex.: 1 frame a cada poucos segundos) e só nos trechos pedidos. Saída: `event` `hud_texto` com a citação em `quote`.
   ⚠️ Verificar a versão do RapidOCR e se o runtime ONNX com CUDA convive com o PyTorch do ambiente `ml`.
3. **VLM local** (`transformers` + Qwen3-VL 4B, sem Ollama; histórico §49) **só em trechos candidatos** (estado de tela
   incerto, B-roll, momentos). Saída em JSON Schema validada por Pydantic, uma pergunta fechada por vez (histórico §40); nunca descrição livre em massa.
4. **`cronista bench-video-quality`** (mesmo desenho do `bench-quality` da 2C): lê o gabarito e os eventos e calcula, por classe
   (`menu`, `loading`, `idle`, `cinematica`), precisão, revocação e erro de bordas em quadros, com tolerância configurável.
5. **Calibração sem constante por jogo:** ajustar limiares da heurística de 3A **por sessão** (a partir da linha de base) ou por
   perfil. Se uma classe só funciona com perfil, registrar isso (o aceite exige o genérico).
6. **Teste de plugabilidade:** adicionar um perfil de exemplo sem alterar uma linha do núcleo (teste automatizado que falha se o núcleo importar o perfil).
7. **Números de corte** aprovados por você **antes** do benchmark final; escolha de modelos e versões fixadas no plano (seção 5.2).

### Plano de execução da 3C (2026-11-17)

Branch `fase/3c-perfis` a partir da `main`, depois do merge do PR #13 (3B). Cinco blocos; o 1 e o 2 não dependem um do outro e começam já.

| Bloco | O que entrega | Depende de | Onde roda |
|---|---|---|---|
| **3C-1 Gabarito visual e métricas (código feito; falta anotar, histórico §50A)** | `gabarito-ui` com **candidatos visuais** (miniatura do trecho de menu/loading/idle/hud_oculto: aceitar, rejeitar ou ajustar bordas, como as sugestões do Whisper na 2C); classe nova `hud_oculto` no gabarito; `cronista bench-video-quality` (precisão, revocação e erro de bordas por classe, tolerância configurável); relatório com a medida **da heurística atual** (linha de base) | Você anotar | `dev` (código), `prod` (mídia real) |
| **3C-2 Perfis e plugabilidade (feito, histórico §50A)** | Schema Pydantic + JSON Schema do perfil (`profiles/*.yaml`): `hud_regions` (nome, retângulo relativo, tipo de leitura), `thresholds` (ajustes sobre o genérico), `context_labels`, `camera_tools`, `objetivos`/`regras`; perfil genérico embutido; carregador; `profiles/exemplo.yaml` (Minecraft: só dados, sem código); **teste que falha se o núcleo importar ou citar um perfil** | nada | `dev` |
| **3C-3 OCR do HUD (código feito; falta medir com RapidOCR real, histórico §50A)** | Porta `HudReader` + adaptador RapidOCR 3.10 (CPU, ONNX); etapa `video_hud_text` lê **só as regiões do perfil**, em frames do **master a 720p**, 1 frame a cada poucos segundos, só nos trechos pedidos; eventos `hud_texto` com `quote`; o bioma do minimapa (ex.: "spider_caves") vira tag de tema do B-roll | 3C-2 | `prod` (master) |
| **3C-4 VLM local (porta, perguntas e nomes de menu em código; falta baixar e medir, histórico §50A)** | Porta `ScreenVLM` + adaptador `transformers` com Qwen3-VL 4B (4 bits se o bitsandbytes funcionar no Windows; senão modelo que caiba em 12 GB); **uma pergunta fechada por vez**, JSON Schema validado por Pydantic; usos: (a) **nomear cada tipo de menu** (7 perguntas no `claude_teste`, não 28), (b) desempate de estado de tela duvidoso, (c) confirmar clima/tema de B-roll candidato ("há inimigo na imagem?"); nunca descrição livre em massa, nunca em stream | 3C-1 (para medir) | `prod` (GPU, com o gate) |
| **3C-5 Calibração e corte final** | Limiares da 3A/3B (`menu_edge`, `dark_luma`, `hud_full`, `hidden_match`, `similarity` de menu) ajustados **por sessão** a partir da linha de base ou por perfil; propor números de corte; **você aprova**; benchmark final; registrar o que só funciona com perfil | 3C-1 a 3C-4, aprovação | `prod` |

**Ordem sugerida:** 3C-2 e 3C-1 (código) em paralelo, enquanto você anota; depois 3C-3, 3C-4 e por fim 3C-5. Cada bloco é um conjunto pequeno de commits; PR para a `main` ao fim da 3C, com `/code-review`.

**O que preciso de você:**
1. **Anotar o gabarito visual** em sessões que já existem (`claude_teste.mp4`, 37 min; sessões 2 e 3): com os candidatos da 3C-1 é confirmar ou rejeitar miniaturas, algo em torno de 30–60 min, sem gravar nada.
2. **Gravar ~30 s com o HUD escondido** (F1 no Minecraft, modo diretor ou Replay Mod) no meio de uma sessão normal: prova o HUD oculto e entra no gabarito.
3. **Escolher o segundo gênero** (item 4 de "Em aberto") para provar que o genérico funciona fora do primeiro jogo; basta uma sessão curta (~20 min).
4. **Autorizar o download do Qwen3-VL 4B** (tamanho a registrar antes de baixar) e **aprovar os números de corte** (abaixo) quando eu os propuser.

**Aceite da 3C-1:** `bench-video-quality` roda no `claude_teste.mp4` e imprime precisão/revocação por classe; os números de hoje (heurística da 3A/3B) ficam registrados como linha de base no histórico.

### Números de corte (proposta inicial, a validar; não decidida)

- `menu`/`loading`: precisão ≥ 90% e revocação ≥ 80% por trecho, bordas dentro de 2 s, **sem perfil de jogo**.
- `idle`: precisão ≥ 80% (é mais ambíguo; confundir com pausa de leitura é aceitável).
- Falsos positivos de `loading`/`menu` em gameplay normal: no máximo 1 a cada 30 min.
- OCR de HUD: ≥ 90% de acerto nas regiões de teste do perfil de exemplo.

### Critérios de aceite (3C = aceite da fase)

- [ ] Menus, loading e idle no gabarito dentro dos cortes, **sem perfil de jogo**.
- [ ] Perfil de exemplo plugado sem tocar no núcleo (teste automatizado).
- [ ] OCR e VLM só atuam onde o perfil/candidato pede, e nunca no mix de áudio nem em stream em massa.
- [ ] Relatório de uma sessão real mostra o que você espera ver (revisão sua, não só do teste).
- [ ] Modelos escolhidos e versões registrados no plano.

## Riscos desta fase

| Risco | Efeito | Mitigação |
|---|---|---|
| Gabarito atrasa (de novo) | 3C parada | 3A e 3B entregam sem ele; usar o `claude_teste.mp4` e começar pelas classes visuais, que são rápidas de anotar |
| Heurística sozinha confunde menu, pausa e cinemática | precisão baixa | embeddings (3B) como segunda opinião e VLM só nos duvidosos; perfil só como último recurso e registrado |
| Decodificar o proxy leva mais que o esperado | 10 h demoram demais | amostragem baixa (1–5 fps), decodificação por NVDEC se disponível (⚠️ medir), retomada por bloco |
| Proxy 360p perde detalhe | OCR e detalhes ruins | OCR só no master e só em regiões; resto no proxy |
| SigLIP/CLIP e RapidOCR brigam por CUDA/DLL | ambiente quebra | rodar em sequência como na 2B; se conflitar, processo separado (exceção da seção 5.2) |
| Contextos instáveis entre sessões | baseline por contexto ruim | contexto é por sessão; contexto pequeno cai para a baseline da sessão |
| Jogo de 1ª pessoa quase sem cortes de cena | detecção de cena pouco útil | foco nos sinais contínuos (movimento, estado de tela), não só nos cortes |
| Deriva para `if jogo == ...` | quebra a regra do produto | teste de plugabilidade e revisão no `/code-review` |

## Fluxo git

Branch `fase/3-video` para a 3A, PR para a `main` ao fim de cada sub-etapa (3A não depende de GPU nem do gabarito).
Commits pequenos por tarefa, Conventional Commits em pt-BR. `/code-review` antes de cada merge.

## Em aberto (precisa do criador)

1. Incluir `menu`, `loading`, `idle` (e `cinematica`) no gabarito, junto com as classes de áudio da Fase 2C.
2. Aprovar os números de corte da 3C.
3. Autorizar o download dos modelos novos (SigLIP/CLIP, RapidOCR, Qwen-VL; tamanho a registrar na 3B/3C).
4. Qual jogo servirá de **segundo gênero** para testar que o genérico funciona sem perfil (o gabarito pede dois gêneros).
5. Decidir como marcar `novo_dia` e os tipos com teclado de 60% (item 9 de "Em aberto" do plano; era "antes da Fase 3").
