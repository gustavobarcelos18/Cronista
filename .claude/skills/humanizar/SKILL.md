---
name: humanizar
description: Tira sinais de texto "de IA" de uma narração falada em pt-BR (audita, reescreve e confere contra os fatos), sem achatar o suspense. Use depois de /roteirizar.
---

# /humanizar

Adaptado do [Humanizer](https://github.com/blader/humanizer) (licença MIT, © autores do projeto original; aviso e crédito
mantidos), que parte do guia da Wikipédia sobre sinais de texto escrito por IA. Esta versão é para **narração falada** em
português do Brasil.

## Fluxo

1. **Auditar:** marque cada sinal, do mais forte ao mais fraco (`uv run cronista roteiro-lint roteiro.json` acha os
   mecânicos; leia o resto você mesmo).
2. **Rascunhar** a reescrita só das falas com sinal.
3. **Conferir** contra os padrões e contra os fatos do `story-pack.json`.
4. **Versão final.** Nunca mude o que aconteceu no jogo. Onde o texto ficar genérico, troque por um detalhe concreto e
   verdadeiro tirado do pacote.

## Padrões que valem para fala

"Não é X, é Y"; frase de efeito e fechamento dramático; "lição" de profundidade falsa; rodeio antes do ponto; responder
objeção que ninguém fez; tríade forçada; frases começando sempre igual; vocabulário inflado; importância exagerada; tom de
vendedor; autoridade vaga ("dizem que…"); evitar o simples "é/tem"; resíduo de chatbot; explicar o que o público acabou de
ver. Os "fracos sozinhos" (excesso de qualificadores, voz passiva) só contam quando aparecem juntos.

Não se aplicam (o texto é lido em voz alta): negrito, títulos, emojis, setas, aspas curvas.

## Acréscimos para pt-BR falado

Muletas de texto escrito ("vale ressaltar", "nesse sentido", "em suma", "jornada", "épico" em toda frase); frases longas
demais para um fôlego (mais de ~28 palavras); gerúndio em cascata.

## Cuidados

- **Não ache o suspense:** corte a frase de efeito e o adjetivo, mas o suspense deve vir de fato concreto do pacote.
- **Voz do criador:** use `voice-profile.json` (bordões, gírias, tamanho de frase) como amostra de estilo.
- Mantenha cada fala no `segment_id` e dentro do espaço livre; confira com `uv run cronista roteiro-import`.
