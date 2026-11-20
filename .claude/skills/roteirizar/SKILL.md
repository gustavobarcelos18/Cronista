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

## Molde do canal (histórico §67, `docs/referencias/estilo-do-canal.md`)

Extraído dos vídeos de "100 dias" do próprio criador. Ele **organiza** o roteiro; as regras acima continuam valendo (fala
ao vivo primeiro, só fatos do pacote, falas dentro das `lacunas`, `segment_id` obrigatório). Fato que o molde pede e o
pacote não tem **não se inventa**: omita a frase e liste a falta em `pendencias.md`, ao lado do `roteiro.json` (ver Saída).

1. **Gancho (abertura do vídeo, até 45 s).** Janela reservada do pacote (`reservas`, `segment_id` **`@gancho`**): é gravada
   à parte, não depende de lacuna e o validador não confere fala ao vivo ali (exceção declarada, histórico §67). Em ordem, uma
   ideia por fala, sem `start_s` (as falas se encadeiam sozinhas):
   - a premissa em uma frase: o jogo (`projeto.jogo`) e o que o torna diferente. O que torna diferente (mods, regra de
     jogo, desafio) só entra se estiver no pacote (objetivo do tipo `restricao`, ou fala ao vivo do criador);
   - a promessa de dias, só se o número de dias estiver no pacote;
   - os **objetivos** de `objetivos` com `confirmado: true`: "Primeiro…", "Segundo…", "Terceiro, e mais importante…",
     um por fala; `principal` por último ("mais importante"); `restricao` descrita como regra numerada ("a primeira
     regra…", "uma vida, um erro"). Com um só objetivo, uma frase basta (nas referências há de 1 a 3);
     nunca cite objetivo `incerto` nem não confirmado;
   - o convite ao like, curto e encaixado na fala, e a virada para o relato ("a minha jornada começa agora", como o criador diz). É a única
     fala sem fato do pacote; **o criador decide se fica**: marque com `"justification": "convite do criador: confirmar"`
     (o `kind` continua `narracao`; o validador só aceita `narracao` e `antecipacao`).
2. **Relato (capítulos).** Primeira pessoa, **passado**, blocos curtos: o que fez e por quê ("Pra não arriscar o bote, arrastei
   ele até a praia"). Complementa a fala ao vivo e **volta a ela** logo depois: nunca emende duas falas de narração
   seguidas sem uma fala ao vivo no meio, quando o beat tiver fala ao vivo. Não diga "dia N" a cada trecho: a marcação
   de dias é do contador na tela; a narração só aponta o dia quando importa ("17 dias depois do assalto…").
3. **Fecho (final do vídeo, até 35 s).** Janela reservada, `segment_id` **`@fecho`**, sem `start_s`. Em ordem: o final do jogo ou do desafio e o que ele significa
   (só fatos do pacote); o balanço dos objetivos pelo `estado` (`concluido`, `falhou`, `abandonado`), com o motivo se estiver
   no pacote e **preservando o fracasso**; o convite à comunidade (Discord, lista de mods na descrição) e a despedida curta.
   Convite e despedida são do criador: marque com a mesma `justification` e não os invente com nome ou link.
   O fecho do canal tem **três formas** (perfil, seção 2): balanço com números e despedida; terminar na cena final do
   jogo (o fecho vira só o agradecimento e a despedida); ou gancho para a próxima parte, sem despedida. Escolha pela
   situação do pacote (objetivos concluídos, fim da série ou série em andamento) e, na dúvida, pergunte ao criador.
4. **Densidade.** Mais fala de narração no gancho e no fecho que no meio; no meio, só onde há lacuna e algo a explicar.
   No relato, sem lacuna, sem fala (o validador recusa); só `@gancho` e `@fecho` dispensam lacuna.

## Saída

Arquivo `roteiro.json`:

```json
{"version": 1, "provider": "claude", "lines": [
  {"segment_id": "<segmento_id do beat>", "text": "fala em português falado", "start_s": 123.0},
  {"segment_id": "...", "text": "...", "kind": "antecipacao", "justification": "por que mostrar antes"}
]}
```

`segment_id` vem do campo `segmento_id` do beat (obrigatório: cada fala é ligada a um segmento).
Se o molde pediu algo que o pacote não traz (número de dias, o que torna o jogo diferente, motivo de um objetivo
falhar), escreva `pendencias.md` ao lado: uma linha por falta, para o criador completar na gravação.
Depois valide: `uv run cronista roteiro-import <sessão> roteiro.json` (gera também o SRT) e
`uv run cronista roteiro-lint roteiro.json`. Corrija o que o validador apontar antes de entregar.
