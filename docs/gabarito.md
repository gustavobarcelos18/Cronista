# Gabarito: formato e como anotar

Decisão D3 (histórico §26): o gabarito é um **CSV** anotado à mão, validado por `cronista gabarito`. Há uma UI mínima de anotação em `cronista gabarito-ui`; a revisão completa só chega com o Studio (Fase 7). Ele é obrigatório a partir da Fase 2: mede o WER, os eventos de áudio, farm × momento e menus.
Começar pela gameplay de teste de ~30 min; meta total de 2–3 h, com dois gêneros de jogo.

## Formato

```csv
inicio,fim,classe,nota
0:12.5,0:15,fala,"apresentando o dia"
1:02,1:40,farm,"colhendo trigo"
```

- Cabeçalho exato: `inicio,fim,classe,nota`. Aceita `;` no lugar de `,` (Excel em pt-BR) e UTF-8 com BOM. Linhas começadas
  com `#` são comentários.
- Tempo: segundos (`83.5`), `m:ss(.fff)` ou `h:mm:ss(.fff)`, **dentro do arquivo anotado** (não do projeto).
  A validação converte para quadros inteiros a 60 fps (histórico §38).
- `nota` é livre; nas classes `objetivo` e `estado` ela diz qual objetivo/estado (Fase 5A) e é obrigatória (aviso se faltar).
- Classes podem se sobrepor (a `fala` acontece durante um `farm`); a mesma classe sobreposta a ela mesma gera aviso.

## Classes (proposta inicial, histórico §39)

| Classe | O que anotar | Quem usa |
|---|---|---|
| `fala` | o criador falando | Fase 2: WER do Whisper |
| `risada`, `exclamacao` | risada e exclamação/grito de emoção alta (`grito` é apelido legado; histórico §46) | Fase 2: classificador de eventos |
| `teclado`, `respiracao` | ruído que **não** deve gerar evento | Fase 2: aceite (falsos positivos) |
| `farm` | trecho repetitivo/rotina | Fases 2 e 4: rotina, timelapse |
| `momento` | momento legal | Fase 4: ≥ 85% no topo dos candidatos |
| `menu`, `loading`, `idle` | tela sem jogo ativo | Fase 3: detecção sem perfil de jogo |
| `cinematica`, `construcao` | cinemática e obra | Fases 3 e 4 |
| `objetivo`, `estado` | objetivo declarado e mudança de estado | Fase 5A |

Classe nova entra por decisão (plano + histórico), nunca em silêncio: o validador recusa classe desconhecida.

## Validar e conferir de ouvido

```bash
cd services/engine
uv run cronista gabarito ../../data/gabarito/teste.csv --video "<vídeo>"
uv run cronista gabarito ../../data/gabarito/teste.csv --video <vídeo> --previa ../../data/gabarito/previa
```

Sem `--video` ele só valida o CSV. Com `--video` confere que nenhum `fim` passa da duração. Com `--previa` grava um
MP4 curto por anotação (`NNN-classe.mp4`, o `NNN` é a linha do CSV) para conferir se o recorte bate com o que foi anotado.
Sai com código 1 se houver erro; avisos não impedem o uso.
