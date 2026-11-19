---
name: roteirizar
description: Escreve o roteiro de narração do vídeo a partir do story-pack.json do Cronista (falas curtas, só nos espaços sem fala ao vivo, em pt-BR falado). Use depois de `cronista story <sessão>`.
---

# /roteirizar

Escreve `roteiro.json` para a sessão. No vídeo da série (`cronista story --projeto N`), "a sessão" é a **sessão
âncora** (a primeira do projeto, número impresso pelo comando): use esse número em todos os comandos abaixo. Entrada: `data/<ambiente>/story/<sessão>/story-pack.json` e `voice-profile.json`.

## Regras (plano mestre, seções 6.3 e 6.8)

1. **Fala ao vivo tem prioridade.** Nunca escreva sobre um trecho em `fala_ao_vivo`; só dentro das `lacunas` de cada beat.
   Dê continuidade ao que o criador já disse (leia os `texto` das falas ao vivo).
2. **Complemento, não descrição.** Explique decisão, porquê, o que vem a seguir e o que o criador estava pensando.
   Nunca narre o que o público acabou de ver.
3. **Só fatos do pacote.** Nada de nome, número ou acontecimento que não esteja nele. Fato concreto no lugar de adjetivo;
   o suspense vem de fato, não de frase de efeito.
4. **Cronologia por padrão.** Antecipação só para dar vontade de assistir ou ilustrar narração com cinemática, sem
   distorcer fatos. Toda antecipação leva `"kind": "antecipacao"` e `"justification"`.
5. **Fim direto.** Se o desfecho real foi fracasso, preserve o fracasso (beat `falha`).
6. **Tom do criador.** Use `voice-profile.json` (tamanho de frase, bordões, palavras frequentes). Frases curtas, de um
   fôlego (até 28 palavras, o limite do `roteiro-lint`). Sem voz de IA: depois de escrever, rode `/humanizar`.
7. **Duração.** Cada fala cabe nas `lacunas` do seu beat (≈ 2,6 palavras por segundo). O criador corta se ficar curto
   ou estende se ficar longo; o roteiro não depende da duração prevista.

## Saída

Arquivo `roteiro.json`:

```json
{"version": 1, "provider": "claude", "lines": [
  {"segment_id": "<segmento_id do beat>", "text": "fala em português falado", "start_s": 123.0},
  {"segment_id": "...", "text": "...", "kind": "antecipacao", "justification": "por que mostrar antes"}
]}
```

`segment_id` vem do campo `segmento_id` do beat (obrigatório: cada fala é ligada a um segmento).
Depois valide: `uv run cronista roteiro-import <sessão> roteiro.json` (gera também o SRT) e
`uv run cronista roteiro-lint roteiro.json`. Corrija o que o validador apontar antes de entregar.
