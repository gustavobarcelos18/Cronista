# Plano F: Documentação (ambiguidade, redundância e contradições)

Escopo: `CLAUDE.md`, `README.md`, `docs/00-plano-mestre.md` (P), `docs/01-historico-de-decisoes.md` (H),
`docs/fase-*.md`, `docs/gabarito.md` e as skills. Índice e ordem: [00-indice](00-indice.md).

**Regra que vale para todo o plano:** nunca apagar. Toda correção marca o trecho antigo como
`[SUBSTITUÍDA por H §N, data]` e aponta para a passagem vigente. Os números de linha são da auditoria (commit
`1d66ce2`) e podem ter se deslocado.

## 1. Contradições e decisões substituídas que ainda aparecem como vigentes

| # | Sev. | Onde | Problema | Correção |
|---|---|---|---|---|
| F1 | alta | P:599-601, P:625-627 × H §57(3)(19), P:1011, P:1075 | Música, SFX, meme e piada visual aparecem como "100% automáticos" (§40-4). O §57 decidiu que humor e impacto nascem só como `sugerir`. | Marcar P:600 e P:626 como substituídas em parte por H §57(3)(19). |
| F2 | alta | P:291-293, P §4.1 × `cli.py:721,965,1048,1188,1470`, skills `roteirizar`/`titular` | O produto é um vídeo por série, mas toda a narrativa e a montagem trabalham por sessão. Nenhum documento registra essa lacuna. | Registrar a lacuna em P §7/§9 e no H. As skills passam a dizer "pacote por sessão até existir a série". Ver B1. |
| F3 | alta | P:193, P:237, P:1250, H:54 × H §51, `fase-4`:12 | O lookback aparece como 60–90 s, mas o vigente é 25/20/30 s por tipo. | Marcar como substituído por H §51 e atualizar o P §4. Ver B13. |
| F4 | alta | P:337, P:739, P:783, P:982, P:1160; EDL em P:596, P:764, P:982 | "OTIO → FCPXML (+ EDL)" e os marcadores por EDL aparecem como vigentes, mas o spike decidiu "FCPXML 1.9 à mão + Lua de marcadores" (P:715-724, H §39). | Marcar as linhas e atualizar a tabela 5.2 e a Fase 6. |
| F5 | média | P:715 × P:733; checklist P:758-787 | O FCPXML próprio aparece como ✅ e também como "ainda sem resposta". O checklist não foi atualizado. | Marcar cada item do checklist com ✅/❌ e um ponteiro. |
| F6 | média | P:862, `fase-1`:6 × H §41 | O "microfone em duas fontes" / `MIC_RAW` ainda aparece como pendente. | Marcar como substituído por §41. |
| F7 | média | P:586, P:621, P:1143, P:411 (`vfx-templates/`) × H §57(18), P:1009 | O Remotion ainda aparece como caminho das cartelas e VFX. | Marcar como substituído. Na árvore 5.5, tirar a pasta ou marcá-la "futura". |
| F8 | média | `fase-9`:12,40 × H §58(11), P:1083, `pyproject.toml` | Diz "FFmpeg/Pillow", mas a decisão é "sem Pillow". | Trocar por "FFmpeg (sem Pillow)". |
| F9 | média | P:996-1000 × P:1073 (H §56) | A Fase 7 descreve o modelo local interpretando o feedback como algo vigente, mas o §56 diz que o texto só é guardado até o benchmark. | Dizer que esse é o alvo e que hoje o texto só é guardado. |
| F10 | média | P:378 (5.4), P:287 × `fase-4`:12 e código | Três listas diferentes de classes de segmento. | O glossário fixa as classes reais do código (`momento`, `dia`, `conversa`, `farm`, `jogo`, `descartavel`). A 5.4 vira "modelo-alvo". |

## 2. Status e "em aberto" desatualizados

