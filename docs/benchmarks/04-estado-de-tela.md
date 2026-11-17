# Estado de tela por modelo de visão e linguagem

Comando: `cronista bench-vision`.

<!-- tabelas:inicio (gerado por `cronista bench-report`; não edite aqui) -->

| Modelo | Entrada | Tempo/quadro | VRAM | Acerto | Por classe |
|---|---|---|---|---|---|
| `qwen25vl-3b` | 360p | 0.43 s | 7.1 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |
| `qwen25vl-3b` | 720p | 1.28 s | 7.4 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |
| `qwen25vl-7b-4bit` | 360p | 0.58 s | 6.0 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |
| `qwen25vl-7b-4bit` | 720p | 1.81 s | 6.5 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |
| `qwen3vl-4b` | 360p | 0.38 s | 8.4 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |
| `qwen3vl-4b` | 720p | 0.97 s | 8.8 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |
| `qwen3vl-8b-4bit` | 360p | 0.58 s | 6.5 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |
| `qwen3vl-8b-4bit` | 720p | 1.49 s | 6.9 GB | 1.00 | gameplay 1.00, menu 1.00, dialogue 1.00; inválidas 0 |

<!-- tabelas:fim -->

## Análise

### Como ler (versão simples)

Mostrei a cada modelo 23 quadros reais do vídeo e perguntei: isto é **gameplay**, **menu** ou **diálogo**? A coluna
"Acerto" é a fração de respostas certas. Testei quatro modelos que entendem imagem e texto (VLM), em quadros de 360p
(a resolução do proxy) e de 720p.

### O que a tabela diz

- **Todos acertaram 100%**, em qualquer resolução e sem nenhuma resposta fora das classes. O teste é fácil demais para
  separar os modelos: nenhum erro, então não há como dizer qual é "mais preciso".
- O que diferencia é custo: o `qwen3vl-4b` leva 0,38 s por quadro em 360p; os de 7B e 8B em 4 bits levam 0,6 s
  (360p) e 1,5 a 1,8 s (720p), e ocupam menos memória que o 4B sem quantizar (6 a 6,5 GB contra 8,4 GB).
- A resolução 360p do proxy basta para decidir o tipo de tela. Não precisa ler o master para isso.

### Qual usar

| Uso no projeto | Escolha | Motivo |
|---|---|---|
| Classificar tela nos trechos que a heurística da 3A deixou em dúvida | `qwen3vl-4b` em 360p | o mais rápido (0,38 s/quadro) com o mesmo acerto |
| Se a memória da GPU estiver apertada | `qwen25vl-7b-4bit` | 6 GB e também 100% |
| Tarefas mais difíceis (loading, `idle`, cinemática, "o que está acontecendo") | reavaliar os de 7B/8B | só aí o tamanho pode compensar; este teste não mede isso |

### Limites

23 quadros de um jogo só, com 3 classes fáceis de distinguir. Faltam exemplos de **loading, idle e cinemática**, que
são justamente o que a heurística não resolve (histórico §47). Antes de escolher o VLM definitivo, montar esse
gabarito (a 3C já o exige). O VLM roda só em trechos candidatos, nunca no vídeo todo.
