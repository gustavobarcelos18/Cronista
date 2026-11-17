"use client";

import type { SeriesPanelOut } from "@cronista/contracts";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

const SITUACAO: Record<SeriesPanelOut["situacao"], string> = {
  faltando: "ainda falta material",
  no_alvo: "dentro da meta",
  acima: "acima da meta (dá para cortar)",
};

export default function Painel() {
  const [panel, setPanel] = useState<SeriesPanelOut | null>(null);

  useEffect(() => {
    fetch(`${API}/series`)
      .then((r) => r.json() as Promise<SeriesPanelOut>)
      .then(setPanel)
      .catch(() => setPanel(null));
  }, []);

  if (!panel) return null;
  const meta = panel.meta_min ?? 40;
  const pct = Math.min(100, (panel.total_min / meta) * 100);
  return (
    <section aria-label="Painel da série">
      <h3>Série</h3>
      <progress value={pct} max={100} style={{ width: "100%" }} />
      <p>
        <strong>{panel.total_min} min</strong> de {meta} · {SITUACAO[panel.situacao]}
      </p>
      <ul>
        {Object.entries(panel.por_classe_min ?? {}).map(([classe, min]) => (
          <li key={classe}>
            {classe}: {min} min
          </li>
        ))}
      </ul>
      <small>
        {panel.sessoes.map((s) => `sessão ${s.sessao}: ${s.gravado_h} h → ${s.produto_min} min, ${s.dias} dias`).join(" · ")}
      </small>
    </section>
  );
}
