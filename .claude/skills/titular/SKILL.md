---
name: titular
description: Escreve 3 a 5 sugestões de título do vídeo da série a partir do titulo-pack.json do Cronista (até 70 caracteres, só fatos do pacote, sem isca de clique). Use depois de `cronista titulos <sessão>`.
---

# /titular

Escreve `titulos.json` para a sessão. Entrada: `data/<ambiente>/packaging/<sessão>/titulo-pack.json`
(gerado por `cronista titulos <sessão>` a partir do story-pack).

## Regras (plano mestre, seção 6.7; fase 9C)

1. **Só fatos do pacote.** Objetivo principal e estado, abertura, desfecho e momentos de maior nota. Nada inventado.
2. **Sem número de dia.** O "dia" é decidido na edição; título com "Dia 37" ficaria errado.
3. **Sem isca de clique.** Nada de "você não vai acreditar", "mudou tudo", "chocante", caixa alta, "!!". O validador recusa.
4. **Fracasso é fato.** Se o `desfecho` é `falha`, o título assume (ex.: o que deu errado, quantas tentativas), sem esconder nem dramatizar.
5. **Até 70 caracteres**, pt-BR, frase de pessoa falando. Varie o ângulo entre as opções (objetivo, obstáculo, desfecho).
6. **`reason` em cada título:** o fato do pacote em que ele se apoia (o criador confere).
7. Depois de escrever, rode `/humanizar` nos títulos e confira de novo contra o pacote.
8. **`thumbnail_texts`:** 2 a 3 textos para a imagem de capa, de 2 a 4 palavras e até 28 caracteres (ex.: "Morri de novo",
   "O Nether, enfim"). Fato curto do pacote, sem isca de clique, sem número de dia e sem repetir o título palavra por palavra.

## Saída

```json
{"version": 1, "provider": "claude", "titles": [
  {"text": "Sobrevivi 100 dias só com pedra", "reason": "objetivo principal; estado concluído"},
  {"text": "...", "reason": "..."}
], "thumbnail_texts": ["Pedra por 100 dias", "Sem nada além de pedra"]}
```

Valide e guarde: `uv run cronista titulos-import <sessão> titulos.json`. Corrija o que o validador apontar.
O criador escolhe com `cronista titulos-escolher <sessão> --sugestao N` (ou `--texto "..."` para o dele); só a escolha
dele fica registrada.
