# Benchmarks: qual modelo usar em cada situação do projeto

Resumo dos cinco benchmarks de 2026-11-17 (RTX 3060 12 GB, `claude_teste.mp4` de 37 min e as sessões de teste de voz e de
gritos). Cada benchmark tem seu relatório, com tabelas geradas por `cronista bench-report` e a análise escrita à mão.
Modelos e versões foram escritos de memória e funcionaram nesta máquina; a escolha definitiva vai para a seção 5.2 do plano.

| Relatório | Responde |
|---|---|
| [01 Embeddings de quadro](01-embeddings-de-quadro.md) | Qual modelo agrupa cenas e busca B-roll por texto |
| [02 Fala](02-fala.md) | Whisper turbo ou large-v3 |
| [03 Eventos sonoros](03-eventos-sonoros.md) | AST ou CLAP para risada e exclamação |
| [04 Estado de tela](04-estado-de-tela.md) | Qual VLM classifica menu, diálogo e gameplay |
| [05 HUD e resolução](05-hud-e-resolucao.md) | Como ler o texto da tela e em que resolução |

## Recomendação por situação

| Situação no projeto | Usar | Em vez de | Por quê (resumo) |
|---|---|---|---|
| Contextos visuais de todos os segundos (3B) | `siglip2-base` | modelos pesados | 10 h em ~1 min e 1,9 GB; os pesados não agrupam melhor neste teste |
| Busca de B-roll por texto ("vista da base") | `siglip2-large`, só nos trechos candidatos | `siglip2-base` | melhor entendimento de texto (0,77 contra 0,64); 11 min para 10 h se rodasse em tudo |
| Transcrição de fala | `whisper-turbo` (o atual) | `whisper-large-v3` | 1,1% de erro contra 3,1% e o dobro da velocidade (com viés a favor do turbo, ver abaixo) |
| Risada no microfone | `ast-mic`, janela de 2 s (o atual) | CLAP | precisão alta; o CLAP gera falsos alarmes demais |
| Exclamação (grito de empolgação) | CLAP como **candidato**, ainda sem adotar | heurística atual | revocação de 63% contra 0% da heurística neste teste, mas precisão de 29% a 36% |
| Eventos do jogo (explosão, música) | `ast` na faixa do jogo (o atual) | , | já no pipeline; não foi o foco |
| Tipo de tela (menu, diálogo, gameplay) | heurística da 3A; VLM `qwen3vl-4b` em 360p só nos trechos duvidosos | VLM de 7B/8B | todos acertaram 100%; o 4B é o mais rápido (0,38 s/quadro) |
| Ler o HUD (dia, coordenadas, bioma) | `rapidocr` no **master em 720p**, só na região do perfil | VLM e proxy | 100% de acerto, 0,33 s, CPU, sem placa de vídeo |
| Resolução de leitura | proxy 360p para sinais, embeddings e tela; master 720p só para OCR | master 1080p | 360p não lê texto; 1080p não melhora o OCR e custa decodificação |
| Roteiro | Claude Code (plano Pro) | LLM local | não testado, por decisão; mantém o plano |

## Tempo estimado para 10 h de gravação (modelos recomendados)

| Etapa | Tempo |
|---|---|
| Sinais visuais (3A, CPU) | ~8 min |
| Embeddings `siglip2-base` (GPU) | ~1,3 min mais a decodificação do proxy |
| Fala `whisper-turbo` (GPU) | ~31 min |
| Eventos sonoros `ast` (GPU), jogo e microfone | ~20 a 40 min |
| OCR do HUD | proporcional aos instantes pedidos; varredura completa seria ~25 min de decodificação |
| VLM `qwen3vl-4b` | só trechos candidatos (segundos por trecho) |

As etapas de GPU rodam em sequência e pausam com o OBS gravando ou jogo em tela cheia.

## O que ficou de fora e por quê

- **Parakeet e Canary:** os modelos do `transformers` são só em inglês; o multilíngue exige o NeMo (pesado no Windows).
- **BEATs:** código da Microsoft (`unilm`), fora do `transformers` e do PyPI. **PANNs:** não houve tempo.
- **SigLIP 2 giant:** travou na carga; não entraria no pipeline. **DINOv2:** não testado (sem texto, só agrupamento).
- **PaddleOCR-VL:** não testado. **Ollama:** não instalado, por decisão do criador (histórico §48); VLMs rodam pelo `transformers`.

## Limites que valem para todos os números

- **Gabaritos pequenos e de um jogo só.** Fala: 287 s; eventos: 84 s (1 risada, 8 exclamações); telas: 23 quadros; HUD: 12
  leituras; cenas: 4 tipos. São indícios, não provas.
- **Viés a favor do turbo na fala:** o gabarito foi montado corrigindo as sugestões do próprio Whisper turbo.
- **Viés no kNN dos embeddings:** os rótulos vieram dos agrupamentos do `siglip-base`; por isso só o zero-shot separa os modelos.
- **Teste de tela saturado:** todos acertaram tudo; falta gabarito de loading, idle e cinemática.
- **Tempos** medem o modelo depois de carregado; o primeiro uso inclui o download e a carga (de segundos a minutos).

## Próximos passos sugeridos

1. Anotar loading, `idle` e cinemática (poucas dezenas de trechos) para o teste de tela deixar de saturar (3C).
2. Calibrar o CLAP para exclamação: juntar eventos vizinhos, ajustar o limiar e cruzar com a energia da voz (Fase 4).
3. Fixar `siglip2-base` e `siglip2-large` e o RapidOCR no plano (seção 5.2) depois de uma busca de B-roll real.
4. Repetir os benchmarks numa sessão longa e real, com outro jogo, antes de dar os números por definitivos.
