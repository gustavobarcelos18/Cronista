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
- **7B codificada**: `GET /media/{id}/segments`, `/events` (sinais de áudio por trecho), `/waveform` (envelope de
  energia jogo/microfone) e `/video` (master normalizado, com `Range`); contratos TypeScript gerados do Pydantic
  (`packages/contracts`, `uv run python -m cronista.contracts` + `json2ts`); Studio com lista de sessões/arquivos, player,
  waveform clicável com os segmentos sobrepostos e sinais por segmento (`apps/studio/app/revisao.tsx`).
  **Falta:** conferir no navegador com mídia real (`prod`).
- **7C parcial**: tabela só de inserção `segment_decision` (migração 0008; aceito/rejeitado/ajustado, a última linha vale),
  `POST /media/{id}/segments/{início}/decision` e botões Aceitar/Rejeitar/Ajustar no Studio. **Montagem, roteiro e Shorts já respeitam as decisões** (`review/decisions.py::load_effective_segments`).
  **Edição de roteiro:** `GET/PUT /sessions/{id}/script` (valida como o `roteiro-import`; a versão anterior vira `roteiro.v<N>.json`) e editor no Studio (`roteiro.tsx`). **Falta:** re-exportar só as etapas afetadas pelo cache por hash (botão no Studio).
- **7C completa (código):** re-exportar pelo Studio: `POST/GET /sessions/{id}/export` roda o mesmo `export_montagem` do CLI numa
  thread (uma por sessão; 409 se já rodando) e o botão em `exportar.tsx` consulta o estado. O cache por hash (plano + roteiro)
  decide o que refazer: com decisões ou roteiro iguais, a versão anterior é reaproveitada. O perfil entra injetado pela CLI
  (`create_app(profile_loader=...)`), porque só `profiles.py` e a CLI conhecem perfis. `open_db` agora serializa as migrações
  com um lock (o Alembic não é thread-safe e a API roda em threads). **Falta:** conferir com mídia real em `prod`.
