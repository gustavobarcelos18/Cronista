# Histórico de decisões

Registro, em ordem, de cada pergunta feita durante o planejamento (2026-11-12) e da resposta ou decisão tomada.
O detalhe técnico de cada item está no [plano mestre](00-plano-mestre.md), na seção indicada.

> **Nota de leitura (2026-11-19, F20):** as seções são numeradas por ordem de inclusão e o número nunca muda (os outros
> documentos o citam). Por isso a data de uma seção pode ser anterior à da anterior (§59 é de 11-17 e vem depois do §58, de
> 11-18). As decisões da 3C ficam no §50A, separadas do B-roll (§50).

---

## 1. Ideia inicial

**Pedido:** criar uma aplicação que entenda do início ao fim as horas de gameplay gravadas, identifique o que é
interessante para o público e faça cortes automáticos, separando o que é legal de assistir do que é farm.
Precisa ser profissional, com arquitetura e organização, e a melhor forma de construir deve ser sugerida.

**Resposta:** o sistema combina vários sinais (voz, áudio do jogo, vídeo, contexto via LLM, marcadores manuais),
dá uma nota a cada trecho e monta a narrativa. Python no núcleo, FFmpeg, pipeline em etapas com cache, banco
SQLite/Postgres, interface de revisão e exportação para o editor. → Plano mestre, seções 1 e 5.

## 2. Respostas do criador ao questionário

| Pergunta | Resposta |
|---|---|
| Jogos | Jogos em geral: Minecraft, Valheim, Terraria, EA FC modo carreira, GTA V com mod, entre outros |
| Gravação | OBS, 1920×1080 a 60 fps; narra ao vivo algumas coisas; consegue gravar faixas separadas |
| Narração | Quer que o projeto também sugira narrações para ilustrar melhor cada momento |
| Duração do produto | Vídeo de 100 dias com 30 a 50 minutos |
| Hardware | RTX 3060 12 GB VRAM, 32 GB RAM, HD 2,5 TB, SSD 450 GB |
| Custo | Local e grátis se possível; usar o plano Claude Pro ou outra ferramenta integrada para melhor resultado; custo zero |
| Saída | Timeline pré-montada no DaVinci Resolve; Shorts para divulgar em outras plataformas |
| Roteiro | Somente o roteiro, nada de cara de IA; implementar uma skill no estilo do Humanizer do GitHub |
| O que é "legal" | Percepção pessoal: muitas mortes e falhas em desafios difíceis (mostrar o sofrimento), falhas como humor, mas o foco é o storytelling: piadas, conquistas, falhas, chefes derrotados, construções concluídas |
| Marcadores | Aceita apertar uma tecla para marcar |
| Criadores de referência | Baronismo, Xedou, Trousy, Promptz |
| Público do app | Só para o criador, mas estruturado para escalar no futuro |
| Linguagens conhecidas | C#, Python, Next.js, React, NestJS, JavaScript, TypeScript |
| Formato do plano | Versão completa, em grandes fases (ex.: 7); cada fase vira um plano de execução próprio, implementado de forma segura e calculada |

## 3. Ruído: teclas, respiração e pisadas

**Pergunta:** identificar teclas do teclado, respiração e a própria pisada do personagem (na grama é mais suave,
na pedra mais alta) seria um problema. Isso precisa ser pensado.

**Decisão:** volume absoluto não é usado como sinal. Quatro camadas: separação por faixa; no microfone, só a fala
conta (VAD + supressão de ruído); no jogo, classificar o tipo de som e medir a novidade em relação ao padrão da
sessão (sons rítmicos = farm); calibração por jogo com o feedback da revisão. → Seção 3.

> **Parcialmente substituído pelos §15 e §18.** A supressão de ruído (DeepFilterNet) só entra se melhorar o WER no
> benchmark (§18, risco 10), e a calibração por jogo virou perfil declarativo aprendido com o feedback, sobre um
> perfil genérico universal (§15).

## 4. Marcadores: início e fim, ou um toque só?

**Pergunta:** é preciso marcar o início e o final do acontecimento, ou só marcar para deixar claro que há algo ali?

**Decisão:** um toque basta. O sistema olha 60–90 s para trás e encontra os limites reais. Início e fim só para
construções (viram timelapse). Hotkeys opcionais por tipo e uma de "Início Dia N". → Seção 4.

> **Substituído pelos §14 e §20.** A hotkey de dia passou a ser obrigatória (§14) e hoje se chama `Novo dia`, sem
> número: grava só onde o dia começa, e o número é definido na edição (§20).

## 5. Quantas horas gravar

**Pergunta:** quantas horas de gravação são necessárias para ter com certeza 30–50 min de produto final?

**Decisão:** mirar 25 h (faixa de 20–35 h), pela compressão típica de 30:1 a 50:1. No Minecraft, 100 dias ≈ 33 h
reais (17–25 h pulando noites). A Fase 4 mede a taxa real. → Seção 2.

> **Atualizado pelos §15 e §19.** A conta passou a partir da duração do vídeo final, sem depender do relógio do
> Minecraft (§15), e a faixa de 20–35 h foi explicada como a faixa central de 15–42 h (§19, item 5).

## 6. Primeira versão do plano

**Decisão:** 7 fases (fundação, áudio, vídeo, relevância, narrativa, montagem, Studio). Usar o plano Pro via
Claude Code, porque o Pro não inclui API. Skill de humanização em português, calibrada pelas narrações
transcritas do criador. NestJS e C# ficaram de fora por enquanto, para evitar ponte entre linguagens. → Seção 7.

> **Atualizado pelos §10 e §13.** O plano tem hoje 9 fases: a Fase 8 (acabamento automático) entrou no §10 e a
> Fase 9 (embalagem e distribuição) no §13.

## 7. Como usar um modelo local do Ollama

**Pergunta:** como implementar um modelo local do Ollama? Na última vez que foi usado para code assist, não funcionou bem.

**Decisão:** o LLM local fica só com tarefas curtas e fechadas (rotular trecho, descrever frame), com saída em
JSON Schema, validação e nova tentativa. Interface `LLMProvider` trocável (Ollama, Claude Code, só heurística).
Um modelo por vez na GPU. A tarefa só fica no local se passar no benchmark contra o gabarito. → Seção 6.1.

## 8. Cenas cinematográficas e timelapse de construção

**Pergunta:** a IA consegue entender tomadas de câmera cinematográficas e registrar isso, por exemplo, numa timelapse de construção?

**Decisão:** a IA reconhece tomadas cinematográficas (movimento de câmera, HUD oculto, beleza visual, busca por texto)
e monta uma biblioteca de B-roll, mas não cria ângulos que não foram gravados. Timelapse de construção em três níveis:
automático, ponto de câmera fixo com a hotkey `Foto de progresso` (recomendado) e ferramenta do jogo (Replay Mod,
câmera livre, Rockstar Editor, replays). Nova hotkey `Cinemática`. → Seção 6.2.

## 9. Como a edição será feita

**Pergunta:** como a edição será feita?

**Decisão:** o app monta o primeiro corte (rough cut) e o acabamento fica no Resolve. Regras de montagem (corte na
ação, nunca no meio de uma palavra, remoção de silêncio, cortes J/L, farm em timelapse pré-renderizado), layout de
trilhas V1–V3 / A1–A4 + legendas, marcadores coloridos com sugestões de edição. Caminho de mão única. → Seção 6.3.

> **Layout de trilhas substituído pelo §21.** Hoje são V1–V5 / A1–A7: efeitos renderizados, overlays, SFX e stems
> crus ganharam trilha própria; B-roll passou para V3 e cartelas para V5.

## 10. VFX, zoom, cor e mixagem automáticos

**Pergunta:** não teria como adicionar VFX, zooms, ajuste de cores e mixagem automáticos?

**Decisão:** sim, com três modos por efeito (sugerir, aplicar editável, aplicar renderizado) e sempre reversível
(efeito renderizado numa trilha acima do original). Mixagem antecipada para a Fase 6; zoom, cor, música e VFX
(Remotion) na nova **Fase 8**. Regras contra "cara de template". → Seções 6.4 e 7.

## 11. O que o DaVinci Resolve gratuito aceita

**Pergunta:** verificar quanto o Resolve gratuito aceita / o que podemos fazer com ele.

**Situação:** a busca na web foi interrompida e o Resolve não estava instalado no PC do trabalho, então o levantamento
foi feito de memória, com nível de confiança. Pontos principais: importa timeline de arquivo; scripts rodam de dentro
do Resolve (externos provavelmente só no Studio); sem decodificação/codificação por GPU de H.264/HEVC no Windows.
Estratégia com Rota A (importar arquivo) e Rota B (script interno), efeitos animados renderizados pelo app e mídia
intermediária só dos trechos usados. **Pendente:** verificação prática no PC de casa. → Seção 6.5.

> **Parcialmente substituído pelos §16 e §17.** A pesquisa do criador confirmou que o gratuito não tem *encoding* por
> GPU. A *decodificação* por GPU não foi confirmada nem descartada: passou a ser item de teste no spike. O scripting
> externo também segue como teste, com o `README.txt` instalado com o Resolve como fonte oficial.

## 12. Documentação e repositório

**Pedido:** estruturar tudo em documento para retomar no PC de casa; depois, colocar no repositório e subir no GitHub;
por fim, atualizar os documentos sem retirar nenhuma informação conversada.

**Decisão:** o repositório git é a fonte de verdade (`docs/00-plano-mestre.md` + este histórico). O GitHub CLI não
estava instalado no PC do trabalho, então o repositório remoto precisa ser criado manualmente (ver README).
Um documento no claude.ai chegou a ser iniciado e ficou incompleto (4 de 8 seções); o repositório o substitui.

