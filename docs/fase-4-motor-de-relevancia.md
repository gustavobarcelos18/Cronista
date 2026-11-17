# Fase 4 — Motor de relevância

Plano de execução. Fonte: plano mestre, seção 7 (Fase 4) e histórico §51. Roda em `dev` (CPU): funções puras sobre
eventos e marcadores já gravados no banco, sem GPU nem modelo.

## Entrega (2026-11-17, primeira versão por regras)

| Peça | Onde | O que faz |
|---|---|---|
| Fusão e segmentação | `relevance/engine.py` | Grade de 1 s com fala, risada/exclamação, menu/loading/idle e contextos; trecho de marcador com **lookback por tipo** encostado nas fronteiras naturais (início de fala, mudança de cena); trechos livres cortados por regime (pausa, fala, jogo calado), mudança de contexto e `max_s` |
| Nota explicável | idem | `marcador + emoção + fala + novidade − pausa`; cada segmento guarda `razoes` |
| Classes | idem | `momento`, `dia`, `conversa`, `farm`, `jogo`, `descartavel` |
| Persistência | `relevance/service.py` | Eventos `segmento` (etapa `relevance`), substituídos a cada execução |
| Métricas | `relevance/quality.py` | Momentos do gabarito no topo (meta 85%), farm (revocação/precisão), compressão |
| CLI | `cronista relevance`, `bench-relevance`, `series` | Candidatos com razões; métricas contra o gabarito; painel da série |

## Pendente (ajustes depois da codificação)

- Calibrar pesos e limiares (`RelevanceParams`) com gabarito real (`momento`, `farm`); hoje são valores iniciais.
- Eventos `rotina` (periodicidade) para reforçar o farm; hoje farm = pouca fala, sem emoção, ≥ 60 s.
- Seleção de trechos relevantes dentro de fala longa e agrupamento de tentativas repetidas: dependem dos estados da
  Fase 5A (viabilidade não comprovada).
- Painel da série no relatório HTML (hoje só `cronista series`, em texto).

## Aceite

≥ 85% dos momentos do gabarito no top de candidatos; farm identificado como farm (medido com `bench-relevance`).