| # | Onde | Correção |
|---|---|---|
| F11 | Status desatualizado em vários lugares: `README.md:6` ("começar a 1A"); P:6 e P:21-22 ("detalhar a Fase 1"); P:1202-1204; `fase-1`:6 ("a ser integrada" e "já integrada" na mesma frase); `fase-2`:6 (2C "bloqueada", mas mergeada no PR #10); `fase-3`:7 (3C "não começou", mas a 3C-1 a 3C-4 existem). | Uma **tabela de status única** em P §7: fase, sub-etapa, PR, status e pendências em `prod`. README, fases e CLAUDE.md passam a apontar para ela. |
| F12 | P §9 "Em aberto". Já decididos: item 1 (spike, H §39); item 2 FIFINE (P:1209, P:1259 × P:276); item 7 OpenAPI (decidido em D2); item 10 Shorts de 608 px (H §58-3); teclado 60% "antes da Fase 3" (P:1239-1241); P:125 "cobrir sessão ou trechos" (H §53). Ainda sem dono: item 9 (`cronista render`, P:1256). | Riscar cada item com o ponteiro da decisão. Converter "Em aberto" numa tabela (id, pergunta, fase-prazo, status). |
| F13 | `cronista render` em P:643, P:751 e `fase-6`:42 (não existe); `cronista bench` em `fase-2`:79 (os comandos reais são `bench-audio`/`bench-video`…); `gabarito.md:3` diz "Não há UI", mas existe `gabarito-ui` (`cli.py:860`). | Marcar `render` como "não implementado" e corrigir os nomes dos comandos e o gabarito. |
| F18 | 38 ⚠️ no P e 23 no H, muitos já respondidos pelo spike. Critérios sem número: "WER aceitável" (P:893), "alta precisão" (P:905), P:1233. P:977 deixa números "para o início da 5A", que já foi implementada (H §52). | Revisar os ⚠️ seção a seção, convertendo em ✅/❌ com ponteiro. Pôr número nos critérios ou apontar para o benchmark que os fixou. |

## 3. Estrutura e fatos de código

| # | Onde | Correção |
|---|---|---|
| F14 | Árvore 5.5 (P:385-421): diz `vision/` (o real é `video/`), `profiles/` (o real é `profiles.py`) e `adapters/` no topo; cita `vfx-templates/` e `game-mods/`, que não existem; não lista `mix/`, `shorts/`, `thumbnails/`, `packaging/`, `review/`, `recorder/`, `preview/`, `integrations/fifine` e `cuda`. Layout de dados `data/projects/<id>` × o real `data/{packaging,shorts,story}/<sessão>`. | Regenerar a árvore e o layout de dados a partir do repositório, num anexo gerado (ex.: `uv run python -m cronista.devtools.tree`) com `cronista --help`. |
| F15 | `CLAUDE.md` (Stack) e P:409 dizem "JSON Schema → Pydantic/TS". | Corrigir para "Pydantic → JSON Schema → TS (D2)". **Afeta toda sessão do Claude Code: prioridade alta.** |
| F17 | Termos sobrecarregados: capítulo (OBS × dia × unidade genérica), momento (tecla × classe × tipo), EDL (CMX × `edit_plan`), pacote (story-pack, titulo-pack, exportação, publicação, "pacote completo" de efeitos), perfil (jogo, voz, dev/prod), trecho × segmento, **Studio (app) × Resolve Studio** (P:584, P:942 × P:674-677, P:756, P:1020, P:1049). | `docs/glossario.md` ([T4](T-transversal.md)), com uso consistente nos documentos: "Studio" sempre quer dizer o app e "Resolve Studio" é sempre escrito por extenso. |
| F21 | `docs/gabarito.md:39` traz um caminho pessoal absoluto. | Trocar por `<vídeo>`. |
| C17 | A `fase-6` (relink relativo, `marcadores.json`) diverge do código (URI absoluta, sem `marcadores.json`). O kit do Resolve ainda manda instalar em `Scripts\Utility`. | Atualizar o doc da fase e marcar o kit como superado pelo Console Lua. |

## 4. Redundância: fonte única por assunto

| Assunto | Hoje aparece em | Fonte única | Os outros passam a ter |
|---|---|---|---|
| Faixas de áudio e microfone | CLAUDE.md:28-29, P:145-154, P:1093-1095, P:1106-1107, H §41, `fase-1` | P §2 | Regra curta + "§2" |
| Duração-alvo 30–50 min | CLAUDE.md:5, P:51, P:77-80, P:286, P:373, P:1091, P:1196 | P §1 | Ponteiro |
| Resultado do spike | P:709-736, P:1096, `fase-6`:8-15 | P §6.5 | Ponteiro |
| Benchmarks na Fase 2, cartelas | P:1119 e P:1172; P:1135 e P:1143 | Seção temática | Ponteiro |
| Status de fase | README, P, fase-N | P §7 (tabela) | Ponteiro |

H §50 mistura as decisões da 3C com o B-roll (H:1282-1288), e H §59 (11-17) vem depois de H §58 (11-18). **F20:**
criar uma entrada própria para a 3C e manter a ordem cronológica. A §9 do P também está fora de ordem.

## 5. Estrutura proposta (sem apagar nada)

1. **`docs/glossario.md`**, fonte única dos termos. O CLAUDE.md e o P passam a citá-lo.
2. **P §9 só com ponteiros:** `D-NN: frase curta → §seção, H §N`. O detalhe fica na seção temática e no H.
3. **Marcação padrão de substituída:** `~~texto~~ [SUBSTITUÍDA por H §N, data]` no ponto original. Cada entrada do H
   ganha o campo `substitui: §X`.
4. **Status num lugar só:** tabela em P §7.
5. **CLAUDE.md enxuto:** só as regras inegociáveis, cada uma com o "§N" da fonte, sem listas copiadas.
6. **Fase-N:** um cabeçalho "Status → P §7" e só as tarefas e decisões locais, citando "H §N".
7. **"Em aberto" como tabela**, revisada obrigatoriamente no fim de cada fase. Acrescentar esse passo ao fluxo do
   CLAUDE.md.
8. **Anexo gerado:** a árvore 5.5 e a lista de comandos (`cronista --help`), nunca escritas à mão.

## Ordem dentro da 10D

1. F15 (CLAUDE.md: contratos) e F11 (status), porque induzem erro em toda sessão.
2. Glossário (F17, F10).
3. Contradições F1–F9, com as marcas de substituída.
4. "Em aberto" e ⚠️ (F12, F18), comandos (F13), árvore (F14).
5. Redundância (seção 4) e reorganização do H (F20).
6. README novo, com setup de dev e prod (`uv sync`, `pnpm install`, `cronista api`, `NEXT_PUBLIC_ENGINE_URL`,
   `CRONISTA_ENV`, `*.local.yaml`).

## Aceite

- Nenhuma passagem do P, das fases, do CLAUDE.md ou das skills afirma como vigente algo marcado como substituído no H.
- Todo comando citado nos documentos existe no `cronista --help`, ou está marcado como "não implementado".
- O status de cada fase aparece num único lugar.
