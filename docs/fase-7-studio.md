# Fase 7 — Studio de revisão e aprendizado

Plano de execução (detalhes do produto na seção "Fase 7" do [plano mestre](00-plano-mestre.md)). Revisão acontece
**antes** de exportar; o caminho continua de mão única app → Resolve.

## Subfases

- **7A — API local do engine (`cronista api`)**: FastAPI só leitura (sessões, arquivos, jobs, marcadores). CORS só para
  `localhost:3000`. Aceite: testes com `TestClient` verdes; sobe com `cronista api`.
- **7B — Lista de segmentos e player**: endpoint de segmentos/plano de montagem, servir mídia com `Range`, tela no Studio
  com player, waveform e sinais de cada segmento (contratos TypeScript gerados do Pydantic).
- **7C — Decisões do criador**: aceitar/rejeitar/ajustar limites; tabela só de inserção (padrão 5A); edição de roteiro;
  re-exportar pelo cache por hash (só as etapas afetadas).
- **7D — Jobs em tempo real e painel da série**: progresso por SSE; visão da série (seção 4.1).
- **7E — Aprendizado**: recalibração dos pesos por manter/tirar trecho (modelo simples e explicável) + feedback em texto
  livre (Q26/Q27) interpretado por LLM local em JSON Schema, só se passar a precisão mínima do benchmark.

## Estado (2026-11-17)

- **7A codificada** (`api/app.py`, `cronista api`, `tests/test_api.py`): `/health`, `/sessions`, `/sessions/{id}`,
  `/sessions/{id}/jobs`, `/sessions/{id}/markers`. Só `GET`; escrita entra na 7C.
