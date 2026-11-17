# Fase 5 e 5A — Narrativa, objetivos e roteiro

Plano de execução (primeira entrega por regras, 2026-11-17; histórico §52). Roda em `dev` (CPU), sem modelo nem Claude
no código: o Claude Code entra pelas skills do repositório.

## Entrega

| Peça | Onde | O que faz |
|---|---|---|
| Memória narrativa (5A) | `db/models.py`, migração `0007` | `objective`, `objective_state` (só inserção, `replaces_id`), `narrative_event`, `narrative_link` (relação sem evidência = hipótese). Evidência embutida (`ev_*`); a tabela `evidence` normalizada fica para o Studio |
| Objetivos (5A) | `story/objectives.py` | Extrator por regras pt-BR (porta `ObjectiveExtractor`, o LLM local entra depois); **citação literal verificada** na transcrição; **declaração não é conclusão** (conclusão só com marcador de conquista por perto, senão `incerto`); comentário hipotético ignorado; objetivos/regras do perfil YAML; fila de revisão em CSV (`cronista revisao`) |
| Arco | `story/arc.py` | Capítulos (corte em `novo_dia`, sem número), beats (setup, conflito, falha, virada, conquista) por regras, alocação do tempo-alvo por capítulo |
| Story-pack | `story/pack.py` | `story-pack.json` compacto: beats, razões da nota, **fala ao vivo com transcrição**, **lacunas livres**, objetivos com estado e citação, regras editoriais; corta transcrições dos trechos de menor nota se passar do teto |
| Roteiro | `story/script.py` | Espaços sem fala, estimativa de duração (2,6 palavras/s), `NullProvider` (padrão), `LocalScriptProvider` (experimental, porta `TextGenerator`), validação (segmento existente, antecipação justificada, cabe no espaço), lint de sinais de IA, SRT, perfil de voz |
| Skills | `.claude/skills/roteirizar`, `humanizar` | Instruções para o Claude Code; `humanizar` adaptada do Humanizer (MIT) |
| CLI | `story`, `revisao`, `roteiro-import`, `roteiro-lint` | Gera o pacote; fila de revisão; valida o `roteiro.json` e gera o SRT; lint |

Fluxo: `cronista analyze` → `relevance` → `story` → `/roteirizar` (Claude Code) → `/humanizar` → `roteiro-import`.

## Pendente (ajustes depois da codificação)

- Gabarito de objetivos e estados e números de corte da 5A (precisão/revocação); hoje o extrator é por regras simples.
- Adaptador do LLM local para o extrator de objetivos e para o `LocalScriptProvider`, e benchmark de roteiro.
- Eventos narrativos e relações automáticas (as tabelas existem, nada as preenche ainda); resumos por escopo.
- SRT em tempo de timeline (a Fase 6 remapeia); o SRT atual está em tempo do arquivo de origem.
- Roteiro de uma sessão real lido pelo criador sem soar artificial (aceite qualitativo).