> **Resolvido.** O repositório remoto foi criado (https://github.com/gustavobarcelos18/Editor_De_Video) e integrado
> (commits `bf41e4f` e `32c1483`); o README traz o comando de clone.

## 13. Pendências antes da Fase 1

**Pergunta:** o que mais precisamos conversar? Foram levantados 12 pontos; respostas do criador e decisões:

| # | Tema | Resposta do criador | Decisão / impacto no plano |
|---|---|---|---|
| 1 | Jogo inicial, vozes, nome | Não será Minecraft: precisa ser universal. Só a própria voz. O nome não importa tanto | Perfil genérico universal como padrão; perfis por jogo opcionais e declarativos. Sem faixa de Discord. Nome "Cronista" mantido (seções 1, 5.3, Fase 3) |
| 2 | Gravações de teste | Não tem ainda; vai gravar ~30 min assim que possível | Fixtures sintéticas com FFmpeg até lá. Observação: a gameplay serve para **calibrar e testar**, não para treinar um modelo (seção 5.6) |
| 3 | Gabarito | Topa anotar, mas não agora | Fase 1 não depende do gabarito; ele é obrigatório a partir da Fase 2 |
| 4 | Onde programar | Código neste PC (trabalho); produção no PC de casa | Ambientes `dev` (sem GPU) e `prod` (RTX 3060) (seção 5.6) |
| 5 | Quando processar | A cada sessão de gravação; ajuda a saber quanto produto final já existe | Projeto incremental + painel da série (seção 4.1) |
| 6 | Ver o resultado no Resolve cedo | Não consegue configurar ou testar o Resolve agora | Esqueleto de ponta a ponta na Fase 1 com **prévia MP4 via FFmpeg** (não depende do Resolve) + FCPXML mínimo validado depois |
| 7 | Teclas dos marcadores | Tem uma mesa de som FIFINE SC3; dá para usar um botão dela? | Spike na Fase 1: evento HID/MIDI → marcador por áudio → alternativas (F13–F24, mouse, macropad) (seção 4) |
| 8 | Música e efeitos | Biblioteca de Áudio do YouTube ou gerada por IA; identidade visual e sonora é importante | Brand kit visual e sonoro; alerta de licença comercial para música de IA (seção 6.4) |
| 9 | Thumbnail e títulos | Quer sugestão de thumbnail; criar um modelo do canal para gerar identidade; decidir junto | Seção 6.7 + nova Fase 9; formato do modelo em aberto |
| 10 | Shorts | Todas as plataformas, edição genérica, prender em 3 s, **máximo 13 s** com começo, gancho e fim | Especificação na seção 6.6; candidatos na Fase 6, finalização na Fase 9 |
| 11 | Backup | Se funcionar, assinar nuvem ou montar NAS | `StorageBackend` trocável; backup imediato do que é pequeno; política de retenção (seção 5.6) |
| 12 | Fluxo git | Branch por fase, commits no nome dele, revisão com Opus, CI no GitHub Actions se necessário | Seção 5.6 |

## 14. Revisão do plano: dúvidas levantadas pelo Claude

| # | Dúvida | Resposta do criador | Decisão / impacto no plano |
|---|---|---|---|
| 1 | O que é "dia" em jogos sem dia (EA FC, GTA V)? | O dia é fictício, só define progresso e passagem de tempo | Hotkey `Início Dia N` passa a ser obrigatória e é a fonte universal de capítulos (seção 4) |
| 2 | Fala ao vivo × roteiro | A fala ao vivo é preferida (reação espontânea); o roteiro complementa explicando o que foi feito, as decisões, o porquê, o que vem a seguir e o que ele pensava | Roteiro só nos espaços sem fala ao vivo; story-pack inclui a fala ao vivo transcrita (seções 6 e 6.3) |
| 3 | MKV ou Hybrid MP4? | Hybrid MP4 | Seção 2 |
| 4 | Pausa/divisão de arquivo no OBS quebram o tempo dos marcadores | Perguntou como resolver | Capítulo no arquivo (tempo de mídia) como fonte primária + diário de eventos com pausas e trocas de arquivo, reconciliados na ingestão; testes com fixtures (seção 4) |
| 5 | Usa facecam? | Não | Shorts e thumbnails só com gameplay (seções 6.6 e 6.7) |

> **Item 1 atualizado pelo §20:** a hotkey obrigatória hoje se chama `Novo dia` e não carrega número.
>
> **Item 4 atualizado pelo §18 (risco 4):** "capítulo no arquivo" passou a se chamar "marcador do OBS".

## 15. Ajustes de consistência

**Pedido:** reforçar que o sistema precisa ser universal, corrigir a ordem das seções e criar o `CLAUDE.md`.
A verificação do Resolve gratuito fica com o criador, que vai pesquisar e trazer o resultado.

**Decisão:** removidas as menções a calibração/adaptadores por jogo no núcleo (seções 2, 3, 4, 5.5, Fase 7 e riscos):
o perfil genérico é o padrão, perfis de jogo são YAML aprendidos com o feedback, e `adapters/` fica só para leitores
de mods opcionais. A conta de horas da seção 2 passou a partir do vídeo final (~15 min de gravação por "dia"), sem
depender do relógio do Minecraft. Seção 6.5 movida para antes da 6.6. Criado o `CLAUDE.md` com as regras que não se negociam.

## 16. Pesquisa do Resolve gratuito e referência do humanizador

**Entrada do criador:** pesquisa "Limitações do DaVinci Resolve gratuito (v19/20)" e o link do Humanizer
(https://github.com/blader/humanizer) como base da skill de humanização.

**Decisões:**
- Resolve: confirmados saída até UHD 60 fps sem marca d'água, Fairlight e Fusion completos, sem encoding por GPU,
  formatos 10-bit/HDR mal suportados, recursos de IA e vários FX só no Studio (e com marca d'água se usados no gratuito).
  → OBS grava H.264 8-bit SDR (seção 2); app nunca usa recurso do Studio; render final com duas rotas a medir
  (CPU no Resolve ou intermediário + NVENC pelo app). FCPXML, API de scripts, decodificação por GPU e HEVC continuam
  para o spike (seção 6.5).
- Humanizador: a skill `/humanizar` adapta o Humanizer (MIT, baseado no guia da Wikipédia sobre sinais de texto de IA):
  mantém o fluxo auditar → rascunhar → conferir → finalizar, seleciona os padrões que valem para fala, descarta os de
  formatação e acrescenta padrões de pt-BR falado; a amostra de voz são as narrações ao vivo do criador (seção 6).

## 17. Como verificar o que falta no Resolve gratuito

**Entrada do criador:** documento "DaVinci Resolve gratuito: pendente de teste", com quatro pontos que a pesquisa não
cobriu (importação de FCPXML, scripting externo no gratuito, decodificação por GPU, HEVC no Windows) e o aviso de
que FCPXML e scripting quase não aparecem nos comparativos free × Studio.

**Decisão:** teste prático, com a documentação oficial como preparação. Fonte da API de scripts = `README.txt`
instalado com o Resolve (versão exata). O kit de teste (FCPXML, script interno, clipes H.264/HEVC 8-bit, roteiro de
checagem) entra como tarefa da Fase 1 e roda no PC de casa. → Seções 6.5 e 7 (Fase 1).

## 18. Revisão do plano: inconsistências e riscos técnicos

**Pedido:** analisar o projeto e os documentos em busca de falhas, dúvidas, pontos em aberto e melhorias.

**Inconsistências corrigidas:**

| # | Ponto levantado | Resposta do criador | Decisão / impacto no plano |
|---|---|---|---|
| 1 | Diagrama da seção 5.1 mostrava gravação em `.mkv` | Alterar para Hybrid MP4 | Diagrama corrigido |
| 2 | "Render final fora de escopo" contradizia `cronista render`, efeitos renderizados e Shorts finalizados | Reescrever | Fora de escopo passa a ser "substituir o Resolve como editor"; o app pode codificar quando é só execução (seção 1) |
| 3 | Ambiguidade: um vídeo de 30–50 min ou episódios semanais? | Um vídeo só de 30–50 min, feito a partir de várias horas de gameplay em sessões de 3 h, 6 h, 10 h etc. | Produto = um vídeo por série; sessões de duração variável; um dia pode atravessar sessões; "episódio" trocado por "vídeo" (seções 0.1, 1, 2, 4.1, 5.4, 5.6, 6.5, Fases 7–9) |
| 4 | Nomes das skills diferentes na seção 5.5 | Corrigir | `/roteirizar` e `/humanizar`; perfil de voz é guia de estilo usado por elas |
| 5 | §11 deste histórico não marcado como substituído | Conferir | Nota de substituição parcial adicionada ao §11 |
| 6 | `.gitignore` ignoraria assets do brand kit, o `.env.example` e não separava config local | Corrigir | Exceção para `packages/brand-kit/`, `!.env.example`, `config/*.local.yaml` e `.claude/settings.local.json` ignorados; `dev.yaml`/`prod.yaml` versionados sem caminhos pessoais (seção 5.6) |

**Riscos técnicos corrigidos** (pedido: "corrija os riscos técnicos; se houver dúvida, me faça pergunta"):

| # | Risco | Resposta do criador | Decisão / impacto no plano |
|---|---|---|---|
| 1 | No OBS o filtro vale para a fonte, não para a faixa: RNNoise "só no mix" não funciona com uma fonte só | — | Microfone em duas fontes: com RNNoise → faixa 1; sem filtro → faixa 3 (seção 2) |
| 2 | FCPXML não carrega cor de marcador | — | Cor via EDL de marcadores do Resolve ou script interno; item do spike (seções 6.3, 6.5, Fase 6) |
| 3 | Não se sabe se o FCPXML mapeia faixa 2 → A1 e faixa 3 → A2 | — | Item do spike; alternativa com WAVs extraídos (seções 6.3, 6.5) |
| 4 | Script Python no OBS exige Python específico e talvez não exponha a função de marcador | Perguntou se não pode usar os marcadores do OBS; esclareceu que o marcador serve para indicar que algo aconteceu, não para definir capítulo | Os marcadores **são** os do OBS (o Hybrid MP4 os chama tecnicamente de "capítulo", mas não cria capítulo no vídeo). Termo trocado para "marcador do OBS". Quem cria o marcador com tipo e dia fica em aberto: A (obs-websocket, recomendada), B (Lua), C (hotkey nativa) (seção 4 e seção 9) |
| 5 | Hotkeys não chegam a jogos rodando como administrador ou com anti-cheat | — | Rodar como administrador ou usar dispositivo físico; verificar no PC de casa (seção 4) |
| 6 | Hybrid MP4 interrompido fica fragmentado | — | Remux sem recodificar na ingestão; item do spike (seções 2, 6.5, Fase 1) |
| 7 | 60 × 59,94 fps causa deriva nos cortes | 60 fps exatos | Gravação, timeline, timelapses e cartelas em 60 fps (seções 2, 6.3) |
| 8 | Navegador toca só a primeira faixa de áudio | — | Proxy H.264 + AAC com uma faixa e `faststart`; waveform a partir dos WAVs (Fase 1) |
| 9 | OCR ilegível no proxy 360p | — | OCR em frames do master (seção 5.2, Fase 3) |
| 10 | PaddleOCR e DeepFilterNet arriscados no Windows/Python 3.12 | RapidOCR + teste | ML em PyTorch + ONNX Runtime; OCR com RapidOCR; DeepFilterNet só se melhorar o WER no benchmark (seções 3, 5.2, Fases 1–3) |
| 11 | Processamento disputa a GPU com o jogo | Automático, com pausa | Começa ao fim da gravação e pausa com o OBS gravando ou jogo em tela cheia (seção 4.1) |
| 12 | CI só em Linux, produção em Windows | — | CI em Ubuntu e Windows (seção 5.6) |

> **Risco 4 resolvido pelo §20:** quem cria o marcador = opção A (obs-websocket), e o marcador não leva mais o dia.
>
> **Risco 10 complementado pelo §21:** o CTranslate2 do faster-whisper é exceção aceita à regra PyTorch + ONNX Runtime.

**Dias na tela:** o criador informou que a contagem de dias aparece na tela, mas que isso é decidido na hora da
edição. → `Início Dia N` passa a ser uma proposta de divisão; o número final é ajustado no Studio ou no Resolve;
cartelas e contador de dias saem editáveis (título Text+/Fusion ou regenerados pelo app), com item no spike
(seções 4, 6.3, 6.5). Contador de dias por projeto, persistido entre sessões; sem tecla de correção.

> **Parcialmente substituído pelo §20:** não há contador de dias na gravação; `Início Dia N` virou `Novo dia`, sem
> número. Continua valendo: a divisão é proposta, o número é da edição e as cartelas saem editáveis.

As demais perguntas e sugestões da revisão (Fase 1.5 com rough cut só de marcadores, divisão da Fase 1, contratos via OpenAPI,
gabarito com dois gêneros, critérios de aceite numéricos, backup na Fase 1, retenção × relink, política do PC do
trabalho, termos do `claude -p`, licenças do Remotion/modelos, macros do Fusion) foram apresentados como sugestões e
**ainda não foram decididos**. Desde o §21, estão listadas no item 7 das decisões em aberto do plano mestre (seção 9).

## 19. Segunda revisão: inconsistências restantes

**Pedido:** analisar o projeto e os documentos em busca de erros, dúvidas e melhorias pontuais (melhoria não é
obrigatória e não pode mudar o projeto todo). O criador aprovou a correção das inconsistências.

| # | Inconsistência | Decisão / impacto no plano |
|---|---|---|
| 1 | Mixagem citava "EBU R128 (−14 LUFS)", mas o alvo da EBU R128 é −23 LUFS; −14 LUFS é o alvo do YouTube | Texto corrigido: −14 LUFS integrado (alvo do YouTube), medido pelo método ITU-R BS.1770/EBU R128 (seção 6.4) |
| 2 | Benchmark "contra o gabarito" e WER na Fase 1 contradiziam "a Fase 1 não depende do gabarito" (WER exige transcrição de referência) | Fase 1 mede só desempenho (velocidade, VRAM); WER com/sem DeepFilterNet vira a primeira tarefa da Fase 2; precisão das tarefas do LLM local medida contra o gabarito (seções 3, 6.1, Fases 1 e 2, seção 9) |
| 3 | "Fallback com LLM local" para o roteiro contradizia a regra de LLM local só em tarefas curtas e fechadas | Fallback = `NullProvider`: sem roteiro escrito, só marcadores com contexto (Fase 5, seção 9) |
| 4 | Diagrama da seção 5.1 mostrava "Adaptador do Jogo" como etapa fixa, contra a decisão do §15 | Etapa renomeada para "Perfil Jogo (opc.)" |
| 5 | Faixa "20–35 h" não saía da conta 30:1–50:1 (que dá 15–42 h) | Tabela da seção 2 explica: 20–35 h na faixa central (~40:1), 15–42 h nos extremos. Meta de 25 h mantida |
| 6 | §12 deste histórico ainda dizia que o repositório remoto precisava ser criado | Nota de "resolvido" adicionada ao §12 |

**Dúvidas levantadas** (respondidas logo abaixo): onde ficam as skills `criar-plano`/`implementar-plano` (não estão no
repositório); como cumprir o aceite "ingerir 10 h" na Fase 1 sem gravação longa (fixture sintética?); se os marcadores
do OBS sobrevivem a uma gravação interrompida (item para o spike); onde ficam os WAVs extraídos (~0,7 GB/h por faixa)
e qual faixa vai no proxy.

**Respostas do criador às dúvidas:**

| # | Dúvida | Resposta do criador | Decisão / impacto no plano |
|---|---|---|---|
| 1 | Onde ficam as skills `criar-plano`/`implementar-plano`? | Não sabe responder | Não existem no PC do trabalho nem no repositório (provavelmente vieram de outra máquina). As referências foram retiradas: os planos de fase são escritos direto em `docs/fase-N-*.md`, sem depender de skill externa (`CLAUDE.md`, seção 0). Se aparecerem, podem ser versionadas em `.claude/skills/` |
| 2 | Como cumprir o aceite "ingerir 10 h" na Fase 1? | O critério está errado: qualquer hora de gameplay é válida | Aceite da Fase 1 sem mínimo de horas: ingerir sem intervenção uma gravação de qualquer duração (Fase 1, seção 9) |
| 3 | Os marcadores do OBS sobrevivem a uma gravação interrompida? | Não faz ideia | Item novo no checklist do spike: `ffprobe -show_chapters` antes e depois do remux; se não sobreviverem, o diário é a única fonte nesse caso (seção 6.5) |
| 4 | Onde ficam os WAVs extraídos e qual faixa vai no proxy? | Provavelmente ficam no vídeo | O áudio original fica sempre dentro do vídeo (master com as três faixas). Os WAVs são cópias de trabalho da análise: cache no SSD, regeneráveis do master; vão para o HD só se o spike exigir WAVs na timeline. O proxy toca o mix (faixa 1), só para ouvir (seção 2, Fase 1, seção 9) |

**Sugestões apresentadas, não decididas:** faixa 2 com "Captura de áudio de aplicativo" no OBS; importar o teste
também como `.otio` no spike; pausar o processamento pelo uso da GPU em vez de detectar tela cheia. Desde o §21,
estão no item 7 das decisões em aberto (seção 9 do plano mestre).

## 20. Quem cria o marcador e o número do dia

**Pergunta:** qual opção cria o marcador com tipo no OBS (A, programa ao lado do OBS via obs-websocket; B, script Lua;
C, só a hotkey nativa)? E a tecla de construção é uma só ou são duas?

**Resposta do criador:** opção A. Mas o programa não tem como saber o número do dia, porque esse número é o da
edição, e não o de quanto ele jogou. Sobre a construção: `▶/■` é só uma forma de escrever.

**Decisão:**
- Gravador de marcadores = **opção A** (seção 4, Fase 1, seção 9).
- **Sem contador de dias na gravação.** Substitui o "contador de dias por projeto, persistido entre sessões" do §18.
  A hotkey `Início Dia N` passa a se chamar `Novo dia` e grava só onde o dia começa, sem número. O nome do marcador
  passa de `tipo|dia|id` para `tipo|id`. O número de cada dia é definido na edição (Studio ou Resolve). Uma sessão que
  começa sem `Novo dia` continua o dia anterior (seções 2, 4, 5.4, Fase 1, seção 9 e `CLAUDE.md`).
- `Construção ▶/■` é uma tecla só, que alterna; o programa da opção A sabe se há uma construção aberta (seção 4).

## 21. Terceira revisão: inconsistências e dúvidas

**Pedido:** analisar o projeto e os documentos em busca de dúvidas ou erros aparentes. O criador aprovou a correção
das inconsistências.

| # | Inconsistência | Decisão / impacto no plano |
|---|---|---|
| 1 | O modelo de domínio (seção 5.4) ainda mostrava `Marcador (tipo, t, dia)`, contra o §20 | Marcador = `tipo, t, id`; o dia de cada trecho sai da posição dos `Novo dia` |
| 2 | A estrutura do repositório (seção 5.5) dizia "mecanismo em aberto" para o gravador de marcadores | Texto trocado para opção A via obs-websocket |
| 3 | O faster-whisper roda sobre o CTranslate2, que traz CUDA próprio, contra a regra "só PyTorch + ONNX Runtime" (§18, risco 10) | Exceção aceita e documentada; ⚠️ conferir na Fase 1 se as versões de cuBLAS/cuDNN convivem com as do PyTorch; se não, transcrição em processo separado (seções 5.2, 8 e 9) |
| 4 | A seção 6.4 põe efeitos renderizados "numa trilha acima do original", stems crus "abaixo" e overlays do Remotion, mas o layout da seção 6.3 só tinha V1–V3 / A1–A4 | Layout novo: V1 gameplay, V2 efeitos renderizados, V3 B-roll, V4 overlays, V5 cartelas (sempre por cima); A1 jogo, A2 voz ao vivo, A3 narração complementar, A4 música, A5 SFX, A6/A7 stems crus desativados (seções 6.3 e 9) |
| 5 | Itens do histórico substituídos por decisões posteriores sem nota (§3, §4, §6, §9, §14, §18) | Notas de substituição/atualização adicionadas |
| 6 | Sugestões não decididas dos §18 e §19 não apareciam na seção 9, que é onde a retomada procura o que está em aberto | Listadas no item 7 das decisões em aberto |

**Dúvidas levantadas, ainda sem resposta** (registradas no item 8 das decisões em aberto, seção 9):
- Primeira sessão do projeto sem `Novo dia`: abre o primeiro dia implicitamente?
- `Construção ▶` sem `■` é fechada no fim da sessão, mas um dia pode atravessar sessões: a construção também deveria?
- Fala ao vivo durante um farm que vira timelapse: descartar, cortar normal ou manter por cima?
- Critérios de aceite sem número nas Fases 2, 3 e 4.
- Fases 7 e 9 dependem de uma série inteira gravada e de um vídeo publicado.
- ⚠️ De memória: Voice Isolation (e talvez Dialogue Leveler) do Fairlight seriam exclusivos do Studio.
- Cópia do `README.txt` do Resolve em `docs/referencias/` num repositório público.

## 22. Quarta revisão: inconsistências e dúvidas

**Pedido:** analisar o projeto e os documentos em busca de dúvidas ou erros aparentes. O criador aprovou a correção
das inconsistências e o registro das dúvidas.

| # | Inconsistência | Decisão / impacto no plano |
|---|---|---|
| 1 | O remux da gravação interrompida usava `ffmpeg -c copy`; sem `-map 0` o FFmpeg copia só uma faixa de áudio e perde as faixas 2 e 3 | Comando passa a ser `ffmpeg -map 0 -c copy`; o spike confere as três faixas depois do remux (seções 2, 6.5, Fase 1) |
| 2 | A linha de base do áudio do jogo era "por contexto visual", mas o contexto só existe depois dos embeddings da Fase 3, e o áudio é a Fase 2 | Fase 2 calcula a linha de base por sessão; a Fase 3 acrescenta o recorte por contexto visual e recalcula só a novidade (seção 3, Fases 2 e 3) |
| 3 | No microfone, "só a fala conta" (o VAD descarta o resto), mas risada e grito eram sinais, e o VAD costuma tratá-los como não-fala | O classificador de eventos sonoros roda também no microfone, só para risada e grito; o VAD decide o que vai para a transcrição (seção 3, Fase 2) |
| 4 | "A falta do DeepFilterNet não bloqueia nada" só valia para a transcrição: a faixa 3 crua vira a trilha A2, e a cadeia de voz precisa de redução de ruído | A redução de ruído da mixagem não depende do benchmark de WER: DeepFilterNet, se instalar, ou filtros do FFmpeg (⚠️ de memória: `arnndn`, `afftdn`), escolhidos na Fase 6 (seções 5.2, 6.4, Fase 6) |
| 5 | O ducking pronto no stem de A1 só considerava a fala ao vivo; a narração complementar (A3) é gravada depois, e ali o jogo ficaria em volume cheio | O stem de A1 também é abaixado nos trechos em que o roteiro prevê narração; desfaz-se com o stem cru (A6). ⚠️ A confirmar com o criador (seção 6.4, Fase 6, seção 9 item 9) |
| 6 | −14 LUFS era aplicado aos stems, mas é alvo da mixagem final (com narração, música e SFX somados) | Stems nivelados entre si; o loudness integrado é medido e ajustado no render final, no Resolve ou no `cronista render` (seção 6.4, Fase 6) |
| 7 | O `.gitignore` ignora `*.mp4`/`*.mov`/`*.wav` em todo o repositório, o que pega os clipes do kit de teste do Resolve e as fixtures de vídeo de `tests/` | Clipes do kit e fixtures sintéticas são gerados por script em cada máquina; exceção no `.gitignore` para amostras reais pequenas em `services/engine/tests/fixtures/` (seção 9) |

**Lacunas menores corrigidas:**
- Checklist do PC de casa (seção 0): OBS 30.2+ (⚠️ de memória) e servidor obs-websocket ativado.
- Checklist do spike (seção 6.5): marcadores do OBS lidos pelo `ffprobe` numa gravação normal, overlay com canal alfa,
  clipes/trilhas desativados via FCPXML, importação do SRT e exportação em ProRes no Windows.
- Rota do intermediário (seção 6.5): ⚠️ de memória, o Resolve no Windows não exporta ProRes; padrão DNxHR até o spike.

**Dúvidas levantadas, ainda sem resposta** (registradas no item 9 das decisões em aberto, seção 9):
- Para que serve o mix com RNNoise, se a análise e a timeline não usam a faixa 1? Uma fonte única de microfone bastaria?
- Como o criador sabe que o toque foi registrado com o jogo em tela cheia (principalmente a tecla de construção, que
  alterna)? E se o programa de marcadores não estiver aberto?
- Marcador que existe só no arquivo e não no diário: qual é a regra da reconciliação?
- `Cinemática` e `Foto de progresso`: a tomada é antes ou depois do toque?
- Ducking sob a narração complementar: pré-aplicado pelo app (padrão atual) ou deixado para o Fairlight?
- Métricas de ritmo dos criadores de referência: origem dos arquivos de vídeo e fase em que entram.
- Itens sem fase definida: `cronista render`, mídia intermediária DNxHR, métricas de ritmo, `StorageBackend` e
  política de retenção.

## 23. Quarta revisão: pontos menores

**Pedido:** "algo mais para ser corrigido?". Foram apresentados seis pontos menores; o criador aprovou a correção.

| # | Inconsistência | Decisão / impacto no plano |
|---|---|---|
| 1 | A opção 2 das cartelas (PNG/MOV regenerado "depois do ajuste dos dias no Studio") não funciona na Fase 6, porque o Studio só chega na Fase 7 | Na Fase 6 vale o título editável (opção 1); se o spike reprovar, os números vêm de um arquivo de dias do projeto, editado à mão (seções 6.3 e 9) |
| 2 | A seção 5.5 listava "ADRs" em `docs/`, mas as decisões vão para este histórico e ADR não aparece em mais nenhum lugar | Texto trocado para "este plano + histórico de decisões + planos por fase" |
| 3 | A árvore da seção 5.5 começava em `cronista/`, e o repositório se chama `Editor_De_Video` | Raiz corrigida; `cronista` é o nome do pacote Python |

**Dúvidas levantadas, ainda sem resposta** (acrescentadas ao item 9 das decisões em aberto, seção 9):
- Direção dos contratos: JSON Schema → Pydantic (seção 5.2) ou Pydantic → JSON Schema (exemplo da 6.1)? Decidir junto
  com a sugestão de OpenAPI.
- Marcador por áudio da FIFINE: o som do pad na faixa do microfone iria para a trilha A2 do vídeo final.
- Ferramenta de anotação do gabarito na Fase 1: o que é, se o Studio só chega na Fase 7?

## 24. Quinta revisão: inconsistências e dúvidas

**Pedido:** analisar o projeto e os documentos em busca de dúvidas ou erros aparentes. O criador aprovou a correção
das inconsistências e o registro das dúvidas.

| # | Inconsistência | Decisão / impacto no plano |
|---|---|---|
| 1 | Os WAVs iriam para o HD "só se o spike exigir", mas os stems processados de A1/A2 (Fase 6) não cabem no MP4 e são sempre WAVs | Stems processados sempre em WAV, no HD (`exports`); o teste de faixas embutidas do spike vale só para as faixas cruas (seções 2, 6.3 e 9) |
| 2 | "Trilhas sem conteúdo numa fase não são criadas" contradizia A3 e A4 "vazias" e deslocaria a numeração | Numeração fixa: trilhas sem conteúdo são criadas vazias; só A6/A7 são condicionais. ⚠️ FCPXML usa "lanes": item novo no spike (seções 6.3 e 6.5) |
| 3 | "O perfil é aprendido, não escrito à mão" contradizia o lookback "ajustável no perfil" e as regiões de HUD "definidas no perfil" | Pesos aprendidos + campos manuais opcionais (HUD, lookback, rótulos ignorados) (seção 3) |
| 4 | Cartelas: título editável na Fase 6 (seção 6.3) × "cartelas de dia" como template Remotion (seção 6.4, Fase 8); a lista da Fase 6 não citava cartelas nem B-roll | Cartelas Remotion = opção 2 (regeneradas pelo app, sem número fixo); título editável continua; Fase 6 passa a citar cartelas e B-roll (seções 6.3, Fases 6 e 8) |
| 5 | "Dois caminhos independentes" para o marcador, mas na opção A o mesmo programa faz os dois | Texto trocado para "dois registros separados"; a redundância não cobre a falha do programa (seção 4) |
| 6 | A exceção `!services/engine/tests/fixtures/**` do `.gitignore` versionaria fixtures sintéticas geradas ali, contra o §22 | Fixtures geradas vão para `data/fixtures/`; a pasta de `tests/` guarda só amostras reais pequenas (seções 5.6 e 9, `.gitignore`) |
| 7 | Pontos de texto: "nessa mesma gravação interrompida" depois do item da gravação normal; "avisa (ou converte)" × "converte" para 10-bit; "o app não chama o Claude" × `ClaudeCodeProvider`; §5 sem nota de atualização; beats da seção 5.4 × arco da Fase 5; intermediário DNxHR SQ "dezenas de GB" | Checklist reescrito; 10-bit = avisa e converte; "nunca chama a API do Claude"; nota no §5; Fase 5 usa os beats da 5.4; intermediário ~65–110 GB (⚠️ de memória) (seções 1, 2, 6.5, Fase 5) |

**Conferido:** o Humanizer lista mesmo 26 padrões (README do repositório, 2026-11-12).

**Itens novos no checklist do spike (seção 6.5):** trilhas em que o Resolve põe os clipes do FCPXML e criação de
trilhas vazias; FCPXML de teste gerado pelo caminho OTIO → FCPXML; script interno sem janela própria.

**Dúvidas levantadas, ainda sem resposta** (registradas no item 10 das decisões em aberto, seção 9):
- O adaptador FCPXML do OTIO dá conta, ou o app escreve o FCPXML direto?
- O FCPXML garante o layout de trilhas e cria trilhas vazias?
- O script interno funciona no gratuito recente sem interface gráfica?
- Timelapse de farm fica mudo na Fase 6, até a música chegar na Fase 8?
- Shorts 9:16 a partir de 1080p: recorte de 608 px ampliado ~1,8×.
- Quem dispara o processamento automático, e em que linguagem é o gravador de marcadores?
- Stems processados: sessão inteira ou só os trechos usados?

## 25. Como começar: divisão da Fase 1

**Pergunta do criador:** o que podemos fazer para começar a desenvolver o projeto?

**Resposta do Claude:** o projeto só tem planejamento; o próximo passo é detalhar a Fase 1. Como ela está grande
demais (sugestão do §18, item 7), propôs dividi-la em 1A (esqueleto e ingestão, roda no PC do trabalho), 1B (marcadores
e prévia) e 1C (itens do PC de casa: kit do Resolve, FIFINE, guia do OBS, benchmark).

**Decisão:** o criador aprovou a divisão ("Sim, dividir"). Criado [fase-1-fundacao.md](fase-1-fundacao.md) com tarefas,
critérios de aceite e testes por sub-etapa. O aceite da Fase 1 equivale a 1A + 1B; a 1C bloqueia a Fase 2 e o spike do
Resolve antes da Fase 6. Plano mestre atualizado (Fase 1 e seção 9).

**Propostas ainda não confirmadas** (D1–D4 no plano da fase, listadas no item 7 da seção 9): gravador de marcadores em
Python e disparo do processamento pelo engine; contratos Pydantic → JSON Schema/OpenAPI → TypeScript (inverte o texto
da seção 5.2); gabarito em CSV; sem Fase 1.5. Também propostos, a confirmar: marcador que só existe no arquivo vira
`Momento` com aviso; primeira sessão sem `Novo dia` abre um dia implícito.

## 26. Confirmação das propostas D1–D4

**Resposta do criador:** "Confirmo todas" (as propostas D1–D4 do §25, mais os dois pontos de reconciliação).

**Decisão:**
- **D1:** gravador de marcadores em Python; o engine dispara o processamento ao observar `recording_stopped`.
- **D2:** contratos Pydantic → JSON Schema/OpenAPI → TypeScript. **Substitui** "JSON Schema → Pydantic" da seção 5.2.
- **D3:** gabarito em CSV com script de validação.
- **D4:** sem Fase 1.5; a prévia MP4 da 1B cumpre o papel.
- Marcador só no arquivo = `Momento` com aviso; primeira sessão sem `Novo dia` abre um dia implícito.
- Itens dos §21–§24 respondidos por isso: dia implícito, marcador só no arquivo, direção dos contratos, ferramenta do
  gabarito, disparo do processamento e linguagem do gravador.

## 27. Correção na 1A: WAV acima de 4 GB

**Contexto:** uma sessão do PC do trabalho implementou em paralelo outra versão da Fase 1, sobre uma cópia
desatualizada do repositório (sem os §19–§26). O criador escolheu manter esta branch como base; a outra versão ficou
só na branch local `backup/fase-1-versao-alternativa` (não enviada), como material de partida da 1B. Dela veio esta
correção, aprovada pelo criador.

**Problema:** o WAV comum tem cabeçalho de 32 bits e para em 4 GB. Uma faixa estéreo 48 kHz 16-bit (~0,7 GB/h) passa
disso com ~6,2 h de gravação, e as sessões podem ter 10 h. Verificado com FFmpeg 9.0.2 em 2026-11-15: num WAV de
4,6 GB sem RF64 o FFmpeg avisa que "output file will be broken".

**Decisão:** a etapa `audio` grava com `-rf64 auto` (RF64 só acima do limite; abaixo continua WAV comum) e extrai jogo
e microfone numa leitura só do master. A versão da etapa subiu para 2, o que invalida o cache dos WAVs já gerados
(seção 2).

## 28. Início da 1B: marcadores como passo da sessão

**Contexto:** a 1B começou pelo diário `.markers.jsonl`, a reconstrução do tempo de mídia, a reconciliação e a
ingestão de marcadores (tarefas 1, 2 e 4 do plano da 1B). Ficam para as próximas partes: gravador (opção A), prévia
MP4, FCPXML mínimo e o `GpuGate` real.

**Decisões de implementação:**
- A ingestão de marcadores **não é uma etapa com cache por arquivo**, e sim um passo idempotente da sessão
  (`ingest/markers.py`). O diário pertence à sessão e cresce entre ingestões, e a chave de cache do orquestrador só
  enxerga o arquivo de mídia; ler capítulos é barato. Cada ingestão refaz as linhas `marker` da sessão (reingerir
  não duplica).
- `Construção ▶/■` é pareada pela ordem dos toques (ímpar abre, par fecha), atravessando arquivos da mesma sessão;
  coluna nova `marker.phase` (`start`/`end`, migração 0002). Aberta no fim da sessão: cria um `■` sintético
  (`<id>-fim`, `source=synthetic`) no fim do último arquivo, com aviso.
- O dia implícito é um marcador `novo_dia` sintético (`dia-implicito`, tempo 0) criado só se nem esta sessão nem
  uma sessão anterior do projeto tem `Novo dia`.
- Marcador só no arquivo vira `Momento` mesmo que o título seja `tipo|id` válido (decisão do §26 mantida); o título
  original vai no aviso.
- Toque durante pausa fica no ponto onde a gravação parou, com aviso.
- O diário é reaberto sem corromper: se a última linha ficou cortada, o escritor começa com uma quebra de linha.

**Verificado com o OBS real (2026-11-16, OBS em pt-BR, arquivo finalizado):** `ffprobe -show_chapters` traz um capítulo
inicial em 0 s ("Iniciar", título traduzido), os toques da hotkey nativa ("Sem nome 1", "Sem nome 2") nos tempos
corretos e um capítulo final "Dummy" que só fecha o último intervalo. Os capítulos do OBS são contíguos (fim de um =
início do próximo). A ingestão descarta o inicial (reconhecido pela posição: primeiro, em 0 s, sem `tipo|id`, já que
o título muda com o idioma) e o "Dummy" (`drop_obs_bookends`); sem isso todo arquivo ganharia um `Momento` falso
em 0 s. O primeiro capítulo em 0 s, que eu tinha tomado por artefato do muxer do FFmpeg, é na verdade o
capítulo inicial do próprio OBS; os tempos dos toques reais não sofrem esse deslocamento. **Ainda por verificar:**
nome com `tipo|id` via `CreateRecordChapter`, e se os capítulos sobrevivem a uma gravação interrompida/ao remux.

## 29. 1B: prévia MP4 (`cronista preview`)

Segundo item da ordem da 1B (§28). Decisões de implementação, todas dentro do que o plano da fase já previa:

- `cronista preview <sessão>` (número da sessão, como em `cronista status`) gera `data/previews/sessao-N.mp4`
  (ou `--out`). Um trecho por marcador, na ordem (arquivo, tempo): 20 s antes e 10 s depois (`preview_pre_s`,
  `preview_post_s` na config), recortado aos limites do arquivo. Marcador fora do arquivo ou com trecho < 0,5 s
  fica de fora com aviso.
- Janelas que se sobrepõem **não são fundidas**: o critério de aceite pede N trechos para N marcadores. Se isso
  cansar na revisão (marcadores colados repetem imagem), fundir é uma mudança pequena em `domain/preview.py`.
- Saída em 1080p60 H.264 yuv420p, áudio só do mix (faixa 1). Encoder por config: `libx264` em `dev` (CPU),
  `h264_nvenc` em `prod`; só o NVENC espera a `GpuGate`. Os parâmetros do NVENC (`-preset p5 -rc vbr -cq`)
  ⚠️ vêm de memória, não foram testados sem GPU: conferir na 1C.
- Corte por trecho (`-ss` antes do `-i`, recodificando) e concatenação sem recodificar (`concat` + `-c copy`).
  Lê o master já normalizado (remuxado/8-bit) pelo artefato da etapa `normalize`; sessão não ingerida dá erro claro.
- Não é etapa do orquestrador (sem cache): é barato de refazer e depende do conjunto de marcadores da sessão, que
  muda a cada ingestão. A pasta de trabalho é apagada ao fim.

## 30. 1B: FCPXML mínimo via OTIO (`cronista export`)

Terceiro item da ordem da 1B. Primeira medição do adaptador FCPXML do OTIO (pendência da seção 9, item 10).

- Dependências: `opentimelineio` 0.18.1 e `otio-fcpx-xml-adapter` 1.0.0 (o adaptador é um pacote à parte, como o
  plano supunha). Instalam e funcionam em Python 3.12 no Windows.
- `cronista export <sessão>` grava `data/export/sessao-N.fcpxml` e `.otio` (o Resolve recente importa OTIO,
  ⚠️ a conferir na 1C). Mesmos trechos da prévia (módulo `montage.py`, compartilhado): um clipe por marcador.
- **Layout:** V1 = master normalizado; A1 = WAV do jogo (faixa 2); A2 = WAV do microfone (faixa 3). Decisão: a OTIO
  não consegue dizer "faixa 2 do MP4", então o mínimo já usa os WAVs que a ingestão extrai, que é o plano B previsto
  na seção 6.3. O teste "o Resolve respeita a faixa embutida?" fica para quando o app precisar das faixas cruas.
  O mix (faixa 1) não entra: A1/A2 são os stems.
- Tempos: quadros inteiros de 1/60 s (`RationalTime(frames, 60)`), recortados ao fim do arquivo.
- **O que o adaptador faz bem (medido):** FCPXML 1.8 com `frameDuration="1/60s"`, um `asset` por arquivo reaproveitado
  entre clipes, áudio em lanes -1 e -2, duração da sequência = soma dos clipes, tempos na grade de quadros.
- **Defeitos medidos e corrigidos em `export/fcpxml.py`** (sem mudar a timeline): `asset-clip` soltos na raiz do
  documento (nada os referencia; posição válida ⚠️ de memória), `format` sem largura/altura (acrescentado 1920x1080) e
  `uid=""` vazio no projeto.
- **Limites que ficam:** o `asset` leva o nome do primeiro clipe que o usa (o rótulo do marcador), o que só atrapalha
  a leitura; áudio vai embrulhado em `<gap>`; faixa vazia é descartada (A3, A4 não saem); versão do FCPXML é a 1.8;
  não testado: títulos, keyframes, clipes desativados, cor de marcador. Nada disso foi pedido ao mínimo da 1B.
- **Validação:** não há DTD oficial utilizável offline. `check_fcpxml` confere XML bem formado, `format` a 60 fps
  exatos, `ref`/`format` que resolvem, tempos na grade de quadros, duração da sequência e lanes de A1/A2; o `export`
  sai com código 1 se algo falhar. Isso prova coerência interna, **não** que o Resolve importa: a importação real é
  da 1C. Se ela falhar ou o layout de trilhas vier errado, o plano já prevê escrever o FCPXML direto.

## 31. 1B: gravador de marcadores (`cronista record`)

Quarto item da ordem da 1B. Confirmação das bibliotecas (pedida pelo plano) e decisões de implementação.

**Bibliotecas (conferidas no PyPI e no protocolo oficial em 2026-11-16):**
- obs-websocket: `simpleobsws` 1.4.3 (MIT, junho de 2025, Python >= 3.9; do IRLToolkit, mesmo autor do protocolo,
  assíncrona sobre `websockets` e `msgpack`). Descartadas: `obsws-python` (GPL-3.0) e `obs-websocket-py` (parada
  desde 2023, só protocolo v4 na prática).
- Hotkeys globais: `pynput` 1.8.2 (LGPL, maio de 2026; F1–F24 no Windows). Descartada: `keyboard` (parada desde
  2020). Instalada só em Windows (`sys_platform == "win32"`): em Linux sem display o `pynput` nem importa, e a CI
  roda em Ubuntu. O núcleo e os testes não dependem dele (porta `HotkeySource`).
- Protocolo (doc oficial): `CreateRecordChapter` (`chapterName` opcional, desde a 5.5.0 = OBS 30.2, só Hybrid MP4);
  eventos `RecordStateChanged` (`outputState`: STARTED, STOPPED, PAUSED, RESUMED...) e `RecordFileChanged`
  (`newOutputPath`, 5.5.0); `GetRecordStatus`; `GetRecordDirectory`. Assinatura de eventos `Outputs` = `1 << 6`.

**Achado que mudou o desenho:** o protocolo **não informa o arquivo ao iniciar a gravação**. `outputPath` só vem ao
parar, e `newOutputPath` só nas divisões. O diário precisa do arquivo desde o início, então o gravador procura o
vídeo mais novo na pasta de gravação (`GetRecordDirectory`), esperando até 3 s. Se não achar, escreve o caminho
**vazio** no diário e avisa; a ingestão assume o **primeiro arquivo da sessão**, com aviso (o arquivo desconhecido é
sempre o primeiro da gravação, porque as divisões chegam com caminho). ⚠️ Validar com o OBS real na 1C: se o OBS
informar o caminho de outro jeito, a busca na pasta sai.

**Decisões de implementação:**
- Portas (`recorder/ports.py`): `ObsLink`, `HotkeySource`, `Feedback`. O núcleo (`recorder/core.py`) é testado sem
  OBS, teclado ou alto-falante; as bibliotecas podem ser trocadas.
- A cada toque, nesta ordem: linha no diário com o **instante do toque** (carimbo tirado na thread do teclado, não
  quando a tarefa roda), `CreateRecordChapter` com `tipo|id` (id aleatório de 4 bytes em hex) e feedback. Se o OBS
  recusar o marcador, o diário ainda tem o toque (os dois registros são independentes, seção 4).
  `JournalWriter` passou a aceitar o carimbo (`Stamp`) como argumento.
- Toque durante a busca do arquivo espera o diário abrir, mas mantém o carimbo original.
- Toque fora de gravação: ignorado com aviso sonoro (nada é escrito).
- `Construção ▶/■`: o gravador guarda se há construção aberta (som do fim = dois toques; aviso ao parar com ela
  aberta). O pareamento definitivo continua sendo da ingestão.
- Diário em `<pasta de gravação>/gravacao-AAAAMMDD-HHMMSS.markers.jsonl`, ao lado do vídeo (a ingestão acha por
  pasta).
- **Retomada:** se o gravador abre (ou reconecta) com o OBS já gravando, reabre o diário da gravação em curso
  (sem repetir `recording_started`; a linha cortada pela queda é tolerada) ou, se não houver, cria um com o início
  estimado por `outputDuration`. Pausas e divisões ocorridas enquanto ele estava fora do ar não constam; avisa.
  Ao encerrar (Ctrl+C) com o OBS gravando, **não** escreve `recording_stopped`.
- Conexão: nova tentativa a cada 3 s (OBS ainda fechado ou conexão perdida); senha do WebSocket em
  `obs_password` no `*.local.yaml` ou em `CRONISTA_OBS_PASSWORD`, nunca em arquivo versionado.
- Teclas (config `marker_hotkeys`, sintaxe do `pynput`): padrão F13–F20; mudar uma não apaga as outras; `momento` e
  `novo_dia` obrigatórias; tecla repetida ou tipo desconhecido dão erro claro. `null` desliga uma opcional.
- Feedback: tom diferente por tipo (`winsound.Beep`), tom grave para aviso; `--quiet` só imprime.
- Detalhes da `simpleobsws` que condicionam o código (lidos da fonte): usa o subprotocolo msgpack; cada evento vira
  uma `Task` separada, então o callback só enfileira, para manter a ordem; não avisa quando a conexão cai, então
  há um vigia em `ws_open`.

**Testes (27 novos, 103 no total):** servidor obs-websocket **falso** (`tests/fake_obs.py`, protocolo v5 em
msgpack, com autenticação) contra o adaptador real; núcleo com OBS em memória (gravação completa com pausa e tempos
conferidos, fora de gravação, construção, marcador recusado, divisão, arquivo desconhecido, espera de arquivo,
retomada após queda com linha cortada); reconexão do laço principal; validação das teclas; ingestão com caminho vazio.

**Não coberto (1C, com o OBS real):** hotkey com o jogo em tela cheia e elevado; `CreateRecordChapter` com nome
`tipo|id` e comportamento durante pausa; a busca do arquivo na pasta; formato real dos eventos.

## 32. 1B: serviço do engine (`cronista serve`)

Quinto item da ordem da 1B: o engine dispara o processamento ao ver `recording_stopped` (decisão D1).

**Problema de desenho encontrado:** a sessão da ingestão era "uma pasta", mas o gravador escreve o diário na pasta de
gravação do OBS, que normalmente é uma só para todas as gravações. Com a sessão por pasta, gravações diferentes
seriam fundidas e os marcadores de uma apareceriam como "fora da sessão" nas outras. **Decisão: uma gravação = um
diário = uma sessão.** `RecordingSession.folder` passou a significar a **origem** da sessão: uma pasta (ingestão
manual, como antes) ou o arquivo de diário (serviço). Sem migração: a coluna e a unicidade continuam servindo.
`ingest_folder` virou um invólucro de `ingest_files(origin, arquivos)`.

**Como o serviço funciona (`watch.py`):**
- Consulta `watch_dir` a cada `watch_poll_seconds` (5 s), sem biblioteca de observação de arquivos: igual em disco
  local, externo e de rede, e não perde evento se o serviço estava fechado (ao abrir, varre tudo).
- Uma gravação está pronta quando o diário termina em `recording_stopped` **e** o diário e os arquivos estão
  parados há `settle_seconds` (10 s). ⚠️ Existe porque o OBS ainda finaliza o Hybrid MP4 depois do evento: não
  verificado com o OBS real (1C).
- Os arquivos vêm do diário (`recording_started` + `file_changed`), pelo caminho ou, se o disco mudou, pelo nome na
  pasta. Caminho vazio (o gravador não achou o arquivo, §31) é deduzido pela data de modificação: o vídeo mais
  antigo que cabe entre o início e o fim da gravação, com aviso.
- **Gravação interrompida** (OBS fechou, PC caiu): o diário fica aberto. Depois de `abandoned_after_hours` (4 h) sem
  nada crescer, entra no mesmo caminho com aviso, e o remux da ingestão cobre o arquivo cortado. 4 h porque uma pausa
  longa também deixa o arquivo parado; se for pouco ou muito, é config.
- Sessão incompleta (processo morto no meio) é retomada: "completa" = todos os arquivos chegaram à etapa `audio`.
- Falha: relatada uma vez e só tentada de novo se o diário mudar ou o serviço reiniciar (sem laço quente).
- `--once` faz uma varredura e sai; `--watch` sobrepõe `watch_dir` (caminho pessoal, só em `*.local.yaml`).
- Recupera jobs órfãos ao iniciar (como `cronista ingest`). Recebe a `GpuGate` e a repassa, mas a ingestão usa só
  CPU; a `GpuGate` real (próximo item) importa para as etapas de GPU da Fase 2 em diante e para a prévia com NVENC.
  **Substituído pelo §35:** o gate vale para toda etapa, de CPU ou GPU (CLAUDE.md: "Processamento pausa enquanto o OBS grava...").

**Testes (11 novos, 114 no total):** gravação encerrada ingerida uma só vez; não ingere antes de parar nem de
assentar; duas gravações na mesma pasta viram duas sessões sem avisos de marcador fora da sessão; divisão de arquivo;
arquivo inicial desconhecido; diário abandonado (arquivo interrompido); falha sem laço quente; retomada de sessão
incompleta; laço do serviço; e um teste que liga o **gravador** ao **serviço** (o diário que um escreve é o que o
outro consome). Fumaça pela CLI: `serve --once` → `status` → `preview`.

**Não coberto (1C):** o tempo real que o OBS leva para finalizar o arquivo depois do `STOPPED`; pasta de rede;
comportamento com o OBS gravando em subpastas (o gravador e o serviço olham só o nível superior da pasta).

## 33. 1B: `GpuGate` real

Sexto item da ordem da 1B: a política de GPU da seção 4.1 (pausar com o OBS gravando ou jogo em tela cheia).

**Gates (`gates.py`), compostos por `CompositeGate` (livre só se todos estão livres, motivo = o do primeiro que recusou):**
- `ObsRecordingGate`: `GetRecordStatus` pelo obs-websocket, uma conexão curta por consulta, em thread própria (o
  gate é síncrono e pode ser chamado de dentro de um laço asyncio). Antes, uma checagem rápida de porta
  (0,5 s): **medido neste PC que o Windows leva ~2 s por endereço para recusar uma conexão em `localhost`** (4 s
  no total); com a checagem, OBS fechado responde em ~1 s. Exige o servidor WebSocket do OBS ligado (já exigido
  pelo gravador).
- `FullscreenGate`: `SHQueryUserNotificationState` (shell32, via ctypes), ocupada nos estados 2 (aplicativo em tela
  cheia), 3 (Direct3D em tela cheia exclusiva) e 4 (modo de apresentação). Chamada real testada neste PC (devolveu
  5, "aceita notificações"). ⚠️ Valores dos estados de memória; ⚠️ jogo em janela sem borda pode não ser detectado.
- `GpuLoadGate` (opcional, `gpu_busy_percent`): `nvidia-smi --query-gpu=utilization.gpu`, ocupada com uso >= o limite.
  Cobre o janela-sem-borda, mas mede a GPU inteira (a consulta é só *antes* de cada etapa, então o próprio
  processamento não se auto-bloqueia). Neste PC o `nvidia-smi` existe e respondeu 5%.
- **Substituído pelo §35:** o gate é consultado antes de **toda** etapa que vai rodar (não só as de GPU) e a carga da GPU não vale
  entre blocos de uma etapa; o gate passou a ter cache curto.
- Regra comum: sinal ilegível (OBS fechado, sem `nvidia-smi`, sem Windows) conta como "não ocupado"; só se adia por
  um sinal real. Consequência: se o WebSocket do OBS estiver desligado ou com senha errada, o gate não enxerga a
  gravação. Mitigação: se a porta do OBS responde mas a conexão falha (senha errada), o gate registra um aviso
  (`gate_obs_recusou_conexao`) no log, para não ficar cego em silêncio.
- `build_gate(settings)`: `gpu_gate: false` em `dev` (sem GPU nem OBS), `true` em `prod`. `cronista ingest`,
  `serve` e `preview` passaram a usar o gate do ambiente.

**Pausa no meio da etapa:** o plano diz "retoma de onde parou", mas o executor só consultava o gate *antes* de cada
etapa; uma etapa de 10 h de Whisper não pararia quando o jogo abre. `StageContext.wait_for_gpu()` (no-op para etapa
de CPU) deixa a etapa pausar **entre blocos**; é o contrato para as etapas de GPU da Fase 2 (processar em blocos e
chamar entre eles; o resultado parcial de cada bloco fica no cache). A prévia com NVENC também consulta entre
trechos. O auxiliar `wait_until_free` registra o motivo no log a cada espera.

**Testes (20 novos, 134 no total):** estados da tela cheia e limiar de carga; composição e motivo; `build_gate` por
ambiente; contagem de esperas; gate do OBS contra o servidor falso (grava, para, OBS fechado, senha); etapa de GPU
que pausa entre blocos quando um "jogo abre" no meio; etapa de CPU que nem consulta o gate. **Não testado:** gate de
tela cheia com um jogo de verdade, NVENC, e a pausa entre trechos da prévia (precisa de GPU).

## 34. 1B: fixture "com pausa" e verdade-terreno do tempo dos marcadores

Último item da ordem da 1B. A fixture de vídeo "com pausa" estava prevista na 1A (tarefa 7) e não havia sido feita,
e os testes de tempo (`test_timeline.py`) só conferiam a **aritmética** sobre eventos sintéticos, sem nenhum vídeo.
O critério da 1B ("erro < 100 ms nos sintéticos") pede mais: provar que o tempo reconstruído cai no **quadro** certo.

**Desenho (`devtools/timecoded.py`):** vídeo 320x180, 60 fps exatos, três faixas de áudio, com o **relógio de parede
escrito nos quadros**: metade esquerda = rampa lenta (0 a 20 s, resolução ~80 ms), metade direita = dente de serra de
1 s (resolução ~4 ms, ambígua módulo 1 s); juntas dão o relógio com erro de poucos ms. Uma gravação com pausa é montada
**recortando** o trecho pausado (`[(0, 4), (9, 14)]` = gravou 0-4 s, pausou até 9 s, gravou até 14 s; o arquivo tem 9 s),
como o OBS faz. `wall_time_at(arquivo, t_mídia)` é o oráculo: decodifica o quadro nesse instante e devolve o relógio.
Os valores de brilho ficam em [16, 235] (faixa limitada do H.264), senão o decodificador comprimiria o sinal.
Medido: erro do oráculo ~18 ms (um quadro de 1/60 s); gerar um vídeo leva < 1 s.

**Testes (`test_timecoded.py`, 6 novos, 140 no total):** o diário diz a que relógio de parede cada toque ocorreu; o tempo
de mídia que a ingestão reconstrói precisa cair no quadro que mostra esse relógio (< 100 ms) e no arquivo certo.
Cenários: gravação simples; pausa recortada do arquivo; divisão de arquivo (relógio reinicia no novo); pausa no
primeiro arquivo que não pode vazar para o segundo; gravação interrompida (MP4 fragmentado e cortado, diário sem
`recording_stopped`, depois do remux); e um controle negativo do oráculo.

**Teste de mutação (feito uma vez, à mão):** quebrei de propósito `reconstruct_media_times` de três jeitos e confirmei
que os testes falham: pausa não descontada (2 testes), divisão que não reinicia o relógio (2), pausa que vaza para o
arquivo novo (1, só o teste combinado pausa+divisão pega, então ele é necessário). O arquivo foi restaurado.

**Limite honesto:** o vídeo é gerado pelo FFmpeg e a pausa é recortada por nós, então prova que a **conta** do diário
bate com o conteúdo sob a premissa de que o OBS recorta a pausa do arquivo e restaura o relógio na divisão. Essa
premissa vem do plano e da documentação do OBS; verificá-la com uma gravação real com pausa é item da 1C.

## 35. 1B: correções da revisão de código (10 achados)

`/code-review` sobre os 6 commits à frente do `origin/main` (o `main` local estava desatualizado; o PR #2 da 1B inicial já
estava no `origin/main`). Os 10 achados foram corrigidos, cada um com teste; os mais sutis foram conferidos por mutação.

**Decisões que mudam o que foi escrito antes (§32 e §33 ficam como história):**
- **Todo processamento pausa, não só o de GPU.** O CLAUDE.md diz "Processamento pausa enquanto o OBS grava ou um jogo
  em tela cheia está aberto", e eu tinha restringido o gate às etapas com `uses_gpu`. Pior caso real: parar a gravação
  e começar a próxima, e o serviço fazer proxy e WAV de horas de vídeo (CPU/disco) durante o jogo. Agora `run_pipeline`
  espera o gate antes de **toda** etapa que vai rodar (etapa em cache não espera), e a prévia também (CPU ou NVENC).
  O `uses_gpu` ficou só informativo.
- **Dois modos de consulta.** `is_free()` = pode começar; `is_free_while_working()` = continuar entre blocos de uma
  etapa. O `GpuLoadGate` só vale no primeiro: no meio da etapa a carga medida é a da própria etapa, que esperaria por
  si mesma para sempre (o que a docstring antiga negava). Gates sem o segundo método usam o primeiro.
- **Cache curto do gate (`CachedGate`, 3 s).** Cada sonda do OBS custava ~1 s com o OBS fechado, e a prévia consulta por
  trecho (200 marcadores = 200 s só de sondas). O TTL (3 s) é menor que o intervalo de espera (5 s), então esperar por
  um gate ocupado sempre reconsulta. A checagem de porta caiu de 0,5 s para 0,25 s (localhost responde em ms).

**Serviço (`watch.py`):**
- Um arquivo já pertencente a outra sessão (ex.: a pasta do OBS ingerida à mão antes) agora é erro claro
  (`SessionConflictError`), checado **antes** de criar projeto ou sessão. Antes criava uma sessão sem arquivos, que
  era reingerida a cada varredura e quebrava `preview`/`export`. `cronista ingest` também mostra o erro de forma limpa.
- Cada diário é tratado isolado: erro inesperado (arquivo que some, banco) vira o resultado daquele diário, com
  `rollback()` (a `Session` vive o laço inteiro), sem derrubar a varredura. Pasta de gravação inacessível é avisada uma vez.
- Falha tem prazo de nova tentativa que dobra (`retry_seconds` = 600 s, teto de 6 h), e é tentada de novo na hora se o
  diário mudou. Antes só reiniciando o serviço.
- **Diário que cresce depois da ingestão** (ex.: tratado como abandonado após 4 h parado, e o criador retoma e para):
  a sessão guarda `source_signature` = tamanho do diário na ingestão (migração 0003; o diário só cresce). Mudou =
  reingere (as etapas em cache não refazem nada). Só o tamanho, não a data, para backup/antivírus não disparar nada.

**Gravador:**
- `_begin` nunca deixa o gravador travado ou caído: `OSError` (sem permissão, disco cheio) vira aviso, `_ready` é sempre
  liberado (`finally`) e os toques seguem só no marcador do OBS. Escritas do diário (toque, pausa, divisão, parada)
  que falham viram aviso em vez de exceção.
- Retomada reconcilia o estado de pausa: se o diário reaberto termina pausado e o OBS já retomou, escreve `unpaused`
  (e o contrário). Antes os marcadores seguintes saíam presos no ponto da pausa, com aviso falso.
- O tom (`winsound.Beep`, síncrono) toca em uma thread própria, na ordem: bloqueava o laço por até 350 ms e atrasava o
  carimbo dos eventos do OBS (pausa, divisão), estourando os 100 ms do critério.
- Falha numa tarefa de toque agora avisa ("toque NÃO registrado") em vez de sumir.

**Ainda aberto (não está nos 10):** `_open_journal` repete a lógica de `watch.inspect_journal` (duplicação pequena);
`watch` consulta o banco por diário a cada varredura (barato em SQLite, mas cresce com a série); `gates` importa o relógio
de `recorder.core`. Ficam para quando incomodarem.

**Testes (160 no total, 26 novos):** um por achado (gate em etapa de CPU e em etapa em cache, modo "trabalhando" sem
auto-bloqueio, `CachedGate`, conflito de sessão, rollback, prazo com recuo, diário que cresce, `_begin` com pasta
inválida, escrita de diário falhando, retomada com pausa nos 4 cruzamentos, beep fora do laço, toque que falha).
**Mutação manual:** desfazer cada correção faz o teste correspondente falhar.

**Adendo (CI e SonarCloud, PR #3):**
- **Ubuntu:** o `mypy` falhou em `winsound.Beep` (módulo só do Windows) e a CI parou antes dos testes. Agora a função
  tem a guarda `sys.platform != "win32"`, que o mypy entende. `uv run mypy --platform linux` passou a fazer parte da
  verificação local, porque é o que reproduz a CI sem ter um Linux.
- **SonarCloud (Security Rating E, 2 vulnerabilidades):** (1) *path traversal* "via conteúdo de arquivo" em
  `make_timecoded`, que lia e regravava o mesmo caminho: agora trunca no lugar (`truncate`), sem ler nada;
  (2) `ws://` em texto claro: o OBS não oferece TLS, então o gravador **só conversa com o OBS deste PC** (host
  loopback; outro host é recusado com erro claro), o que já era premissa (ele procura o arquivo da gravação no disco
  local). O `ws://` loopback é o único que o OBS entrega. O Sonar **não honrou** `# NOSONAR` nessa regra (S5332 vem como
  vulnerabilidade), então o esquema virou a constante documentada `OBS_WS_SCHEME`; a mitigação real é a recusa de host
  que não seja loopback. Se o Sonar ainda acusar o texto claro, é falso positivo a marcar como "Safe" na interface
  do SonarCloud (decisão do criador), não algo a esconder no código.
  Achado no teste: IPv6 (`::1`) gerava URL inválida; agora leva colchetes.
- **Consequência assumida:** OBS em outro PC não é suportado pelo gravador nem pelo `GpuGate`. Se um dia for preciso,
  exige outro jeito de achar o arquivo da gravação (hoje é o disco local) e TLS/túnel.

---

## 36. Visão narrativa v0.1: decisões aprovadas, Fase 5A e lacunas técnicas

Documento `Cronista_Visao_Narrativa_e_Viabilidade_v0_1.md` (2026-11-16), avaliado contra o plano, o CLAUDE.md, a memória
da 1B e o código do engine (diagnóstico da sessão, sem alterações de código). O criador aprovou três decisões.

**Decisões aprovadas:**
1. **Formatos narrativos gerais.** A estrutura passa a ser de capítulo/unidade de progresso, objetivo e fase. O modo
   "100 dias" é um formato entre vários (missão, desafio, sobrevivência por regras) e continua preservado, com `Novo dia`
   e cartelas "Dia N". Hitman, por exemplo, não usa dias (seções 4, 5.4 e 6.3 do plano).
2. **Montagem inteligente como preferência editorial.** Para esforço longo (ex.: 20 min de mineração), entram o início,
   alguns marcos, a descoberta e a consequência. Timelapse vira opção por trecho, não padrão obrigatório (seção 6.3).
   Substitui a regra anterior "farm vira timelapse 4×–50×" como padrão.
3. **Fase 5A** (objetivos, subobjetivos, estados e evidências), entre a Fase 4 e a Fase 5. Estados, relações e evidências
   como no documento; citação literal obrigatória na descoberta por fala; declaração não é conclusão (seção 7 do plano).

**Benchmarks de modelos na Fase 2.** Decisão de sequência: a 1C não mede desempenho de modelo. Os benchmarks de velocidade,
VRAM e qualidade (WER) ocorrem no início da Fase 2. A 1C fica com testes físicos e técnicos (Resolve, OBS, FIFINE,
GpuGate, gravação real com `MIC_RAW` ativo). Isso altera a decisão anterior "benchmark da Fase 1" (seções 6.1, 7 e 9).

**Lacunas técnicas e fase de correção** (levantadas no diagnóstico; nenhuma implementada ainda):
1. **Tempo do marcador em float de segundos** (`marker.media_time_s`). Com 60 fps exatos, o correto é quadros inteiros,
   para não haver deriva. Fase: **1B, antes do merge** (tarefa 7 do `fase-1-fundacao.md`).
2. **Padrão de evidência/proveniência** (intervalo em quadros, fonte, confiança, versão do modelo). Não existe no código.
   Fase: **início da Fase 2** (primeiro consumidor: transcrição e sinais), ampliado na **5A**.
3. **`Artifact` com `UniqueConstraint(media_file_id, stage)`.** Duas variantes de um estágio se sobrescrevem, o que
   impede comparar modelos no benchmark. Fase: **início da Fase 2, antes do benchmark de WER**. A chave de cache já
   inclui versão e parâmetros (`pipeline/cache.py`).
4. **Sinais em série temporal sem lugar definido.** Decidir formato (array no cache, referenciado por `artifact`) e
   consulta. Fase: **início da Fase 2**, antes da primeira análise.

**Notas de diagnóstico registradas:**
- A visão diz que a 1B estava "em codificação"; o repositório e a memória indicam código completo no `dev`, com o
  `/code-review` já feito (§35). O roadmap do documento está desatualizado e não foi usado como status.
- O `Cronista_Teste.mp4` tem a faixa 3 silenciosa (`MIC_RAW` mutado). Não serve para testar fala nem objetivos; a gravação
  de teste com `MIC_RAW` ativo entra como tarefa 7 da 1C.
- A sequência do roadmap foi mantida: 1B → 1C → Fase 2 (com benchmarks) → 3 → 4 → **5A** → 5 → 6 → 7 → 8 → 9.

---

## 37. Memória narrativa em SQLite (avaliação e decisão, sem implementação)

**Pergunta:** o SQLite já existente no Cronista pode guardar o contexto narrativo (objetivos, acontecimentos, relações,
evidências, resumos e correções humanas), para que a IA analise muitas horas sem manter toda a transcrição na janela de contexto?

**Avaliação do SQLite atual:** o banco já é SQLite com SQLAlchemy 2 + Alembic (plano §5.2 e tarefa 4 da 1A), com `project`,
`session`, `media_file`, `job`, `artifact` e `marker`. Serve a um único usuário, sem infraestrutura, e a migração para Postgres
continua possível. Limites: um escritor por vez (o que obriga transações curtas com `cronista serve` e o Studio), nenhuma
busca vetorial embutida e índices que precisam ser desenhados desde o início. A busca textual (FTS5) depende da build do
SQLite no Python 3.12 do Windows; a crença é que ela vem incluída, mas não foi verificada.

**Decisão:**
1. A memória narrativa fica **no mesmo banco**, nas tabelas da Fase 5A: `objective`, `objective_state`, `narrative_event`,
   `narrative_link`, `evidence`, `summary` (nomes provisórios; detalhe na seção 7, Fase 5A).
2. **Tabelas de fatos só recebem inserção.** Estado, evento e relação nunca são atualizados ou apagados. A correção humana é
   uma linha nova com `origem=humano` e `substitui_id`. Assim a versão automática e a evidência original continuam
   consultáveis, o que cumpre o requisito 6 (correção sem perder a rastreabilidade).
3. **Toda informação deriva de evidência:** quadros inteiros a 60 fps, fonte, `artifact_id`, citação literal quando houver
   fala, confiança e versão do modelo. Sem evidência válida, a informação fica como hipótese.
4. **Resumos são derivados e marcados:** cada frase de um resumo aponta para `evidence_id`; quando uma fonte muda (inclusive
   por correção), o resumo recebe `stale`.
5. **Recuperação determinística na 5A:** objetivos ativos, eventos da sessão atual, vizinhança de `narrative_link` com dois
   saltos no máximo, busca textual e janela de quadros, com teto fixo de tamanho por chamada. Embeddings ficam fora desta
   decisão e só serão reavaliados se a busca textual não bastar.

**Alternativas consideradas e descartadas:**
- *Manter tudo na janela de contexto:* não cabe em horas de gravação nem no plano Pro (plano §8, risco "limites de uso").
- *JSON ou planilha por sessão:* não relaciona sessões, não permite consulta e não guarda correções com histórico.
- *Banco de grafos (ex.: Neo4j) ou banco vetorial dedicado:* um serviço a mais, contra "custo zero e zero infraestrutura".
  As relações cabem em tabela com recursão limitada.
- *Atualizar linhas no lugar:* simples, mas destrói a origem; descartado pelo requisito 6.

**Impactos e riscos:**
- Cresce com a série: índices por `project_id`, `session_id` e quadro desde a primeira migração da 5A.
- Concorrência: um escritor por vez; WAL e transações curtas. Verificar com `cronista serve` ativo na implementação.
- Resumo inconsistente ou relação inventada pelo LLM local: mitigado por `evidence_id` obrigatório e `stale`.
- Contratos: as entidades novas entram no fluxo Pydantic → JSON Schema → TypeScript (D2).
- Universal: objetivos vêm só do perfil YAML ou do projeto (`objetivos` e `regras`); nada por jogo no núcleo.
- Não mexe na 1B nem na 1C: nenhuma tabela nova entra agora, e a tarefa 7 da 1B (quadros inteiros) continua como está.

**Associação à Fase 5A e dependências:** a 5A é a implementação desta decisão e depende de: padrão de evidência e
unicidade de `Artifact` por variante (Fase 2, lacunas 2 e 3 do §36), sinais em série temporal (Fase 2, lacuna 4), estados
de cena (Fase 3) e eventos e segmentos (Fase 4). A ordem do roadmap do §36 não muda.

**A verificar antes da implementação (não verificado nesta sessão):**
- Disponibilidade do FTS5 no `sqlite3` do Python 3.12 para Windows.
- Comportamento de WAL com o serviço `serve` e a leitura pelo Studio.
- Números de corte do teto de recuperação e da profundidade de relações: definidos no início da 5A, com medição.
- Se `sqlite-vec` for necessário (só se a busca textual não bastar).

---

## 38. 1B: tempo do marcador em quadros inteiros (tarefa 7, lacuna técnica 1)

**Decisão (2026-11-16):** `marker.media_time_s` (float) vira `marker.media_frame` (inteiro, quadro de mídia a 60 fps
exatos dentro do arquivo). Executa a lacuna 1 do §36, feita depois do merge do PR #3 numa branch curta
(`fase/1b-quadros`), porque o merge foi anterior à tarefa.

**Como ficou:**
- Uma única conversão, em `domain/frames.py`: `seconds_to_frame` (quadro mais próximo, nunca negativo) e
  `frame_to_seconds`. Segundos só existem nas bordas: `ffprobe` (capítulos), janelas da prévia/exportação e textos de aviso.
- `JournalMarker`, `FileChapter` e `ResolvedMarker` guardam `media_frame`. A tolerância de reconciliação passa a 60
  quadros (1 s); o capítulo inicial do OBS é reconhecido por `media_frame == 0`.
- Migração `0004`: soma a coluna, converte os valores existentes (`round(s * 60)`), remove `media_time_s`; o downgrade volta
  para segundos. Teste de migração nos dois sentidos.
- Testes de reconstrução comparam quadros exatos (inclui relógio fracionado: 12,508 s → quadro 750; 12,51 s → 751).

**Alternativas descartadas:** guardar segundos como `Decimal`/racional (continua exigindo arredondar em cada consumidor) e
manter o float com "tolerância" (o erro de ponto flutuante aparece só em exportação para o Resolve, que exige quadros inteiros).

**Impactos:** a Fase 2 em diante (evidências, objetivos da 5A) já nasce em quadros; `ResolvedMarker` e a tabela `marker`
são o único lugar do código que tinha tempo em float por marcador. A janela da prévia (`ClipWindow`) segue em segundos,
por ser decisão de renderização e não evidência.

---

## 39. 1C: primeira passada no PC de casa (2026-11-16)

O PC de casa (`prod`: RTX 3060, driver 610.88, OBS 33.0.1, FFmpeg 9.0.2) foi usado pela primeira vez. Branch
`fase/1c-pc-de-casa`. **O DaVinci Resolve não estava instalado** neste PC na primeira passada (tudo que dependia dele ficou como kit
pronto); foi instalado depois, no mesmo dia (ver "Segunda passada" abaixo).

**Decisões:**
- **Classes do gabarito** (proposta inicial, em `docs/gabarito.md` e `cronista/gabarito.py`): `fala`, `risada`, `grito`,
  `teclado`, `respiracao`, `farm`, `momento`, `menu`, `loading`, `idle`, `cinematica`, `construcao`, `objetivo`,
  `estado`. Sobreposição entre classes diferentes é permitida; o validador recusa classe fora da lista (crescer a lista é
  decisão). Tempo anotado em segundos e guardado em quadros a 60 fps (§38). Comando `cronista gabarito` com
  `--video` (confere duração) e `--previa` (um MP4 curto por anotação).
- **Kit do Resolve em três FCPXML separados** (`cronista resolve-kit`): básico, recursos e áudio; um erro de importação
  aponta o recurso culpado. FCPXML versão 1.9 com `asset src=`; UIDs de título/transição e EDL de marcadores de memória (⚠️).
  Roteiro de checagem em `integrations/resolve/ROTEIRO.md`; script interno em `integrations/resolve/cronista_kit_teste.py`
  (relata OK/FALHOU por passo).

**Medido no `prod`:**
- Gravações reais do OBS (`Cronista_Teste.mp4`, `testeia.mp4`): `cronista ingest` sem aviso de formato (H.264 High,
  yuv420p, bt709, 60/1, 3 faixas); 5 marcadores (capítulos `Sem nome N` viram `Momento` com aviso, como previsto);
  `cronista preview` com `h264_nvenc`: 5 trechos, 117,1 s esperados e 117,1 s gerados, em ~39 s; `cronista export` sem
  problema estrutural. A interrupção/remux e a gravação com o gravador continuam por fazer (guia do OBS, seção 6).
- **CUDA** (`integrations/cuda/check_cuda.py`, ambiente descartável): torch 2.11.0+cu128 e ctranslate2 4.9.0 convivem
  nas duas ordens de importação; cuDNN 9.19; `faster-whisper tiny` em float16 rodou na GPU (~1,2 GB de VRAM).
  Limite do teste: as duas ordens importam o torch antes de rodar o Whisper, então não prova o CTranslate2 sozinho.
- **OBS (lido dos arquivos de configuração):** perfil conforme o plano (Hybrid MP4, NVENC H.264, 60 comum, NV12, 709,
  trilhas 1–3). Falhas: servidor WebSocket **desligado**; `MIC_RAW` **mudo** (explica a faixa 3 vazia); `MIC_MIX` sem
  RNNoise e em dispositivo diferente do `MIC_RAW`. Registrado em `integrations/obs/GUIA.md`.
- **FIFINE SC3** (VID 3142, PID 0C33): o Windows a mostra com duas interfaces HID (controle de mídia e uma de fabricante,
  `0xff00`) e nenhuma entrada MIDI. 90 s de escuta sem eventos: **inconclusivo** (não se sabe se os botões foram apertados);
  repetir com o criador apertando botão por botão. **Decisão posterior (2026-11-16): o criador descartou a FIFINE SC3
  como dispositivo de marcação** ("não funcionam para o que precisamos"); vale o caminho 3 do plano (teclas F13–F24
  por macro, mouse ou macropad). O spike fica em `integrations/fifine/` só como registro.

**Segunda passada: Resolve gratuito 21.2.1.0006 (PT-BR), mesmo dia.** Instalado e testado com o kit
(`cronista resolve-kit`). Detalhes e ressalvas na seção 6.5 do plano; resumo:
- Scripting externo **bloqueado**. O Console interno só aceita Lua, sem `io`/`dofile`/`loadfile`/`require`; scripts em
  `Scripts\Utility` não aparecem no menu. O teste roda colando `teste-linha-unica.lua` (gerado por
  `integrations/resolve/gerar_linha_unica.py`). Um projeto novo por rodada: reaproveitar o anterior fez o Resolve
  recusar timelines de mesmo nome e mascarou resultados (a recusa do título na 2ª rodada era isso, não o UID).
- FCPXML: entram `01`, `02a` a `02e` e `03-audio`; HEVC (`02f`) é recusado; o FCPXML com tudo junto foi recusado,
  por isso o kit tem um arquivo por recurso. Título nativo, overlay com alfa e 3 trilhas de áudio (canal desativado
  chega como clipe desativado) confirmados nos prints.
- Bug nosso achado no teste: o `overlay_alfa.mov` saía 100% transparente (`drawbox` sem `replace=1`); corrigido, com
  teste automático do pixel.
- Marcadores: nenhuma das três posições no FCPXML (clipe, sequência, gap) vira marcador de timeline; o Resolve gratuito
  não tem importação de marcadores por EDL nos menus; `AddMarker` pelo Console funciona. **Decisão:** marcadores só por script.
- SRT: pelo menu Importar → Legenda; o clipe do Pool começa na 1ª fala e desloca 1 s se solto no início. **Decisão:**
  o app gera o SRT com uma fala vazia em 0 s (conferido: falas em 1 s, 4 s e 8 s).
- **FCPXML do app (A16): o adaptador OTIO `fcpx_xml` foi abandonado.** O arquivo que ele gerou (versão 1.8, `<project>`
  solto, `<clip>` com `<video>` e `<gap>` aninhados) foi recusado pelo Resolve ("Unable to find inherited value for key
  'library'"); com `library/event` por cima o Resolve abriu a janela "Carregar XML" e **travou** depois do Ok (mais de
  uma hora). **Decisão:** o app escreve o FCPXML 1.9 à mão (`export/fcpxml.py`), no desenho dos arquivos do kit que
  importam: `asset-clip` por trecho na V1, áudio do jogo e do microfone (WAVs) como `asset-clip` nas lanes -1 e -2. O
  `.otio` continua sendo gravado. **Resultado (mesmo dia): importou sem erro nem travada**: `sessao-1` com 5 clipes na V1
  (10 s, 30 s, 23:32, 30 s, 23:34), `game.wav` na A1 e `mic.wav` na A2, 1:57:06 no total (7026 quadros a 60 fps, como
  o esperado); o áudio do mestre não entra, então não há áudio duplicado; painel Marcadores vazio (esperado, marcadores
  só por script). Sincronia de áudio e vídeo, reprodução e uso da GPU ainda não conferidos. Isso substitui a escolha da 1B
  (histórico §30) de usar o adaptador com correções mínimas.
- O criador perguntou se dava para trocar o editor, se necessário: avaliado, **não é necessário**; Kdenlive fica como
  plano B (de memória, não verificado).
- Erros meus corrigidos no caminho: o roteiro apontava Linha de Tempo → Importar para o EDL de marcadores (o menu não
  existe nessa versão) e dizia que o script aparecia em Área de Trabalho → Scripts.

**Pendente (precisa do criador):** ajustes do OBS acima (a configuração no disco ainda não foi reverificada);
gravação com `MIC_RAW` ativo; anotação do gabarito; no Resolve: relink, HEVC à mão, tons de áudio, desempenho e render
(blocos A5, A16, D do roteiro). Resultado do `SetLUT` e dos marcadores de clipe da última rodada não chegou em texto.

---

## 40. Questionário de decisões editoriais v0.1 (2026-11-16)

Documento `Cronista_Questionario_e_Decisoes_Editorias_v0_1.md`: 27 perguntas e as respostas do criador, mais o contexto
aprovado antes delas. Avaliado contra o plano mestre, o histórico (§36–39) e o `fase-1-fundacao.md`. **Só documentação:
nenhum código foi alterado, a ordem do roadmap não mudou e a 1B/1C não ganharam nada.** Registrado na branch
`docs/questionario-editorial`. Os conflitos com decisões anteriores ficaram em aberto no primeiro commit e foram
**decididos pelo criador na mesma conversa** (bloco "Decisões do criador", abaixo; seção 9 do plano).

**Contexto aprovado (já compatível):** autonomia nível B, editor autônomo supervisionado (a "primeira edição completa" é lida
como o rough cut rico da seção 6.3: o acabamento continua do criador no Resolve; confirmar se houver divergência);
narração escrita pelo Cronista e gravada pelo criador; formatos gerais (§36); memória em SQLite (§37); montagem inteligente (§36);
priorizar o Ollama local para o trabalho frequente e o Claude Pro só onde agrega valor, sem presumir API ilimitada (plano §1 e §6.1).

**Respostas registradas como decisão (plano, seção 6.8 e fases):**

| Q | Resposta | Efeito |
|---|---|---|
| 1 | A+B+C+D | Os quatro riscos (cortar o importante, partes monótonas, drama artificial, narrativa desconexa) viram critérios de revisão (6.8) |
| 2 | B | Preservar o contexto essencial e condensar o lento (já em 6.3) |
| 3 | C | Suspense por edição e narração, sem distorcer fatos (6.8) |
| 4 | B | Montagem de tentativas mostrando evolução (6.8; Fases 4, 5A e 6; viabilidade não comprovada) |
| 5 | C | Reação original e narração combinadas, sem repetir (já em 6) |
| 6 | C | Acontecimento fora do objetivo: avalia o impacto e cria um pequeno arco se merecer (6.8) |
| 7 | B+C | Abertura com cena forte e curiosidade sem inventar fatos; cinemática enquanto o criador narra o objetivo. Sem ângulos 3D novos (§6.2) |
| 8 | A | Final direto; um fracasso real é preservado (6.8, beats) |
| 11 | C com condição | Cronologia por padrão; antecipação só para gerar desejo ou ilustrar uma narração com cinemática; sempre marcada (6.8) |
| 12 | C | Humor adaptado ao contexto, preservando a espontaneidade (6.8) |
| 13 | C | Mantém as partes relevantes da fala longa e a narração complementa, incluindo a mudança de estratégia (6.8) |
| 14 | A | Evento de mod não confirmado vai para revisão humana, nunca descartado nem afirmado (5A) |
| 18 | C | Identidade híbrida: brand kit do canal mais estilo declarativo por série (6.4) |
| 19 | B+C | Efeitos dinâmicos e adaptativos, sem poluição visual (já em 6.4) |
| 20 | C | Referências, recursos próprios e feedback; só princípios e métricas de ritmo, nunca cópia (6) |
| 21 | A | Roteiro completo, com estimativa de duração por fala (6.8) |
| 22 | B+C+D | Tom natural, dinâmico e adaptativo (6.8) |
| 23 | D | Ganchos combinados conforme a narrativa, sem exagero nem invenção (6.8) |
| 24 | C | Ritmo dinâmico, respeitando o contexto da Q2 (6) |
| 25 | D | Legendas só em falas e momentos importantes, com animações pontuais (Fase 8) |
| 26 | C | Feedback escrito em linguagem natural, dentro do Studio (Fase 7); não é fine-tuning (Fase 7) |

**Respostas que só entram como indício:**
- **Q15 (resposta livre, sem letra):** "o roteiro é uma base para eu seguir, se ficar mais curto eu corto, se ficar maior eu estendo".
  Não recebeu A, B ou C. Reforça a dúvida em aberto sobre o ducking pré-aplicado (seção 9, item 9 do plano; o stem cru A6
  já permite desfazer), sem decidi-la.

**Conflitos com decisões anteriores (propostas feitas ao criador; resolvidos no bloco "Decisões do criador", abaixo):**
1. *Roteiro inteiramente local* (contexto) × §6.1 e §9 ("sem Claude, o fallback é o `NullProvider`"). Proposta: manter o
   `NullProvider` e acrescentar um `LocalScriptProvider` experimental, só se passar no benchmark de roteiro.
2. *Duração como referência, qualidade acima de duração* (Q9 A+B, Q10 A) × "um único vídeo de 30–50 min" (CLAUDE.md, plano
   §0.1, §1 e §9). Proposta: 30–50 min fica como padrão do formato 100 dias; a duração vira parâmetro e teto do projeto; o
   painel da série avisa "material insuficiente" sem forçar o preenchimento. Exige alterar o CLAUDE.md.
3. *Aprendizado só por feedback em texto* (Q26 = C, sem o D) × §3.4, §5.3 e Fase 7 (aceitar/rejeitar recalibra os pesos
   automaticamente). Falta saber se a recalibração automática continua.
4. *Música e SFX escolhidos e posicionados pelo Cronista* (Q16 = B) × §6.4 (baixa confiança fica em `sugerir`; piada visual e
   SFX de meme só como sugestão). Proposta: `aplicar editável` como padrão acima de um limiar, meme em `sugerir`.
5. *Biblioteca pessoal de efeitos, transições e SFX* (Q17 = C) × §6.4 (só Biblioteca de Áudio do YouTube ou música de IA) e a
   regra do Resolve gratuito (efeito do Studio ou plugin pago deixa marca d'água). Falta o formato dos arquivos do criador.
6. *"Modelos gratuitos diferentes"* (contexto): só modelos abertos locais? Serviço gratuito hospedado quebra "custo zero e tudo
   local" e a privacidade da gameplay e da voz.

**Q27** (o feedback aplica a correção na edição atual ou só registra para as futuras): estava pendente; **decidida** no bloco abaixo.

**Lacunas expostas (seção 9, item 11):**
- **Revisão humana entre a 5A e a Fase 7.** A Q14 exige revisão, mas o Studio só chega na Fase 7. Proposta: fila de revisão em CSV ou
  relatório HTML nas Fases 4 a 6, que o Studio absorve depois.
- **"Tom" ou emoção da cena** não existe como sinal. A Q16 (música conforme a emoção) e a Q19 (efeitos adaptativos ao tom)
  dependem dele. Viabilidade não comprovada.
- **Legendas de fala no vídeo longo** (Q25): a trilha "Legendas" da seção 6.3 é o SRT do roteiro, e a legenda gravada só existe nos Shorts.

**Decisões do criador sobre os conflitos e a Q27 (2026-11-16, mesma conversa):**
1. **Roteiro local:** `LocalScriptProvider` **experimental**, ao lado do `NullProvider`, que continua como fallback. Só vale se
   passar no benchmark de roteiro da Fase 2. Substitui "o roteiro não cai para o LLM local" (seções 6.1 e 9 do plano).
2. **Duração:** resposta livre: um vídeo de 25 min, com contexto narrativo interessante e começo, meio e fim definidos, com
   clímax, deve poder ser postado. O critério de "pronto" é o **arco narrativo completo**, não a minutagem. Registrado como:
   30–50 min é a duração-alvo e referência do formato 100 dias, **não obrigação**; o painel da série avisa "material
   insuficiente" sem forçar preenchimento (CLAUDE.md, seções 0.1, 1 e 9 do plano ajustados). Interpretação da resposta livre:
   não houve decisão sobre se a faixa 30–50 continua como padrão do painel; foi mantida como referência.
3. **Aprendizado:** os dois canais. Manter/tirar trecho no Studio (aceitar/rejeitar) continua recalibrando os pesos de nota
   sozinho, e o feedback escrito em texto acrescenta regras explícitas. Mantém a seção 3.4, a 5.3 e a Fase 7 como estavam.
4. **Música e SFX:** **tudo automático** (Q16 = B), inclusive SFX de meme e piada visual. Substitui "piadas visuais ficam como
   sugestão" (6.3) e "baixa confiança fica só como sugerir" (6.4). Continuam valendo o orçamento de efeitos por minuto, a
   intensidade ligada à nota do momento e a reversibilidade (efeito sempre em trilha acima do original). Sem item adequado na
   biblioteca, nada é aplicado. Risco registrado: o próprio plano apontava a piada visual automática como o que mais denuncia
   vídeo feito por IA; o orçamento por minuto e a revisão do primeiro corte são a mitigação.
5. **Biblioteca pessoal:** os efeitos, transições e SFX do criador são **arquivos de áudio e vídeo**, que funcionam no Resolve
   gratuito sem marca d'água. Passam a ser a fonte prioritária, com inventário e registro de origem e licença; a Biblioteca de
   Áudio do YouTube e a música de IA ficam como complemento (6.4).
6. **Modelos gratuitos:** só modelos abertos locais (RTX 3060). Serviços gratuitos hospedados estão fora.
7. **Q27:** o feedback escrito **aplica a correção na edição atual e registra a preferência** para as próximas. A edição atual é
   ajustada antes de exportar, com re-execução só das etapas afetadas (cache por hash); o Resolve continua de mão única.

Continuam em aberto desta entrada: critérios de aceite qualitativos para os quatro riscos, o sinal de "tom" da cena e a fila
de revisão (propostas, ainda sem fase de execução).

**Nota de consistência (fora do escopo desta entrada):** o plano ainda cita a FIFINE como pendente em §0.1, na Fase 1 e no item 2
de "Em aberto", apesar da decisão do §39. Não foi corrigido aqui.

---

## 41. Microfone sem a fonte crua (2026-11-16)

Origem: no teste do Resolve com as gravações reais, o microfone não tocava (A2 muda). Medido: a faixa 3 do
`Cronista_Teste.mp4` está a −91 dB, silêncio digital, porque o `MIC_RAW` estava mudo no OBS. O criador perguntou por que
o `MIC_MIX` não foi usado, propôs dois arranjos (1 jogo+mic mix, 2 jogo, 3 mic mix, 4 mic raw; ou 1 jogo, 2 mic mix, 3 mic
raw) e depois decidiu: **"vamos desconsiderar o mic raw"**.

**Decisão:** uma fonte de microfone só (`MIC`), com RNNoise, nas faixas 1 (mix) e 3 (microfone). Faixas: 1 = mix, 2 = jogo,
3 = microfone. Sem fonte crua. O código não muda: o app extrai as faixas de índice 1 (jogo) e 2 (microfone) (`AUDIO_TRACKS`).
Resolve a dúvida em aberto da seção 9 do plano ("para que serve o mix com RNNoise?").

**Custos assumidos (⚠️ a medir na Fase 2):**
- Teclado e respiração ficam atenuados na faixa 3; as classes `teclado` e `respiracao` do gabarito podem não ser
  detectáveis. Se o benchmark mostrar isso, reabrir com uma fonte crua na faixa 4 (ou tirar as classes).
- O benchmark "WER com e sem DeepFilterNet" passa a testar limpeza sobre um sinal que já passou pelo RNNoise.
- Sem cópia sem filtro, a limpeza do OBS não se refaz depois.

**Efeitos práticos:** a configuração do OBS é mais simples (uma fonte, sem o problema de duas fontes no mesmo
dispositivo). As gravações de teste atuais (faixa 3 vazia) continuam inúteis para fala; falta gravar com `MIC` ligado.
Documentos ajustados: `CLAUDE.md`, plano (seções 2, 6.4, 9 e listas), `integrations/obs/GUIA.md`, fase 1.
Os trechos de §39 que citam `MIC_RAW` descrevem o estado antes desta decisão.

**Confirmado depois (mesmo dia):** o criador configurou o OBS no arranjo de 3 faixas (`AUDIO_GAME` em 1 e 2, `MIC` em 1 e 3)
e a gravação de 10 s `2026-11-16 18-40-07.mp4` mediu: faixa 1 −26,1 dB, faixa 2 (jogo) −43,1 dB, faixa 3 (microfone)
−26,2 dB (pico −8,5): a faixa 3 tem sinal. O jogo estava baixo; combinado subir o ganho dele em vez de abaixar a voz.

**Ferramenta de supressão de ruído (2026-11-16):** o criador não usa RNNoise no OBS; a limpeza do microfone é o **ClearCast
AI do SteelSeries Sonar** (dispositivo virtual de entrada), ajustado para ~50% (era ~75%; ⚠️ o limite de ~50% vem de uma guia
de terceiros, não da SteelSeries), com gate e compressor do Sonar desligados e um **Limitador** no OBS (−6 dB, liberação 60 ms,
de memória) para gritos. Onde esta decisão e o plano dizem "RNNoise", leia "supressão de ruído na origem" (ClearCast ou RNNoise,
**um só, nunca os dois**). A configuração do Sonar fica fora do repositório: registrar os valores neste histórico se mudarem.

**Marcação com teclado de 60% (2026-11-16):** o criador usa teclado 60%, sem F13–F24, e disse que programar e decorar
vários comandos seria difícil. **Decisão para a gravação de teste de 30 min: só a tecla nativa do OBS** ("Adicionar marcador
de capítulo", ligada à tecla Menu), sem o gravador do app. Resultado esperado: capítulos "Sem nome N" que o ingest já
converte em `momento` com aviso; **sem `novo_dia` e sem tipos** (o dia fica implícito). Isso contradiz a regra de que
`novo_dia` é obrigatória (`CLAUDE.md`, plano seção 4) e fica **em aberto** (plano, seção 9): como marcar o início do dia e os
tipos de momento com poucas teclas, sem decorar atalhos (ex.: uma tecla só e o tipo decidido depois na revisão; uma
tecla de dia; marcar por voz). O gravador do app e a conexão com o OBS (WebSocket) continuam funcionando e testados.

---

## 42. Plano de execução da Fase 2 (2026-11-16)

Origem: com a 1C na `main` (PR #6), o criador pediu para seguir as fases; a Fase 2 ainda não tinha `docs/fase-2-*.md`.

**Decisão:** a Fase 2 é dividida em **2A** (lacunas técnicas 2–4, sinais de energia/novidade/periodicidade em CPU, portas de
VAD/transcrição/eventos com fakes, relatório HTML; roda em `dev` e `prod`), **2B** (ambiente de ML, adaptadores reais e
benchmark de desempenho; só `prod`) e **2C** (qualidade contra o gabarito, escolha dos modelos e benchmark de roteiro do
`LocalScriptProvider`; **bloqueada pelo gabarito anotado**). Motivo: separar o que é verificável sem gabarito do que depende
dele, para não parar a fase inteira esperando as 2–3 h de anotação. Plano em [fase-2-analise-de-audio.md](fase-2-analise-de-audio.md).

**Propostas dentro do plano, ainda não decididas pelo criador:** formato dos sinais (`.npy` float32 no cache, grade de 6
quadros = 10 Hz, sem tabela no banco); tabela `event` com a evidência embutida (a 5A a normaliza); coluna `variant` em
`artifact` e `job`; números de corte da 2C (WER ≤ 15%, no máximo 1 evento falso de teclado/respiração a cada 10 min, ≥ 70% das
rotinas detectadas). Os cortes precisam ser validados com o criador antes do benchmark final (item 8 de "Em aberto").

---

## 43. Fase 2A implementada (2026-11-16)

Aprovado pelo criador o plano do §42 ("Aprovar e começar 2A"), a 2A foi feita na branch `fase/2-audio`. As propostas do §42
sobre formato de sinais, tabela `event` e coluna `variant` **viraram decisão** ao serem implementadas; os números de corte da
2C continuam propostas.

**O que existe:** `variant` em `artifact` e `job` com unicidade por `(arquivo, etapa, variante)` (migração 0005); a variante vira
pasta no cache e só aceita `[A-Za-z0-9._-]`; `needs`, relatório e logs usam `nome:variante`. `Evidence`/`AnalysisEvent` e a tabela
`event` (0006), em que reexecutar uma etapa substitui só os eventos da própria execução. Sinais como `.npy` float32 na grade de 6
quadros (10 Hz): `game.energy_db`, `game.onset`, `game.novelty`, `game.periodicity`, `mic.energy_db`, `mic.energy_rel_db`, todos
relativos à sessão (mediana móvel de 5 min), sem nada por jogo. Portas `SpeechDetector`, `Transcriber`, `SoundEventClassifier`
(adaptadores reais só na 2B), etapas `speech` e `sound_events` (no microfone só risada e grito; o mix nunca é analisado),
`cronista analyze <sessão>` e `cronista report <sessão>` (HTML único, sem rede, com texto escapado).
Dependências novas: `numpy` e `soundfile` (libsndfile 1.2.2, que lê RF64).

**Medido com a gravação real (`claude_teste.mp4`, 37 min, `prod`):** sinais em ~8 s (10 min sintéticos: 1,1 s; extrapolação
para 10 h: ~1 min); o banco de `data/prod` migrou sem perder linhas. Faixa do microfone com mediana −51,7 dB e picos de −12 dB
(fala presente); novidade do jogo com mediana 0 e p99 11; periodicidade com mediana 0,22 e máximo 0,63. **Ainda não dizem se
detectam rotina ou fala de verdade:** isso é a 2C, com o gabarito.

**Achado da validação real:** dois dos três arquivos da sessão 1 (`Cronista_Teste.mp4`, `testeia.mp4`) já não existem na pasta de
gravação. O `analyze` quebrava com traceback; agora é falha clara por arquivo (a sessão continua nos demais). O banco ainda os lista.

**Não verificado:** CI no GitHub (Ubuntu e Windows); RF64 acima de 4 GB e uso de memória em sessões de horas; retomada após
interrupção específica da análise; `Evidence`/`AnalysisEvent` ainda fora do JSON Schema dos contratos (o Studio só chega na Fase 7).

---

## 44. Fase 2B: modelos reais e benchmark de desempenho (2026-11-16)

O criador autorizou a instalação ("permissao para instalar"), depois de ver a lista de modelos e os tamanhos estimados.

**Decisão de ambiente: um só.** Os modelos entram como grupo opcional `ml` do engine (`uv sync --group ml`), fora do `uv sync`
da CI e do `dev`; PyTorch vem do índice `cu128` da PyTorch (`[tool.uv.sources]` só para `torch` e `torchaudio`). Silero (PyTorch),
faster-whisper (CTranslate2, CUDA) e o classificador (PyTorch, CUDA) rodaram em sequência **no mesmo processo** na RTX 3060, sem
conflito de DLL: a exceção do CTranslate2 (plano, seção 5.2) **não precisou de processo separado**. A 1C já tinha testado as duas
ordens de importação num ambiente descartável. `audio_models: true` só em `config/prod.yaml`; sem o grupo `ml`, `cronista analyze`
volta aos sinais de CPU e avisa o que não rodou.

**Versões verificadas:** driver NVIDIA 610.88 (CUDA 13.3), torch 2.11.0+cu128, torchaudio 2.11.0+cu128, ctranslate2 4.9.0,
faster-whisper 1.2.1, silero-vad 6.2.3, transformers 5.23.0, onnxruntime 1.32.0, huggingface-hub 2.4.0, psutil 7.2.2.

**Modelos (em `data/prod/models/`, fora do git):**

| Modelo | Origem | Tamanho medido | Licença (⚠️ de memória, conferir) |
|---|---|---|---|
| Silero VAD | pacote `silero-vad` (modelo embutido) | ~2 MB | MIT |
| faster-whisper `large-v3-turbo` | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (Hugging Face; conversão CT2 dos pesos da OpenAI) | 1,6 GB | MIT |
| AST AudioSet | `MIT/ast-finetuned-audioset-10-10-0.4593` (Hugging Face) | 331 MB | BSD-3-Clause |

Classificador de eventos: o primeiro candidato é o **AST** (AudioSet, 527 classes, com Laughter, Screaming, Typing, Breathing,
Explosion, Music), porque é o que mais rápido vira medida com `transformers`; PANNs, BEATs e CLAP continuam candidatos da 2C. Tem
resolução de 2,5 s (janela de 10,24 s com passo de 2,5 s): marca onde há o evento, não corta com precisão.

**Desempenho medido** (`cronista bench-audio 1 --minutes 10`, primeiros 10 min de `claude_teste.mp4`, RTX 3060, `prod`):

| Modelo | Faixa | x tempo real | 10 h de sessão em | VRAM (pico, com pesos) |
|---|---|---|---|---|
| Silero VAD (CPU) | microfone | 79 | ~8 min | ~0 |
| faster-whisper large-v3-turbo (int8_float16) | microfone | 34 | ~18 min | ~1,3 GB |
| AST AudioSet | microfone | 116 | ~5 min | ~0,9 GB |
| AST AudioSet | jogo | 121 | ~5 min | (modelo já carregado) |

Análise completa da sessão real (`cronista analyze 1`, 37 min, os três modelos mais os sinais): **3m14**, incluindo carregar os
modelos. Saída: 550 falas (1158 s), 15 eventos de música no jogo, 0 de risada/grito no microfone. A transcrição é PT-BR coerente
em amostra (conf. média 0,80); **a qualidade só se mede na 2C com o gabarito**. O Whisper roda só nos trechos de fala (54% do
trecho medido), então o "x tempo real" depende de quanto o criador fala. As estimativas de 10 h são **extrapoladas de 10 min**,
não medidas em 10 h reais.

**Correção de método:** a primeira medição de VRAM lia a linha de base depois do aquecimento e deixava os pesos de fora (Whisper
aparecia com 210 MiB). A linha de base agora é de antes da carga.

**DeepFilterNet:** instala (0.5.6), mas rebaixa o NumPy 2.5 do projeto para 1.26 e o `packaging`. Não entra no ambiente principal;
vira teste da 2C num ambiente descartável.

**Achados do `/code-review` da 2B:** o índice `cu128` vale só no Windows (`marker` em `[tool.uv.sources]`; em outras plataformas o
`torch` vem do PyPI) e o grupo `ml` ganhou limites de versão (`torch>=2.11`, `transformers>=5.23,<6` etc.). O Silero devolve tempos
em amostras (÷16000), porque em segundos ele arredonda a 0,1 s; a fusão de trechos vale só na fronteira entre blocos. O custo de
extração de atributos do AST em CPU (janelas sobrepostas ~4×) **não foi tratado**: as estimativas de 10 h podem estar otimistas.

**Não feito na 2B:** pausa com o OBS gravando de verdade (precisa do criador gravando); 10 h reais de áudio; cobertura
`@pytest.mark.gpu` rodada (os testes existem em `tests/test_adapters_gpu.py`, ver resultado no PR).

---
## 45. Plano de execução da Fase 3 (2026-11-17)

A Fase 3 ganhou plano próprio em [fase-3-analise-de-video.md](fase-3-analise-de-video.md), dividido como a Fase 2: **3A** (frames do proxy,
cenas, sinais visuais e heurística universal de menu/loading/idle, CPU), **3B** (embeddings SigLIP/CLIP, contexto visual, linha de base do
áudio por contexto, B-roll) e **3C** (perfis YAML, OCR de HUD no master, VLM só em candidatos, métricas contra o gabarito). Números de
corte propostos (menu/loading ≥ 90% de precisão sem perfil de jogo etc.) **ainda não decididos**: precisam da aprovação do criador antes
do benchmark final. Pendências do criador: classes visuais no gabarito, segundo gênero de jogo, download dos modelos novos e a marcação
de `novo_dia` com teclado de 60%. Nada implementado.

## 46. Exclamação no lugar de grito (2026-11-17)

**Decisão do criador:** deixar de separar grito de fala empolgada. A classe `exclamacao` ("exclamação ou grito de emoção alta")
substitui `grito` no gabarito e nos eventos do microfone; `grito` continua aceito como apelido legado (vale como `exclamacao`).
Para a edição interessa achar os momentos de emoção alta, não rotular o tipo.

**Evidências (2C, dois testes de voz do criador, `data/gabarito/teste-voz.csv` e `gritos_risadas.csv`):**
- AST (janela de 10,24 s) não pontuou nenhum grito (0 de 4); com janela de 2 s continuou em 0,01 a 0,11 contra no máximo 0,02 fora dos gritos.
- O limitador do OBS achata o pico em cerca de -6 dBFS; o nível médio (RMS) ainda separava o grito da fala normal no primeiro teste (+10 dB), mas **não** no segundo (falas de anúncio tão altas quanto os gritos).
- Altura da voz (f0): grito 330–410 Hz no primeiro teste; a "fala alta em tom agudo" do segundo teste tem 333 Hz, igual a um grito. Separar por regra simples não generaliza (detector de grito por energia e f0: 4 de 4 no primeiro teste, 0 de 8 no segundo).
- Risada: AST com janela de **2 s** (hop 0,5 s) sobe de 0,12 para 0,2–0,52 nos trechos anotados, contra no máximo 0,10 fora. O microfone passa a usar um segundo classificador com essa janela (`AudioModels.mic_classifier`).
- Teclado e respiração: 0 eventos falsos nos dois testes; o AST vê os dois (0,82 e 0,87), mas o código os descarta no microfone por desenho.
- WER: 13,3% (556 palavras) no primeiro teste e 0% (59 palavras) no segundo. **Otimista:** o criador corrigiu as sugestões do Whisper em vez de transcrever do zero.

**Estado:** a etapa `sound_events` do microfone ganhou uma variante CPU (`ScreamHeuristic`, energia relativa à sessão mais f0) que emite `exclamacao`;
ela acerta o primeiro teste (4 de 4) e erra o segundo (0 de 8, ali a linha de base da sessão fica inflada porque o trecho todo é alto).
**Experimental, sem número de corte aprovado.** Falta um gabarito de `exclamacao` marcado como tal (fala empolgada também conta) e uma sessão longa realista.

## 47. Fase 3A parcial: sinais visuais e estados de tela (2026-11-17)

Decisão do criador (2026-11-17): **concluir a codificação do projeto primeiro e fazer os ajustes de qualidade depois**; por isso a Fase 3
começou antes de fechar a 2C. A fusão em camadas (fala + risada + exclamação + respiração + intensidade) fica para a Fase 4.

Implementado em `cronista/video/`: leitor de quadros do proxy por pipe do FFmpeg (cinza 160x90 a 5 fps, hop de 12 quadros a 60 fps, em blocos);
sinais `motion`, `still`, `luma_mean`, `luma_std`, `edge_density`, `shift` e `shift_conf` (deslocamento global por correlação de fase, sem OpenCV)
e `hist_diff` (corte de cena por histograma, sem PySceneDetect); heurística universal `loading` (tela escura parada), `menu` (tela parada com muitas
bordas), `idle` (tela parada e lisa), `movimento_camera` (`parada`/`panoramica`) e `cena`. Etapas `video_signals` e `video_scenes`, ambas em CPU
e incluídas no `cronista analyze`. `pausa` ficou para a 3B (precisa de embeddings); `orbita` ainda não.

Verificado em vídeo sintético com verdade de campo (`devtools/synthetic_video.py`): loading, menu e idle detectados, sem falso positivo na jogabilidade.
**No `claude_teste.mp4` (37 min) a análise leva cerca de 24 s** (≈ 90× o tempo real) e gera 214 eventos (28 menus, 10 loadings, 9 idles); **os números não foram
conferidos contra gabarito nem de olho**, só a plausibilidade. Limiares são pontos de partida, sem corte aprovado (a 3C calibra).

**Relatório de vídeo:** `cronista report` ganhou a seção "Vídeo" (estados de tela sobre o tempo, gráficos de movimento, parada, bordas e brilho, e tabela com miniatura do quadro do meio dos trechos mais longos de loading, menu e idle). `analyze --only audio|video` limita a análise.

**Conferência de olho do criador no `claude_teste.mp4` (2026-11-17):**
- **loading:** os 6 trechos mostrados eram cena escura de jogo com HUD (brilho 0,04–0,09), nenhum era loading. Corte apertado (brilho < 0,03 e quase nenhum movimento); no mesmo vídeo caíram de 10 para 0 trechos. Não há medida de revocação de loading real (talvez o vídeo não tenha nenhum).
- **menu:** os 6 trechos mostrados eram menus de verdade. Observação do criador: **menu de configuração e inventário não têm a mesma relevância**. A heurística só diz "tela de interface parada"; o **tipo** do menu (configuração, inventário, diálogo, mapa) e o peso de cada um na relevância ficam para a 3B/3C (embeddings agrupando menus parecidos, VLM só para nomear) e para a Fase 4.
- **idle:** os trechos mostrados eram páginas de texto escuras e um inventário sobre o jogo, não "personagem parado". Com bordas e parada não se separa uma coisa da outra. `idle` ficou **desligado por padrão** (`ScreenParams.idle_enabled`) até a 3B. Limite de fundo: em 160x90 o texto pequeno some; se faltar resolução, subir para 320x180 (custo a medir).

## 48. Fase 3B parcial: embeddings, contextos e linha de base por contexto (2026-11-17)

Implementado sem baixar modelo nenhum (verificado em CPU, com embedder falso e vídeo sintético):

- **Porta `FrameEmbedder`** (`video/ports.py`): embeddings normalizados, `embed_images` com `pause` entre lotes (gate de GPU) e `embed_text` no mesmo espaço. `VideoModels` leva o embedder; sem ele, só a 3A roda.
- **Etapa `video_embeddings`** (GPU): 1 quadro por segundo do proxy, RGB esticado para o quadrado do modelo (224), gravado em `.npy` `float16` (N x D). Só a referência vai no `result.json`.
- **Contextos** (`video/contexts.py`, etapa `video_contexts`, CPU): **decisão: agrupamento incremental "líder" por cosseno com limiar (0,85) e centróide móvel**, filtro de moda nos rótulos (5 amostras) e poda de contexto com menos de 20 s (vira "sem contexto"). Determinístico e linear; HDBSCAN fica como alternativa se a conferência de olho mostrar contextos instáveis. Saída: eventos `contexto` (id, confiança, quadro representativo) e o sinal `video.context` a 1 Hz.
- **`game.novelty_ctx`** (etapa `context_novelty`): `novelty` recalculada com a mediana móvel **dentro de cada contexto**, como variante ao lado de `game.novelty` (não a substitui). Contexto com menos de 120 s de áudio mantém a linha de base da sessão, com aviso. Só roda quando áudio e vídeo são analisados juntos (sem `--only`). Aparece no relatório.
- **Adaptador `SiglipEmbedder`** (`video/adapters/siglip.py`): **escrito, não verificado** (sem GPU nem checkpoint nesta máquina). Fica desligado: só carrega se `video_embedder` (ex.: `google/siglip-base-patch16-224`) estiver na configuração, o que também autoriza o download. Escolha SigLIP x CLIP, versões e desempenho dependem do benchmark em `prod`.


**Rodado em `prod` (SigLIP `google/siglip-base-patch16-224`, `claude_teste.mp4`, 37 min):** embeddings em cerca de 1 min na RTX 3060; 11 contextos (os quatro maiores cobrem ~1950 s de 2245 s, 43 s sem contexto). **Conferência de olho dos quadros representativos:** caverna escura (972 s), diálogo com NPC/missão (399 s), floresta (332 s) e inventário (247 s) — coerentes. O relatório ganhou a faixa `contexto` e a tabela "Contextos visuais" com miniatura. Ajustes do adaptador no `transformers` 5: normalização própria dos quadros (sem Pillow/torchvision), tokenizer só na busca por texto (precisa de `sentencepiece`, não instalado) e leitura de `pooler_output`. SigLIP x CLIP ainda não comparado; tempo de 10 h e VRAM ainda sem medir (`bench-video`).

**Decisão do criador (2026-11-17):** **não instalar o Ollama.** O VLM local da 3C será testado pelo `transformers` (já no ambiente `ml`), com quantização em 4 bits se o bitsandbytes funcionar no Windows; se não funcionar, o VLM sai do escopo ou usa um modelo que caiba em 12 GB sem quantizar (⚠️ a verificar). Isto substitui "Ollama + Qwen-VL" na seção 5.2 do plano e na 3C. O benchmark ampliado (embeddings pesados, fala, eventos sonoros, VLM, OCR, resolução; sem roteiro) segue em etapas, com tabela e registro aqui.

**Benchmark de embeddings de quadro (`bench-video`, `claude_teste.mp4`, 37 min, 1 quadro/s, RTX 3060; gabarito pequeno de 4 cenas com rótulos vindos do SigLIP base, então o kNN não separa os modelos):**

| Modelo | 10 h em | VRAM | kNN | Zero-shot |
|---|---|---|---|---|
| clip-b32 | ~24 s | 0,7 GB | 0,94 | 0,38 |
| siglip-base | ~1 min | 1,3 GB | 0,93 | 0,58 |
| siglip2-base | ~1,3 min | 1,9 GB | 0,93 | 0,64 |
| clip-l14 | ~5 min | 2,4 GB | 0,92 | 0,61 |
| siglip-so400m | ~22 min | 5,8 GB | 0,93 | 0,55 |
| siglip2-large | ~11 min | 3,9 GB | 0,92 | 0,77 |
| siglip2-so400m | ~23,5 min | 6,5 GB | 0,92 | 0,68 |

`siglip2-giant` travou na carga e não foi medido (não entraria no pipeline). Tamanho não garante ganho (SigLIP 1 so400m pior que o base). **Proposta (a confirmar com uma busca real):** `siglip2-base` nos contextos (todos os segundos) e `siglip2-large` só na busca por texto de B-roll (trechos candidatos). Tempos excluem a decodificação do proxy. O `bench-video` passou a gravar o JSON a cada modelo.
**Falta da 3B:** rodar em `prod` com o checkpoint (autorização do download), conferir contextos de olho no `claude_teste.mp4`, B-roll (tabela `broll_clip`, beleza, busca por texto), tipo de menu e `idle`, HUD oculto, `bench-video` e a seção do relatório (mapa de contextos).

## 49. Benchmarks de modelos (2026-11-17)

Cinco benchmarks automáticos, com relatórios em [`docs/benchmarks/`](benchmarks/00-recomendacoes.md) (tabelas geradas por `cronista bench-report`, análise à mão): embeddings de quadro (`bench-video`), fala e eventos sonoros (`bench-audio-quality`), estado de tela, OCR de HUD e resolução (`bench-vision`). Candidatos pedidos pelo criador: as "opções mais pesadas" por etapa, exceto roteiro.

**Resultados e escolhas propostas (a confirmar numa sessão longa e real):** `siglip2-base` nos contextos e `siglip2-large` só na busca de B-roll por texto; Whisper turbo continua (1,1% de erro contra 3,1% do large-v3, com viés: o gabarito nasceu das sugestões do turbo); risada com AST de 2 s; exclamação com CLAP é candidata, não adotada (revocação 63% contra 0% da heurística, precisão 29–36%); estado de tela por VLM `qwen3vl-4b` em 360p só nos trechos duvidosos (todos os VLMs acertaram 100%: teste saturado, falta gabarito de loading/idle/cinemática); **OCR do HUD com RapidOCR no master em 720p** (100% de acerto, 0,33 s, CPU; em 360p nenhum leitor lê o HUD).

**Substitui:** o VLM da 3C deixa de ser "Ollama + Qwen-VL" e passa a rodar pelo `transformers` (histórico §48, sem Ollama). Pacotes novos no grupo `bench` do `pyproject.toml` (Pillow, torchvision, accelerate, bitsandbytes, RapidOCR) e `sentencepiece` no `ml`.

**Não testados:** Parakeet/Canary (multilíngue exige NeMo), BEATs, PANNs, DINOv2, SigLIP 2 giant (travou), PaddleOCR-VL. Correções feitas no caminho: WER por palavra com tempo (o large-v3 dava 217% por agrupar frases), tempo sem o download do modelo e VRAM pelo medidor do PyTorch.

## 50. Fase 3B: biblioteca de B-roll (2026-11-17)

Etapa `video_broll` (CPU, depois de `video_scenes` e `video_embeddings`) e `cronista broll-search`. **Candidato** = `movimento_camera` parada ou panorâmica com pelo menos 4 s e menos de 30% coberto por menu/loading/pausa/idle. **Beleza** zero-shot: probabilidade de o embedding médio (por segundo) parecer mais com prompts positivos ("a beautiful scenic view"...) que negativos ("a menu screen full of text"...); serve para ordenar, não para decidir. **Tags** = 3 rótulos mais próximos de um vocabulário fixo e genérico (caverna, floresta, lago, base...), sem nada por jogo. Saída: eventos `broll` (confiança = beleza; `payload` com movimento, tags e quadro de capa), reaproveitando a tabela `event` **em vez de uma tabela `broll_clip` nova** (mesmo conteúdo, sem migração; reavaliar na Fase 6 se precisar de mais campos). Busca por texto: cosseno do embedding médio do trecho com o texto (consulta em inglês). O relatório ganhou a galeria "B-roll candidato" (12 melhores, com capa).

Em `prod` (SigLIP base, `claude_teste.mp4`): 20 candidatos em ~35 s; buscas "a cave" e "a lake" devolveram trechos com tags coerentes, **ainda sem conferência de olho das capas**. Os candidatos têm 4–7 s (a câmera quase não fica parada mais tempo). **Correção do criador (mesma data):** beleza absoluta é o critério errado; para narrar algo perigoso, a caverna de aranha (2237 s) serve melhor que a paisagem de 1987 s, e meus prompts "imagem escura e borrada" a derrubaram para 0,01. A nota passou a **utilidade** (cena de jogo contra menu, inventário, tela preta e loading; 2237 s foi para 0,74) e a adequação ao assunto fica com a busca por texto. **Regra de produto:** sob a narração o B-roll **alterna** em sequência (nova tomada a cada 4–7 s, sem repetir nem contextos parecidos em seguida, primeira por busca de texto, demais do tema ou cenas calmas); o montador é da Fase 6. **Pedido do criador (mesma data):** o B-roll sempre deve fazer sentido com a narração; sem tomada à altura o app marca "falta tomada" e **sugere gravar** (ex.: Replay Mod no Minecraft, modo diretor no GTA), com a ferramenta vinda de `camera_tools` no perfil do jogo (3C) e, sem perfil, a sugestão genérica "câmera livre". Implementação com o roteiro (Fase 5) e o montador (Fase 6).

**Pedido do criador (mesma data, 2):** para ilustrar a **abertura** (narração que explica o desafio) ou partes do vídeo, interessa **variedade**: partes bonitas, sombrias, inimigos. Decisão: cada tomada recebe um **clima** (`bonito`, `sombrio`, `perigoso`, `calmo`; zero-shot, prompts genéricos em `broll.py`) além do tema; o montador pede mistura de climas na abertura e um clima específico quando a narração pede. Tomadas de inimigo/ação têm movimento: virão dos momentos detectados (combate, intensidade, eventos sonoros) na Fase 4, não só de câmera parada. No `claude_teste.mp4`: 19 sombrias, 1 bonita, 0 perigosas (a sessão é quase toda caverna e noite): a biblioteca é pobre em variedade, o que alimenta as sugestões de gravação.

**HUD oculto (mesma data):** etapa `video_hud` (CPU) e campo `hud` (`oculto`/`visivel`/`desconhecido`) em cada B-roll. Método universal: a sessão inteira define um **gabarito** (pixels estáveis, com borda, dilatados em 3 px; mediana de 1 amostra a cada 8 s) e cada segundo mede a fração do gabarito que ainda bate; trecho de pelo menos 6 s com quase nada batendo (< 0,15), fora de menu/loading/pausa/idle, vira evento `hud_oculto` de confiança ≤ 0,5. No `claude_teste.mp4`, com corte 0,5 saíram 7 trechos, **todos falsos**: painéis de interface (talentos, livro de missões, configurações, escolha de arma) abertos sobre o jogo, que cobrem parte do HUD (match 0,24 a 0,45) mas não o escondem; densidade de bordas não separa (0,04 a 0,10 contra 0,03 a 0,11 das cenas limpas). Com corte 0,15 saem 0 trechos, coerente com a sessão (HUD nunca escondido). **Não validado com HUD escondido de verdade**: gravar ~30 s com F1 (Minecraft) ou sem HUD (modo diretor/Replay Mod) para provar a revocação; até lá a detecção é experimental e todo B-roll sai `visivel`.

**Tipos de menu (mesma data):** etapa `video_menu_types` (CPU, depois de `video_scenes` e `video_embeddings`) e eventos `menu_tipo` (id do tipo, menus no tipo, menu representativo), mais a tabela "Tipos de menu" no relatório (contagem, tempo total, miniatura). Cada menu da 3A vira o embedding médio do trecho; **subtrai-se a média de todos os menus** antes do agrupamento "líder" por cosseno (limiar 0,3 depois de centrar). Sem centrar, chat e inventário ficavam juntos mesmo a 0,95 (cosseno 0,85 entre eles, o fundo escuro e os painéis dominam). No `claude_teste.mp4`: 28 menus em 7 tipos, todos puros de olho (inventário com 14 menus, configurações de vídeo, chat, diálogo/missão, árvore de talentos); o inventário ficou dividido em 3 tipos (excesso pequeno). **O tipo não tem nome**: nomear (configuração, inventário, diálogo, mapa) é uma pergunta por grupo para o VLM na 3C ou para o criador; o peso por tipo na relevância é da Fase 4. **`idle` de volta (mesma data):** etapa `video_idle` (CPU, depois de `video_signals` e `video_hud`) e série `video.hud_match` (1 Hz, gravada pela `video_hud`). Definição nova: **cena parada** (`still` >= 0,90, fora de tela escura) **com o HUD do jogo inteiro à vista** (`hud_match` >= 0,9) por pelo menos 10 s. Painel, chat e telas de boas-vindas cobrem parte do HUD, então não contam; a `idle_enabled` da 3A segue desligada (substituída). Sem HUD estável na sessão, idle não é detectável (aviso). No `claude_teste.mp4`: com corte 0,8 saíram 3 trechos, 1 idle verdadeiro (personagem parado diante de um NPC, 358 s, match 0,96) e 2 falsos (tela de boas-vindas do modpack, match 0,83; diálogo longo no chat, 0,85); com 0,9 sobra só o verdadeiro. **Uma sessão, um acerto, sem controle negativo amplo:** recalibrar com o gabarito da 3C (precisa de idle marcado, que o `gabarito-ui` permite sem gravar nada novo). **Correções do /code-review:** máscara do HUD com `stable_frac` 0,5 (HUD escondido em até metade da sessão ainda é detectável), o que baixou o `hud_match` máximo de uma cena limpa para ~0,89 e levou o corte do idle a 0,85 (o idle de 358 s segue sendo o único); chave explícita `has_hud` na `video_hud`; menus: com menos de 4 menus usa limiar bruto 0,93 em vez de colapsar; B-roll calcula os textos uma vez e passa pelo gate de GPU; `broll-search` recusa embeddings de outro modelo; idle antigo da 3A removido. Com isso a 3B fica completa em código; falta conferir o que ainda depende de olho.

**Teste da busca por texto (SigLIP 2 base x large, `claude_teste.mp4`, 20 B-rolls):** a caverna de aranha (2237 s) ficou em 10º (base) e 9º (large) para "a dark spider cave"; "lago ao pôr do sol" e "vila" acertaram nos dois. O quadro é quase todo escuro, com HUD à vista, e a única pista de aranha é o texto "spider_caves" do minimapa: o limite é o conteúdo da imagem, não o tamanho do modelo. Conclusões: manter `siglip2-large` só na busca (ganho pequeno, não provado); usar o **OCR do HUD** (bioma no minimapa) e o **VLM** (3C) como pistas extras de tema; tomada com HUD à vista é a que o app deve **sugerir regravar** (Replay Mod/modo diretor).

Falta da 3B: conferir B-roll de olho, tipo de menu, `idle`, HUD oculto.

*As decisões da Fase 3C (3C-1 a 3C-4), que ficavam aqui, passaram para o §50A.*

## 50A. Fase 3C: perfis, gabarito visual, OCR do HUD e VLM (2026-11-17)

Estas decisões estavam dentro do §50 (Fase 3B, B-roll) e foram separadas em 2026-11-19 (Fase 10D, F20), sem mudar o texto.
A numeração fica como estava, para não quebrar as referências "§50" já escritas; o §50A vem logo depois do §50.

**Fase 3C-2, perfis e plugabilidade (2026-11-17):** `cronista/profiles.py` com `GameProfile` (Pydantic; `extra=forbid`): `hud_regions` (retângulo relativo, leitura `text`/`number`/`icon`, `tag_theme`), `thresholds` por grupo (`screen`, `hud`, `idle`, validados contra os campos dos parâmetros do núcleo), `context_labels`, `camera_tools`, `objetivos`, `regras`. Perfil `generico` embutido (não acrescenta nada); `apply_thresholds` devolve cópia dos parâmetros. `profiles/exemplo.yaml` (Minecraft, só dados, valores ilustrativos) e `profiles/profile.schema.json` gerado (`python -m cronista.profiles`). **Teste de plugabilidade:** falha se qualquer módulo do núcleo (exceto `profiles.py` e a CLI) importar `cronista.profiles` ou citar um jogo ou perfil. Ainda **não ligado às etapas** (isso entra com a 3C-3/3C-5, via `Settings.profile`).

**Fase 3C-1, gabarito visual e métricas (2026-11-17):** classe `hud_oculto` no gabarito; `cronista gabarito-ui <sessão> --visual` gera a página com os **candidatos visuais** (menu, loading, idle, hud_oculto) já com miniatura do meio do trecho (confirmar com ✓, corrigir bordas, apagar com ✕, marcar o que faltou); `cronista bench-video-quality <sessão> <gabarito.csv>` imprime por classe anotados, previstos, casados, precisão, revocação, erro médio de bordas, pares dentro da tolerância (padrão 2 s) e falsos a cada 30 min (`video/quality.py`, funções puras). Casamento guloso pelo maior encavalamento. Correções no caminho: `video_idle` não estava em `VIDEO_STAGES` (idle não aparecia no relatório nem nos candidatos); atalhos numéricos do anotador quebravam com 10 classes. **Linha de base ainda não medida:** falta o criador anotar o gabarito visual do `claude_teste.mp4` (28 menus e 1 idle candidatos; nenhum `loading`/`hud_oculto` detectado hoje).

**Fase 3C-3, OCR do HUD (2026-11-17):** porta `HudReader` (+ `HudRegionSpec`, o que o núcleo vê do perfil) e adaptador `RapidOcrReader` (CPU, ONNX; versão a conferir em `prod`). Etapa `video_hud_text` (`video/hud_text.py`): lê **só as regiões do perfil** em quadros do **master a 720p**, um a cada 5 s (`iter_frames_every`; `spans_s` limita a trechos pedidos); regiões `text`/`number` (`icon` é ignorado com aviso); eventos `hud_texto` com a citação em `quote`, fundindo leituras iguais seguidas. Perfil genérico ou sem `rapidocr` = etapa não entra. Ligação: `Settings.profile` (e `profiles_dir`) + `profiles.build_models_with_profile`, usado pelo `analyze`. **Tema do B-roll:** região com `tag_theme` (ex.: bioma do minimapa) vira tag do B-roll que ela cobre (`theme_tags`; `video_broll` depende de `video_hud_text` só quando a etapa existe). Testado só com leitor falso; **falta medir o acerto (meta ≥ 90%) com RapidOCR real**, e as coordenadas do `exemplo.yaml` são ilustrativas: precisam ser medidas num quadro do master.

**Fase 3C-4, VLM local em perguntas fechadas (2026-11-17), só código, sem baixar o modelo:** porta `ScreenVLM` e `video/vlm.py`: cada `Question` lista as opções e pede `{"answer": "<opção>"}`; a resposta é validada por Pydantic (modelo `Literal` gerado das opções, que também dá o JSON Schema) e, se vier texto, só vale se citar **uma** opção; fora disso é inválida (`None`), nunca palpite. Perguntas prontas: `MENU_KIND`, `SCREEN_STATE` (desempate de estado de tela) e `ENEMY_PRESENT` (confirmar tema de B-roll). Etapa `video_menu_names` (GPU, depois de `video_menu_types`): **uma pergunta por tipo de menu**, no quadro representativo a 360p, evento `menu_nome`. Adaptador `QwenVL` (`transformers`, 4 bits opcional) **não baixa nada ao construir**: os pesos só vêm na primeira pergunta e só se `vlm_model` estiver na configuração (`Settings.vlm_model`, `vlm_4bit`). Testado só com VLM falso. **Pendente:** autorização do criador para baixar o Qwen3-VL 4B (tamanho a registrar antes), medir acerto no `claude_teste` contra o gabarito e ligar (b) e (c) a etapas.

## 51. Fase 4: motor de relevância, primeira versão por regras (2026-11-17)

**Decisão do criador:** terminar a codificação de todas as fases primeiro e só depois calibrar (3C-5 e ajustes finos ficam para depois do gabarito). Branch `fase/4-relevancia`, a partir da 3C. `relevance/` (puro, CPU): grade de 1 s com fala, emoção, menu/loading/idle e contextos; **lookback por tipo de marcador** (momento 25 s, engraçado/conquista 20 s, morte 30 s) encostado em fronteiras naturais; nota explicável (`marcador 0,5 + emoção 0,2 + fala 0,15 + novidade 0,15 − pausa 0,5`, pesos iniciais); classes `momento`, `dia`, `conversa`, `farm`, `jogo`, `descartavel`. Segmentos viram eventos `segmento`. Comandos `cronista relevance`, `bench-relevance` e `series` (painel em texto: minutos estimados de produto por sessão e acumulado). No `claude_teste` (37 min): 85 segmentos, os 2 marcadores viraram os 2 momentos de topo; farm não aparece (a sessão não tem trecho calado longo). Pesos e limiares são provisórios; seleção dentro de fala longa e tentativas repetidas esperam a 5A. Plano: [fase-4-motor-de-relevancia.md](fase-4-motor-de-relevancia.md).

## 52. Fases 5 e 5A: narrativa, objetivos e roteiro, primeira versão (2026-11-17)

Branch `fase/5-roteiro`, a partir da Fase 4. Código sem modelo nem Claude: a 5A (objetivos com evidência) e a Fase 5 (arco, story-pack, roteiro) rodam em `dev`. Decisões: (1) evidência **embutida** nas tabelas de estado e evento (`ev_*`) em vez da tabela `evidence` normalizada do §37, que fica para o Studio; (2) **declaração não é conclusão**: `concluido` só com marcador de conquista por perto, senão `incerto` e vai para a fila de revisão; citação que não confere é descartada; (3) o roteiro vem do **Claude Code** (skills `/roteirizar` e `/humanizar` versionadas em `.claude/skills`), validado por `cronista roteiro-import`; `LocalScriptProvider` fica experimental e o `NullProvider` é o padrão; (4) fala ao vivo tem prioridade: o pacote traz as falas e as **lacunas livres** e a validação avisa quando a fala não cabe. No `claude_teste`: 1 capítulo de 7 trechos relevantes, 18 hipóteses de objetivo (17 na fila de revisão) e perfil de voz coerente (bordões "a gente", "acho que", "isso aqui"). Pendentes: gabarito e números de corte da 5A, LLM local, eventos e relações automáticos. Plano: [fase-5-narrativa-e-roteiro.md](fase-5-narrativa-e-roteiro.md).

## 53. Fase 6: plano de montagem e exportação (2026-11-17)

Branch `fase/6-montagem`, a partir da `main` (Fases 1–5 e code-review já mergeados). Escrito [fase-6-montagem-e-exportacao.md](fase-6-montagem-e-exportacao.md) com 6A (plano de montagem em quadros inteiros a 60 fps), 6B (mixagem), 6C (exportação), 6D (candidatos a Shorts) e 6E (CLI). Decisões: (1) cada recurso do FCPXML é validado isoladamente, porque um recusado derruba o arquivo; (2) marcadores coloridos saem como Lua de uma linha para o Console (única via que o spike confirmou); (3) **stems A1/A2 cobrem só os trechos usados**, não a sessão inteira (resolve a pergunta aberta da seção 9, item "stems processados"); (4) SRT remapeado para tempo de timeline, com fala vazia em 0 s. Itens do spike ainda sem resposta (relink, FCPXML do app com trilhas, cartela editável, render) bloqueiam só o aceite da 6C em `prod`.

## 54. Fase 6E: retomada por hash e pausa de GPU no `montagem` (2026-11-17)

Fecha as duas pendências da 6E. Retomada: `entrada_hash` (SHA-256 do plano em JSON + roteiro + versão do plano) no
manifesto; versão completa idêntica é reaproveitada, interrompida é continuada, mudança de entrada cria versão nova
(nunca apaga a anterior). Timelapses passam para `<base>/timelapses`. Pausa: `build_gate` do ambiente consultado antes
de cada timelapse e da mixagem. Não interrompe um FFmpeg já em curso. 425 testes verdes.

## 55. Fase 7A: API local do Studio (2026-11-17)

Fase 7 dividida em 7A–7E (`docs/fase-7-studio.md`). A 7A entrega a API FastAPI só de leitura (`cronista api`, porta 8000,
CORS apenas para `localhost:3000`); o comando `serve` já era o watcher do OBS, então a API é `api`. Escrita (decisões do
criador) fica para a 7C.

## 56. Fase 7B–7E: Studio de revisão e aprendizado (2026-11-18)

Decisões tomadas ao implementar o Studio (`docs/fase-7-studio.md`):

1. **Decisões do criador só por inserção** (`segment_decision`): aceito / rejeitado / ajustado, vale a última linha, a anterior
   fica no histórico (padrão da 5A). A decisão fica presa à janela do segmento (`seg_start_s` + `seg_end_s`): se a relevância
   for recalculada e a janela mudar, a decisão deixa de valer, em vez de cair em outro trecho que comece no mesmo segundo.
   Ajuste não pode passar da duração do arquivo nem invadir outro segmento.
2. **Roteiro, montagem e Shorts leem os segmentos efetivos** (`load_effective_segments`): rejeitar tira o trecho, ajustar
   troca os limites. A montagem re-exporta pelo cache por hash (plano + roteiro): decisões iguais reaproveitam a versão.
3. **Edição de roteiro** valida como o `roteiro-import` e guarda cada versão anterior em `roteiro.v<N>.json`; a gravação é
   feita em temporário antes de trocar, para uma falha não apagar o roteiro vigente.
4. **API local sem autenticação, só em 127.0.0.1**: escrita só aceita a origem do Studio (`Origin` fora da lista → 403),
   porque POST sem corpo é "requisição simples" e o CORS não impede um site qualquer de dispará-lo. Migrações Alembic rodam
   uma vez na partida e sob lock (o Alembic não é thread-safe); progresso por SSE assíncrono com teto de 6 h.
5. **Recalibração por manter/tirar** (7E): regressão logística pequena sobre marcador, emoção, fala, novidade e pausa,
   encolhida para os pesos padrão com `n/(n+30)`; mínimo de 20 decisões, 5 de cada lado; proposta explicada em português e
   **só vale depois de aceita** (`weight_calibration`, só inserção). Limite conhecido: só usa trechos que o criador decidiu,
   o que enviesa para quem já tem nota extrema; a proposta avisa disso.
6. **Feedback em texto livre (Q26/Q27)** fica guardado sem interpretação (`feedback`). O LLM local só entra se passar o
   benchmark da seção 6.1 (precisa da GPU de `prod`); até lá, nada ajusta a edição a partir do texto.

## 57. Fase 8: plano do acabamento e identidade do canal (2026-11-18)

Branch `fase/8-acabamento`, a partir da `main` (Fase 7 mergeada). Escrito [fase-8-acabamento.md](fase-8-acabamento.md) com 8A
(brand kit, estilo por série, inventário da biblioteca), 8B (plano de acabamento por orçamento), 8C (render: zoom, shake, LUT,
templates, legendas pontuais, música), 8D (exportação) e 8E (Studio). Decisões: (1) brand kit e estilo por série são YAML
versionado em `packages/brand-kit/`, validados por Pydantic com JSON Schema gerado; a série só sobrepõe o que muda (Q18);
(2) cada efeito tem modo (`sugerir`/`editavel`/`renderizado`), máximo por minuto e nota mínima, mais um teto somado por minuto
(seção 6.4); (3) padrão conservador: humor e impacto nascem só como `sugerir`, o criador liga por série; (4) inventário da
biblioteca pessoal exige origem e licença por item, BPM em música e a flag `commercial_use`, que bloqueia o item no vídeo
monetizado; (5) o brand kit referencia a biblioteca por `id`, nunca por caminho; (6) licença do Remotion a verificar antes de
adotar (alternativa: overlays por FFmpeg/Pillow).

Decisões da 8B (plano de acabamento, escrito sem poder rodar o ambiente completo): (7) orçamento por efeito é um **espaçamento
mínimo** de `60/max_per_minute` s entre dois do mesmo efeito (garante variação, não só média) mais um teto somado por janela de
60 s que só conta o que é aplicado; `sugerir` é só marcador e fica fora do teto; música, cartela de dia e LUT são estruturais e
ficam fora do orçamento; (8) vagas disputadas vão para as maiores notas, e SFX/música rodam entre os itens menos usados (determinístico,
por `id`); (9) o contador de mortes numera todas as mortes da montagem, mesmo as que o orçamento corta; (10) o clima do capítulo
vem do beat dominante (`BEAT_MOOD`, palpite a validar) e o brand kit pode fixar trilhas por clima; (11) o módulo do plano usa só a
biblioteca padrão e recebe políticas e biblioteca por interfaces simples, para ser testável sem o ambiente do projeto; (12) as
sugestões entram no pacote como marcadores "Sugestão: ..." no Lua do Resolve, com cores que não repetem as do criador.

Decisões da 8C (render de vídeo, `finishing/render/video.py`): (13) zoom e shake saem de `scale` 2x + `zoompan` do FFmpeg
(nada do Studio do Resolve), em um MP4 por efeito para a V2, 60 fps, sem áudio, com o enquadramento original no primeiro e no
último quadro (curva `sin²` no zoom; tremor com ataque em 10 % e queda a zero, ampliação proporcional à amplitude), então a emenda
com a V1 não aparece e desligar a V2 devolve a gravação intacta; (14) o clipe nasce da janela de origem do corte de V1 sob o
efeito (só gameplay ao vivo em velocidade 1; o que passa do corte é aparado); (15) nome do arquivo com hash do filtro e do encoder:
mesma entrada reaproveita o render; (16) **LUT em modo `renderizado` não é gerado**: a V1 por baixo ficaria sem cor e o clipe
da V2 destoaria; LUT fica `editavel` (Resolve) e o render avisa; (17) o executor espera o `GpuGate` antes de cada render, como o
timelapse.

Decisões da 8C restante, 8D e 8E (2026-11-18): (18) o contador de mortes sai de overlay MOV (ProRes 4444 com alfa) feito com
`drawtext` do FFmpeg, sem Remotion (licença não verificada, §45); fonte do brand kit ou do sistema; o número é o da morte, nunca
o do dia; (19) **freeze + texto e piada visual ficam só como sugestão** (o texto é decisão do criador) e **barra de progresso e
legenda pontual ficam fora da Fase 8**: dependem dos dias do Studio e das palavras do Whisper, e o plano avisa quando estão
ligados; (20) música renderizada = um stem A4 do tamanho da timeline, com fade e `sidechaincompress` contra o stem de voz;
editável = arquivo da biblioteca por corte, com volume fixo de -20 dB; SFX é o mesmo nos dois modos; (21) no FCPXML os efeitos
entram como clipes conectados ao corte de V1: V2 = lane 1, V4 = lane 3, A4 = lane -4, A5 = lane -5; zoom/shake editáveis são
cópias do corte com keyframes de `adjust-transform` (escala; posição em % da altura no tremor); (22) LUT editável = `.cube` copiado
para `luts/` e um Lua de uma linha com `SetLUT` no nó 1 de cada clipe da V1 (o FCPXML não carrega LUT de forma portável);
(23) `manifesto.json` ganha `efeitos` (o quê, onde, quando e como desfazer) e o LEIA-ME uma seção do acabamento; (24) Studio:
ajuste de efeito (modo, máximo por minuto, nota mínima) é por **projeto** e decisão sobre item é por **sessão**, ambos só
inserção, a última linha vale; `aceito` promove sugestão a editável (só onde há forma editável), `removido` tira o item, `padrao`
desfaz a decisão; a decisão fica presa ao **item e ao momento** (`<id>@<momento>`), porque o `id` é posicional e o mesmo `id`
pode cair em outro trecho se o plano mudar; o POST confere o item contra o plano atual; tirar um item não libera a vaga de
outro (o orçamento não é refeito); (25) o Studio usa a série de
`finishing_series` da configuração; sem brand kit, o painel avisa e a exportação segue sem acabamento.

Correções da revisão de código da Fase 8 (2026-11-18): (26) o hash da exportação passou a cobrir o brand kit, os arquivos que ele
referencia (LUT, fontes) e os arquivos da biblioteca usados pelo plano, para trocar um `.cube` ou uma fonte gerar versão nova em
vez de reaproveitar a antiga; (27) renders de zoom, shake e overlay são escritos em arquivo temporário e só então renomeados
(cancelar no meio não deixa clipe parcial no cache); (28) áudio ilegível da biblioteca vira aviso e o item é ignorado;
(29) a prévia do Studio guarda a montagem (história + cortes) por sessão e alvo, com impressão digital das tabelas que a
alimentam, e só refaz o plano de acabamento a cada clique.

⚠️ Sem conferência no Resolve (plano 6.5): se ele respeita as lanes 1, 3, -4 e -5, os keyframes de `adjust-transform`, `SetLUT` e
o alfa do MOV. Se algo falhar, o modo `renderizado` (MP4/MOV prontos) é o caminho mais seguro.

## 58. Fase 9: plano da embalagem e 9A, Shorts finalizados (2026-11-18)

Branch `fase/9-embalagem`, a partir da `main` (Fase 8 mergeada, PR #22). Escrito [fase-9-embalagem.md](fase-9-embalagem.md) com
9A (Shorts), 9C (títulos), 9B (thumbnails) e 9D (Studio e pacote). Decisões: (1) ordem 9A → 9C → 9B → 9D, porque os Shorts já têm
entrada pronta (candidatos da 6D) e o modelo de thumbnail depende do criador; (2) **modelo de thumbnail segue "a decidir
depois"** (resposta do criador): a fase entrega o mecanismo e um modelo declarativo em YAML no brand kit, e o layout se define na
hora de testar; (3) reenquadramento 9:16 em dois modos, `desfoque` (padrão, gameplay inteira sobre fundo desfocado) e `recorte`
(janela vertical em torno de `focus_x`); o seguidor de saliência da seção 6.6 fica fora porque não há dado de região de ação no
banco; (4) legenda gravada em ASS pelo filtro `ass` do FFmpeg, palavras do Whisper em grupos de 3, palavra falada em destaque,
cor e fonte do brand kit; (5) margens seguras (topo 250, base 450, direita 140, esquerda 60 px) são valores de memória, a
conferir no celular; gameplay e legenda formam um bloco centrado entre elas; (6) áudio é a faixa 1 (o mix de entrega, nunca para
análise) com `loudnorm` no alvo do canal e corte suave de 0,15 s; (7) mesmo padrão da Fase 8: render atômico, nome com hash do
filtro, da legenda e do encoder, espera do `GpuGate`.

⚠️ Sem conferência com FFmpeg real (este PC não o tem): grafo de filtros, `ass` (libass) e `loudnorm` só se confirmam em `prod`.

**9C, sugestões de título (2026-11-18).** Decisões: (8) mesmo caminho do roteiro: `cronista titulos` gera um `titulo-pack.json`
compacto e determinístico (objetivo confirmado, arco, abertura, desfecho, 6 momentos de maior nota, sem número de dia), a skill
`/titular` (com `/humanizar`) escreve `titulos.json` e `cronista titulos-import` valida; o `NullTitleProvider` é o padrão e **não
há título por LLM local** (a exceção do §40 vale só para o roteiro); (9) são **erros** (nada gravado) título vazio, repetido, acima
de 70 caracteres ou com clichê de isca de clique, e **avisos** os sinais de texto de IA e a falta de `reason`; (10) a escolha do
criador fica na tabela `title_choice` (migração 0012), só inserção, com origem `sugerido`, `editado` ou `proprio`, para o app
aprender o gosto depois; o texto do criador só esbarra no limite duro do YouTube (100 caracteres), nunca no validador de clichê.

**9B, thumbnails (2026-11-18).** Decisões: (11) **mecanismo sem Pillow e sem IA de imagem**: o FFmpeg corta o frame da gravação em
16:9, corrige a cor (`eq`, `vignette`), aplica a moldura e desenha texto e selo (`drawtext`); a heurística de frame usa só
numpy; nenhuma dependência nova; (12) modelo declarativo em `packages/brand-kit/thumbnail.yaml` (campo desconhecido, cor
inválida, proporção diferente de 16:9, moldura ausente e fonte ausente são recusados), valores ilustrativos até o criador
definir o layout, o que mantém a decisão "decidir depois" do §58; (13) frame candidato = pico do story-pack; nota final 60% a
nota do momento e 40% a qualidade medida (nitidez, contraste, exposição, composição), um por segmento e nunca dois a menos de
20 s no mesmo arquivo; (14) 2–3 variações determinísticas, JPEG de até 2 MB (tenta qualidades menores e avisa se não couber);
(15) o texto da thumbnail (2 a 4 palavras, até 28 caracteres) vem do `/titular` (`thumbnail_texts`) ou de `--texto` do criador,
que ganha; (16) a escolha vai para `thumbnail_choice` (migração 0013), só inserção; (17) **contradição com o plano apontada**: o
selo "Dia N" não pode ler "os dias ajustados no Studio" porque o app não guarda número de dia (decidido na edição); o número
vem de `--dia` e o selo nasce desligado.

⚠️ Sem FFmpeg real neste PC: filtro e `drawtext` só se confirmam em `prod`; os pesos da heurística de frame são de memória e
precisam de olho humano em jogos reais.

**9D, pacote de publicação e Studio (2026-11-18).** Decisões: (18) a aprovação do Short é inserção em `short_decision` (migração
0014), com `aprovado`, `rejeitado` e `padrao` (volta a pendente), no mesmo padrão da 7C, da 8E e dos títulos; aprovar exige o MP4
renderizado; (19) a pasta de publicação (`pacote-publicacao`) copia só os Shorts aprovados, na ordem da nota, e **o que falta é
item do `LEIA-ME.md` e código de saída 2, nunca erro**: dá para montar a pasta parcial e ver o que resta; (20) o vídeo da série é
renderizado pelo criador no Resolve e entra por `--video` (o app não o produz), e o painel do Studio não pede caminho de arquivo;
(21) o painel "Embalagem" lê tudo de um único `GET .../packaging` e cada escolha devolve o painel atualizado; as mídias
(thumbnail e Short) só são servidas se constam no manifesto, para a rota não abrir arquivos arbitrários; (22) nada é publicado
pelo app: não há envio ao YouTube (sem rede, sem credenciais); o criador sobe a pasta.

⚠️ O painel passou em `tsc` e `eslint`, mas não foi visto no navegador (sem engine com mídia neste PC).

**Correções do `/code-review` da fase (2026-11-18):** (23) falha do FFmpeg em um Short vira aviso e os outros seguem (o
`shorts-<id>.json` sempre é gravado); (24) `--top` padrão sobe para 5, porque o pacote pede 3 aprovados e o criador pode
rejeitar; (25) gravação sem ingestão não derruba Shorts nem thumbnails: vira aviso, e só falha se nenhuma gravação estiver
pronta (`montage.load_masters`); (26) a thumbnail escolhida só vale se ainda consta no manifesto atual, no painel **e** no pacote
(o mesmo critério nos dois); (27) sem `--video`, o pacote usa o MP4 mais recente da pasta, e `--out` recusa pasta com arquivos
que não são de um pacote (sem `LEIA-ME.md`), para não apagar `short-*.mp4` alheios; (28) aspa simples no texto do `drawtext`
fecha a citação e entra escapada (`'\''`), não `'`, que o FFmpeg não aceita dentro de aspas (**não conferido com FFmpeg real**;
também vale para o contador da Fase 8); (29) `titulos.json` quebrado vira `TitleError` e o painel segue sem sugestões; (30) JPEG
reaproveitado acima de 2 MB avisa de novo.

## 59. Aviso de capítulos com pouco material no Studio (2026-11-17)

*Ordem: a numeração segue a ordem de inclusão no histórico, não a data; este §59 é de 2026-11-17 e vem depois do §58 (2026-11-18).*

O painel reaproveita a divisão e a estimativa da narrativa sobre os segmentos revisados, em ordem de sessão e arquivo
por projeto. Capítulos podem atravessar sessões e aparecem no aviso quando têm menos de 30 s de material estimado,
a referência existente da alocação narrativa. O Studio consulta o painel novamente após salvar uma decisão.

## 60. Auditoria do projeto e decisões da Fase 10 de correções (2026-11-18)

O código e os documentos foram auditados (só leitura) em 6 blocos lógicos: captura e análise; relevância e narrativa;
montagem e acabamento; embalagem e orquestração; Studio, contratos e CI; documentação. A auditoria gerou planos de
correção por bloco, mais um transversal de redundância e ambiguidade, em `docs/auditoria/` (índice em `00-indice.md`).
As correções formam a **Fase 10**, em sub-etapas:

- 10A: bugs e regras;
- 10B: pontos únicos de tempo, FFmpeg e pastas;
- 10C: consolidação;
- 10D: documentação;
- 10E: testes e CI;
- 10F: história por série.

**Decisões do criador:**

1. **Narrativa por série.** Registrar agora a lacuna "por sessão" e implementar na 10F.
2. **LUT.** O padrão passa a `sugerir` até a conferência em `prod`.
3. **Detector de grito.** Fica atrás de uma flag desligada por padrão.
4. **`cronista export`.** Fica deprecado e marcado como substituído por `montagem`.
5. **`--out` dos comandos de embalagem.** É removido.
6. **Painel.** Ganha os estados `curto_ok` e `abaixo_da_referencia`, no lugar de `faltando`.
7. **Lookback.** Valem os 25/20/30 s do §51, ajustáveis por perfil; os 60–90 s ficam substituídos.

O que substitui o quê:

- o item 4 substitui, como caminho vigente, o FCPXML via OTIO do §30;
- o item 7 substitui a janela de 60–90 s citada na seção 4 do plano mestre;
- os itens 2 e 6 refinam §57 e §40/§59.

Detalhes, local de cada achado e critérios de aceite estão nos planos.

## 61. Glossário aprovado (2026-11-19)

O criador aprovou `docs/glossario.md` (termos: Studio × Resolve Studio, faixa × trilha, segmento × trecho, os três
sentidos de "pacote", perfil de jogo/voz/ambiente). Ressalva: o vocabulário de decisões **não** será unificado agora
(`aprovado`/`rejeitado` nos Shorts, `aceito`/`removido` no acabamento, `aceito`/`rejeitado`/`ajustado` nos segmentos),
porque exigiria migração de dados; fica como possibilidade sem urgência. Em conflito de vocabulário, vale o glossário.

## 62. Vídeo da série na sessão âncora (2026-11-19)

Para a 10F sem tabela nova nem migração, o vídeo único da série é ancorado na **última sessão do projeto**
(`anchor_session`). `cronista story --projeto N` grava o story-pack na pasta dela; roteiro, títulos, thumbnails, Shorts
e publicação seguem como comandos por sessão, chamados com o número da âncora. Montagem e acabamento ganham
`--projeto N` (alvo único, dias contínuos), e o Studio/API aceitam `serie=true` na sessão âncora. Contrapartida: rodar
`cronista story <âncora>` por sessão sobrescreve o pacote da série na mesma pasta. Alternativa descartada por ora: tabela
`video` própria (mais limpa, mas exige migração e reescrita dos caminhos). B15 ficou como reconciliação de ids (religa a
fala ao segmento que contém o início antigo e acusa roteiro órfão), não como hash estável.

Revisão (`/code-review`, 2026-11-19): corrigidos o piso de capítulo que estourava o alvo com muitos capítulos (agora
encolhe para `alvo / nº de capítulos`), os stems da série (iam para a pasta da sessão 0), a exportação em modo série
com sessão que não é a âncora (422), o aviso de roteiro ausente na âncora, o aviso de pacote de outro escopo (`escopo.json`)
e as thumbnails, que agora usam as gravações do projeto todo. **Limites conhecidos:** entrar uma sessão nova muda a
âncora e deixa roteiro, título e decisões na âncora antiga (é preciso copiá-los); os Shorts continuam por sessão.

## 63. Texto da thumbnail, A9 e A10 (2026-11-19)

- **D14:** o texto editável da thumbnail (fase 9, 9B) fica **fora de escopo**: não existe endpoint nem campo no Studio, e o
  criador escolheu não criá-los. O texto sai sugerido (2–4 palavras, humanizado) e quem quer outro texto escolhe outra
  variação. A frase da fase 9 foi marcada como substituída.
- **A9 feito:** `HOP_FRAMES` virou `AUDIO_SIGNAL_HOP` (6 quadros, 10 Hz) em `audio/signals` e `VIDEO_SAMPLE_HOP` (12 quadros,
  5 por segundo) em `video/frames`; `FloatArray` (float32) e `Pause` passaram a existir só em `domain/types.py`. O campo
  `hop_frames` dos sinais não mudou (é dado persistido).
- **A10 adiado:** mover a infraestrutura genérica de sinais e eventos de `cronista.audio` para `cronista/analysis/` mexe em
  muitos imports sem corrigir bug; fica como dívida técnica consciente, sem prazo.
- **A13 e E17 feitos:** o serviço de observação não dá a gravação como abandonada enquanto o OBS grava; o Studio ganhou
  teclado no waveform, `aria-label`, títulos em ordem e formulário inline de ajuste.

## 64. Revisão dos ⚠️ e dos critérios sem número (2026-11-19, Fase 10D, F18)

Os ⚠️ do plano mestre foram revisados um a um contra o que o spike do `prod` (§39), os benchmarks (§44, §49) e as fases
já registraram. Cada um foi marcado no próprio texto: ~~⚠️~~ riscado com ✅/❌ e o ponteiro quando resolvido, ou ⚠️ com
colchetes quando segue aberto ou parcial (a maioria só se resolve em `prod`, e consta como EA-1 na tabela "Em aberto").
Os ⚠️ deste histórico **não foram alterados**: são o registro do que se pensava em cada data.

- **Resolvidos ❌ (o plano de memória estava errado):** marcadores por FCPXML/EDL (só por script), scripting externo,
  adaptador OTIO do FCPXML, script interno com interface própria, HEVC importado, DeepFilterNet no ambiente principal.
- **Resolvidos ✅:** CUDA convivendo (torch e CTranslate2), hotkeys e obs-websocket no Python 3.12, capítulos nativos do
  OBS, título nativo no FCPXML, faixas de áudio por WAVs extraídos.
- **Critérios sem número:** "WER aceitável" (proposta ≤ 15%, fase 2), "alta precisão" (menu/loading ≥ 90% de precisão,
  fase 3) e "top de candidatos" (85% dos momentos, fase 4, já no código) ficaram com a proposta e o resultado medido ao
  lado. **Nenhum corte foi aprovado pelo criador**; seguem propostas até o benchmark final em `prod`.
- **Medido nos benchmarks (com gabaritos pequenos):** `whisper-turbo` WER 1,1% e `large-v3` 3,1% (viés a favor do
  turbo); tela: todos os VLMs acertaram 100% (teste saturado).

## 65. Correções da revisão de código da Fase 10 (2026-11-19)

O `/code-review` da branch achou 10 pontos; 4 foram confirmados e corrigidos, cada um com teste que o reproduzia:
- **Limiar do perfil no arco e no painel:** `keep_score` (e o resto do grupo `relevance`) só valia em `relevance_session`;
  story, painel e `/aprendizado` usavam o padrão. Os limiares do perfil agora vão em `Settings.relevance_overrides`
  (campo que **não vem do YAML**, preenchido por `current_settings()`), para o núcleo não conhecer perfis.
- **Marcadores no mesmo quadro** ficam dentro do próprio corte (para a frente e, no fim, para trás); sem quadro livre
  viram aviso.
- **Estado de objetivo:** a guarda de reexecução compara com a última linha da **mesma citação**, então um estado que
  volta a ser o de antes (a evidência mudou e mudou de novo) é regravado, sem alternar entre citações diferentes (B7).
- **Docstring solta** em `finishing/plan.py` removida.

Os demais achados não procedem: a chave dos Shorts é a decisão D4 (§60) e as thumbnails do projeto todo são a correção da
10F (§62). Não foram tratados: `pipe_raw` com bloco parcial, `session_id or 0` repetido e listas mutáveis em `ExportStatus`
(sem falha hoje); o painel de embalagem que engole manifesto corrompido ficou **sem verificar**.

## Decisões em aberto

A lista atual fica na seção 9 do [plano mestre](00-plano-mestre.md).
