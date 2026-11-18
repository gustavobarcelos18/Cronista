"use client";

import type { SeriesPanelOut } from "@cronista/contracts";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";
const SEGUNDOS = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

const SITUACAO: Record<SeriesPanelOut["situacao"], string> = {
  faltando: "ainda falta material",
  no_alvo: "dentro da meta",
  acima: "acima da meta (dá para cortar)",
};

export default function Painel({ revisao }: { revisao: number }) {
  const [panel, setPanel] = useState<SeriesPanelOut | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    fetch(`${API}/series`, { signal })
      .then((r) => {
        if (!r.ok) throw new Error(`Painel da série (${r.status})`);
        return r.json() as Promise<SeriesPanelOut>;
      })
      .then((next) => {
        if (!signal.aborted) setPanel(next);
      })
      .catch(() => {
        if (!signal.aborted) setPanel(null);
      });
    return () => controller.abort();
  }, [revisao]);

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
      {panel.capitulos_com_pouco_material.length > 0 && (
        <>
          <h4>Capítulos com pouco material</h4>
          <p>Referência de {panel.referencia_capitulo_s} s por capítulo.</p>
          <ul>
            {panel.capitulos_com_pouco_material.map((c) => (
              <li key={`${c.projeto_id}-${c.capitulo}`}>
                {c.projeto} · capítulo {c.capitulo} · {SEGUNDOS.format(c.produto_s)} s estimados
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
