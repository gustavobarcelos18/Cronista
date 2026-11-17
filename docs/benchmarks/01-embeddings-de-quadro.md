# Embeddings de quadro (contextos e busca de B-roll)

Comando: `cronista bench-video`.

<!-- tabelas:inicio (gerado por `cronista bench-report`; não edite aqui) -->

| Modelo | Dim. | 10 h de vídeo em | VRAM | kNN | Zero-shot |
|---|---|---|---|---|---|
| `siglip2-large` | 1024 | 11 min | 3.8 GB | 0.92 | 0.77 |
| `siglip2-so400m` | 1152 | 24 min | 6.3 GB | 0.92 | 0.68 |
| `siglip2-base` | 768 | 1 min | 1.9 GB | 0.93 | 0.64 |
| `clip-l14` | 768 | 5 min | 2.3 GB | 0.92 | 0.61 |
| `siglip-base` | 768 | 1 min | 1.3 GB | 0.93 | 0.58 |
| `siglip-so400m` | 1152 | 22 min | 5.7 GB | 0.93 | 0.55 |
| `clip-b32` | 512 | 24 s | 0.6 GB | 0.94 | 0.38 |

<!-- tabelas:fim -->

## Análise

### Como ler (versão simples)

Um modelo de embedding "olha" cada segundo do vídeo e o resume em números. Com isso o programa agrupa momentos
parecidos (caverna, floresta, inventário) e consegue buscar por texto ("vista da base"). A tabela mostra o quanto cada
um demora para analisar 10 horas de gameplay, a memória de vídeo que ocupa e dois acertos:

- **kNN:** momentos parecidos ficam juntos? Todos tiram ~0,93: o teste não separa os modelos, porque os rótulos vieram
  dos agrupamentos de um dos próprios modelos.
- **Zero-shot:** o modelo entende uma descrição em texto ("dark cave", "inventory menu")? Aqui há diferença real.

### O que a tabela diz

- Tamanho não garante qualidade: o `siglip-so400m` (versão 1) entende pior o texto que o `siglip-base` e é 20 vezes
  mais lento. O `siglip2-large` ganhou do `siglip2-so400m`, que é maior e mais caro.
- O `siglip2-giant` travou na carga e não foi medido (não entraria no pipeline de qualquer jeito).
- Tempos são só do modelo; a decodificação do proxy é igual para todos.

### Qual usar

| Uso no projeto | Escolha | Motivo |
|---|---|---|
| Contextos visuais de todos os segundos (3B) | `siglip2-base` | ~1 min para 10 h, 1,9 GB, zero-shot 0,64 |
| Busca de B-roll por texto, só nos trechos candidatos | `siglip2-large` | melhor entendimento de texto (0,77), 11 min para 10 h se rodasse em tudo |
| Máxima velocidade, sem busca por texto | `clip-b32` | 4 s por hora de vídeo, mas texto fraco (0,38) |

### Limites

Gabarito de 4 tipos de cena (~1.000 s) de um vídeo só, com rótulos vindos do `siglip-base`. É indício, não prova:
conferir com uma busca real de B-roll antes de fixar a versão no plano (seção 5.2).
