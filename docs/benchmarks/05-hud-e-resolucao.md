# Leitura do HUD (OCR) e efeito da resolução

Comando: `cronista bench-vision`.

<!-- tabelas:inicio (gerado por `cronista bench-report`; não edite aqui) -->

| Leitor | Entrada | Tempo/leitura | Leituras boas | Erro de caracteres | Dia/hora certo | Nota |
|---|---|---|---|---|---|---|
| `rapidocr` | 360p | 0.40 s | 0.00 | 1.00 | 0.00 |  |
| `rapidocr` | 720p | 0.33 s | 1.00 | 0.01 | 1.00 |  |
| `rapidocr` | 1080p | 0.34 s | 1.00 | 0.00 | 1.00 |  |
| `qwen25vl-3b` | 360p | 1.45 s | 0.42 | 0.29 | 0.33 |  |
| `qwen25vl-3b` | 720p | 1.48 s | 0.75 | 0.08 | 0.83 |  |
| `qwen25vl-3b` | 1080p | 1.68 s | 1.00 | 0.00 | 1.00 |  |
| `qwen25vl-7b-4bit` | 360p | 1.27 s | 0.33 | 0.25 | 0.25 |  |
| `qwen25vl-7b-4bit` | 720p | 1.42 s | 1.00 | 0.01 | 0.92 |  |
| `qwen25vl-7b-4bit` | 1080p | 1.58 s | 1.00 | 0.00 | 1.00 |  |
| `qwen3vl-4b` | 360p | 1.79 s | 0.67 | 0.15 | 0.75 |  |
| `qwen3vl-4b` | 720p | 2.05 s | 1.00 | 0.00 | 1.00 |  |
| `qwen3vl-4b` | 1080p | 2.04 s | 1.00 | 0.00 | 1.00 |  |
| `qwen3vl-8b-4bit` | 360p | 2.16 s | 0.50 | 0.19 | 0.50 |  |
| `qwen3vl-8b-4bit` | 720p | 2.44 s | 1.00 | 0.00 | 1.00 |  |
| `qwen3vl-8b-4bit` | 1080p | 2.47 s | 1.00 | 0.01 | 0.83 |  |

**Decodificação do vídeo (1 quadro por segundo):**

| Caso | x tempo real | 10 h em |
|---|---|---|
| proxy 360p (CPU) | 182.9x | 3 min |
| master 720p (CPU) | 22.9x | 26 min |
| master 1080p (CPU) | 23.5x | 26 min |
| master 720p (NVDEC) | 13.0x | 46 min |
| master 1080p (NVDEC) | 13.1x | 46 min |

<!-- tabelas:fim -->

## Análise

### Como ler (versão simples)

O HUD é a informação escrita na tela do jogo: coordenadas, bioma e "Day 2, 13:05". Pedi a cada leitor que lesse 12
recortes do HUD, em três resoluções: o proxy de 360p, e o vídeo original (master) reduzido para 720p e em 1080p.
"Leituras boas" é a fração com no máximo 15% de caracteres errados; "Dia/hora certo" confere se o "Day N, HH:MM" saiu
exatamente igual. Nos modelos de visão, o tempo inclui gerar a resposta.

### O que a tabela diz

- **Em 360p ninguém lê o HUD**: o RapidOCR acerta 0% e os melhores modelos de visão ficam entre 33% e 67%. O texto
  simplesmente não existe nessa resolução.
- **Em 720p o RapidOCR acerta 100%** (erro de 1% de caracteres, dia/hora 100% certo), em 0,33 s por leitura, na CPU e
  sem usar a placa de vídeo. Os modelos de visão chegam a 100% em 720p só no Qwen3-VL 4B e no Qwen2.5-VL 7B (92% no
  dia/hora), e levam de 1,5 a 2,5 s por leitura.
- **1080p não melhora o OCR**: 720p já é suficiente e mais barato para decodificar.
- **Decodificar o master é caro:** 1 quadro por segundo do vídeo original roda a ~23x o tempo real em CPU (cerca de
  25 min para 10 h), contra ~174x do proxy (3 min). A aceleração por placa de vídeo (NVDEC) ficou mais lenta, ~13x,
  porque o filtro de amostragem obriga a decodificar todos os quadros.

### Qual usar

| Uso no projeto | Escolha | Motivo |
|---|---|---|
| Ler texto do HUD (dia, coordenadas, bioma) | `rapidocr` no **master em 720p**, só na região do perfil | 100% de acerto, 0,33 s, CPU |
| Texto difícil ou estilizado onde o RapidOCR falhar | `qwen3vl-4b` em 720p, só nesses casos | também 100%, mas 6x mais lento |
| Tudo que não é texto (sinais, embeddings, tipo de tela) | proxy 360p | 8x mais rápido de decodificar |

Na prática: ler o master só nos instantes pedidos (busca por tempo, não varredura completa), o que torna o custo de
decodificação desprezível perto dos 25 min da varredura inteira.

### Limites

12 leituras do mesmo HUD, de um jogo só, de fonte clara e fundo escuro. HUDs com fontes pequenas, animadas ou
semitransparentes podem se comportar diferente. O PaddleOCR-VL não foi testado.
