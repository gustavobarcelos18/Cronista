# Cronista

App pessoal que transforma horas de gameplay gravada no OBS em uma **timeline pré-montada no DaVinci Resolve**
(gratuito) + **roteiro de narração**, para vídeos de "100 dias". Um vídeo por série, de 30 a 50 min como referência.

**Status:** fases 1 a 9 mergeadas; Fase 10 (correções da auditoria de 2026-11-18) em andamento. A tabela de status
fica no [plano mestre, seção 7](docs/00-plano-mestre.md); o resto aponta para ela.

## Documentos

| Documento | Conteúdo |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Regras de produto que não se negociam e fluxo de trabalho |
| [docs/00-plano-mestre.md](docs/00-plano-mestre.md) | Fonte de verdade: requisitos, arquitetura, stack, fases, riscos, decisões |
| [docs/01-historico-de-decisoes.md](docs/01-historico-de-decisoes.md) | Cada pergunta do planejamento e a decisão tomada |
| [docs/glossario.md](docs/glossario.md) | Um sentido por termo (proposta, aguardando aprovação) |
| `docs/fase-N-*.md` | Plano de execução de cada fase |
| [docs/auditoria/](docs/auditoria/00-indice.md) | Auditoria de 2026-11-18 que originou a Fase 10 |

## Setup

Dois ambientes: `dev` (sem GPU; tudo roda em CPU com mocks e fixtures de FFmpeg) e `prod` (PC de casa: RTX 3060, OBS,
Resolve). O ambiente vem de `CRONISTA_ENV` (`dev` por padrão); `config/dev.yaml` e `config/prod.yaml` são versionados e os
caminhos de cada máquina ficam em `config/*.local.yaml` (fora do git).

```bash
# Engine (Python 3.12 + uv; FFmpeg no PATH)
cd services/engine
uv sync
uv run pytest                  # testes em CPU; os marcados gpu/media rodam só em prod
uv run cronista --help         # lista de comandos
uv run cronista api            # API local na porta 8000

# Studio (Node LTS + pnpm)
pnpm install
pnpm --filter @cronista/studio dev   # http://localhost:3000; NEXT_PUBLIC_ENGINE_URL aponta para a API
pnpm gen:contracts                   # regera types.ts a partir de schema.json
```

O schema dos contratos sai do Pydantic: `uv run python -m cronista.contracts` escreve `packages/contracts/schema.json`.

## Retomar em outro PC ou numa nova sessão

Clone o repositório e abra o Claude Code na pasta: o `CLAUDE.md` carrega o contexto sozinho. Para a retomada guiada,
use o prompt da seção 0 do plano mestre.

## Repositório

```
git clone https://github.com/gustavobarcelos18/Editor_De_Video.git
```

Fluxo: branch por fase (`fase/N-nome`), pull request para a `main` ao fim da fase, revisão com `/code-review` e CI no
GitHub Actions (seção 5.6 do plano mestre).
