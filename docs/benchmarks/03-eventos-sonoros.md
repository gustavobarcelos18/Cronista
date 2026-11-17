# Eventos sonoros (risada e exclamação)

Comando: `cronista bench-audio-quality --events`.

<!-- tabelas:inicio (gerado por `cronista bench-report`; não edite aqui) -->

| Modelo | 10 h de áudio em | VRAM | Risada (precisão / revocação) | Exclamação (P / R) | Eventos |
|---|---|---|---|---|---|
| `ast-mic` | 21 min | 0.9 GB | 1.00 / 1.00 | - / 0.00 | 1 |
| `clap-mic` | 35 min | 1.3 GB | 0.17 / 1.00 | 0.29 / 0.62 | 23 |
| `clap-fused-mic` | 37 min | 1.1 GB | 0.04 / 1.00 | 0.36 / 0.62 | 36 |

<!-- tabelas:fim -->

## Análise

### Como ler (versão simples)

Testei se um modelo de som reconhece a risada e a exclamação (grito de empolgação) do criador no microfone. **Precisão**
é "dos eventos que o modelo marcou, quantos eram reais"; **revocação** é "dos eventos reais, quantos o modelo achou".

### O que a tabela diz

- **AST (o atual):** marcou 1 risada e acertou (precisão e revocação 1,0). Não produz exclamação no microfone por
  desenho (o rótulo "grito" é descartado lá; a exclamação vem da heurística de energia e altura).
- **CLAP (`unfused` e `fused`):** achou a risada (revocação 1,0), mas gerou 23 a 36 eventos curtos contra 1 esperado,
  então a precisão fica em 0,04 a 0,17 (parte disso é a risada longa quebrada em vários pedaços; seria preciso juntar
  eventos vizinhos). Na exclamação acertou 5 de 8 (revocação 0,63), com precisão de 0,29 a 0,36.
- Para comparação, a heurística de exclamação atual acertou 0 de 8 neste mesmo teste (histórico §46).

### Qual usar

| Uso no projeto | Escolha | Motivo |
|---|---|---|
| Risada | `ast-mic` (janela de 2 s) | única com precisão alta; CLAP gera falsos alarmes demais |
| Exclamação | CLAP como candidato, **não adotar ainda** | revocação 63% contra 0% da heurística, mas precisão baixa: precisa de limiar e de cruzar com energia da voz |
| Eventos do jogo (explosão, música) | `ast` na faixa do jogo | já no pipeline; não foi o foco deste teste |

### Limites

O gabarito tem 1 risada (de 7,6 s) e 8 exclamações em 84 s: um número muito pequeno. As frases do CLAP são um primeiro palpite e
mudam o resultado. O PANNs ficou de fora por falta de tempo e o BEATs porque o código não está no `transformers`.
