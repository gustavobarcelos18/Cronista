# Transcrição de fala

Comando: `cronista bench-audio-quality --speech`.

<!-- tabelas:inicio (gerado por `cronista bench-report`; não edite aqui) -->

| Modelo | 10 h de áudio em | x tempo real | VRAM | WER | Trechos |
|---|---|---|---|---|---|
| `whisper-turbo` | 31 min | 19.2x | 1.3 GB | 1.1% | 54 |
| `whisper-large-v3` | 57 min | 10.6x | 2.2 GB | 3.1% | 38 |

<!-- tabelas:fim -->

## Análise

### Como ler (versão simples)

WER é a porcentagem de palavras erradas na transcrição (menos é melhor). Comparei o Whisper "turbo", que o projeto já
usa, com o Whisper "large-v3" completo, no mesmo áudio de 287 s com fala normal, rápida, baixa, risadas e gritos.

### O que a tabela diz

- O **turbo** errou 1,1% das palavras e processa 10 h em ~31 min; o **large-v3** errou 3,1% e leva ~57 min.
- O large-v3 junta várias frases num trecho só e pontua melhor, mas não reduziu o erro neste teste.
- A primeira medição deu 217% de erro para o large-v3: era defeito da métrica (cada frase do gabarito recebia o texto
  inteiro do trecho). Foi corrigido comparando palavra a palavra, pelo tempo de cada palavra.

### Qual usar

| Uso no projeto | Escolha | Motivo |
|---|---|---|
| Transcrição de todas as sessões | `whisper-turbo` (o atual) | mais rápido, menor erro, menos VRAM (1,3 GB) |
| Trechos curtos em que a fala é decisiva para o roteiro | manter o turbo | o large-v3 não compensa o dobro do tempo |

### Limites

O gabarito de fala foi montado corrigindo as sugestões do próprio Whisper turbo, então o WER do turbo é otimista e
favorece o turbo em relação ao large-v3. Os dois ficaram abaixo de 5%, então a diferença real é pequena. Parakeet e
Canary ficaram de fora: os modelos Parakeet do `transformers` são só em inglês e o multilíngue exige o NeMo.
