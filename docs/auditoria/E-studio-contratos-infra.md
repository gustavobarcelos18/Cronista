# Plano E: Studio, contratos e infraestrutura

Escopo: `apps/studio`, `packages/contracts`, `packages/brand-kit`, `contracts.py`, `.github/workflows`, `config/*.yaml`,
`.gitignore`, README. Índice e ordem: [00-indice](00-indice.md).

**Diagnóstico:** os contratos estão bem resolvidos. O Pydantic é a fonte, a geração é determinística e a divergência é
checada nas duas pontas. Não há segredo nem caminho pessoal na config. O Studio funciona, mas é frágil:

- a URL do engine e o tratamento de erro estão copiados em 9 componentes;
- falhas de rede passam em silêncio;
- o SSE não se recupera;
- não há nenhum teste.

O CI cobre menos do que o CLAUDE.md promete.

## Correções (bugs)

| # | Sev. | Onde | Problema | Correção | Esf. | Etapa |
|---|---|---|---|---|---|---|
| E1 | média | `apps/studio/app/revisao.tsx:175-181` | Quatro irmãos usam `key={sessionId}`, o que dá chave duplicada e reconciliação imprevisível. | Um `<Fragment key={sessionId}>` em volta dos quatro. | P | 10A |
| E2 | média | `revisao.tsx:80`, `feedback.tsx:14`, `aprendizado.tsx:21`, `exportar.tsx:29`, `roteiro.tsx:42-48` | `fetch` sem `try/catch`: com o engine fora do ar, nada aparece na tela. O roteiro fica preso em "Salvando…". | Helper `lib/api.ts` (E6) com erro de rede e `detail`. | P | 10A |
| E3 | média | `aprendizado.tsx:14-16,26`, `exportar.tsx:15-17` | `r.json()` é feito sem checar `res.ok`: um 404 vira "undefined trechos" e toda falha vira "faltam decisões". | Checar `res.ok`. Só o 409 significa "faltam decisões". | P | 10A |
| E4 | média | `progresso.tsx:13-17` | O `onerror` fecha o SSE para sempre: jobs iniciados depois de a página abrir nunca aparecem. | Reconectar com backoff, ou polling leve de `/progress` sem stream aberto. | P/M | 10A |
| E5 | baixa | `revisao.tsx:50,87,106` | O alerta de erro nunca é limpo. | `setError(null)` no sucesso. | P | 10A |
| E7 | média | `api/app.py:284,296`, `cli.py:1512-1515` | O CORS e o bloqueio de escrita estão fixos em `:3000`. Se o Next subir em 3001, tudo falha. `NEXT_PUBLIC_ENGINE_URL` não está documentado. | `studio_origin` no `config/*.yaml` (ou `--origin`) e uma seção de setup no README. | P | 10A |
| E16 | baixa | `.gitignore` | `apps/studio/next-env.d.ts` não está ignorado. | Adicionar ao `.gitignore`. | P | 10A |

## Redundância e ambiguidade

| # | Onde | Problema | Correção | Etapa |
|---|---|---|---|---|
| E6 | `const API = ...` em 9 arquivos; `errorOf` em `embalagem.tsx:22`, inline em `acabamento.tsx:126` e `revisao.tsx:86` | A URL e o tratamento de erro estão triplicados. | `apps/studio/lib/api.ts` com `API`, `getJson`, `send` e `errorOf`. | 10A (com E2/E3) |
| E10 | `CLAUDE.md` (Stack) × plano l. 335, l. 409, `contracts.py:1` | A direção dos contratos está invertida no CLAUDE.md. | Ver [F](F-documentacao.md) (F15). | 10D |
| E11 | `README.md:4-7` | Parado na "Fase 0", sem setup. | Ver [F](F-documentacao.md). | 10D |
| E13 | `packages/contracts/types.ts:211,285,295,412,514,584` | Aliases soltos (`EndS`, `StartS`) e `Decision1`…`Decision5`, porque os `title` dos campos vazam para os tipos gerados. | Enums nomeados no Pydantic (`SegmentDecision`, `FinishDecision`…) ou remover os `title` de campo em `build_schema`. | 10C |
| E14 | `painel.tsx:36`, `exportar.tsx:29`, `acabamento.tsx:13-17`, `embalagem.tsx:14` | `?? 40` repete `TARGET_MIN`, o export ignora a meta da série e os mapas não usam os tipos gerados. | `meta_min` obrigatório no contrato, o export recebe `target_min` e os mapas viram `Record<EffectMode,…>`/`Record<Origin,…>`. | 10C |
| E15 | `config/dev.yaml`, `config/prod.yaml` × `config.py:32-51` | Os YAML repetem os defaults do código, então o mesmo valor existe em 3 lugares. | Deixar nos YAML só o que muda por ambiente (`env`, `preview_encoder`, `gpu_gate`, `audio_models`). | 10C |
| E12 | plano 5.5 l. 411 | Cita `vfx-templates/` (Remotion) e `game-mods/`, que não existem, e não lista vários módulos que existem. | Ver [F](F-documentacao.md) (F14). | 10D |

## CI e testes (10E)

- **E8:** o job `studio` em matriz Ubuntu + Windows, com o passo `pnpm --filter @cronista/studio build`.
- **E8:** `ruff` e `mypy` também em `integrations/**/*.py`.
- **E9:** Vitest + Testing Library no Studio, com o script `test` no `package.json` rodando no CI. Cobertura mínima:
  `lib/api.ts` (erro de rede, `!res.ok`, `detail`), `Waveform` e os estados de carregamento e erro da Revisão.
- **E17 (acessibilidade):**
  - `tabIndex` e teclado no waveform;
  - `aria-label` nos `textarea`;
  - ordem dos títulos;
  - trocar `prompt()` por um formulário inline no "Ajustar".

## Aceite

- Engine desligado: toda tela mostra uma mensagem de erro e nenhuma fica presa em um estado intermediário.
- Engine reiniciado: o progresso volta a aparecer sem recarregar a página.
- O CI roda `eslint`, `tsc`, `next build` e `vitest` em Ubuntu e Windows.
- Nenhuma constante de URL fora de `lib/api.ts`.
