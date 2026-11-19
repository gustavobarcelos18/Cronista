"use client";

import type { ProjectPanelOut, SeriesPanelOut } from "@cronista/contracts";
import { useEffect, useState } from "react";
import { API } from "../lib/api";

const SEGUNDOS = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

const SITUACAO: Record<ProjectPanelOut["situacao"], string> = {
  curto_ok: "curto, mas com arco completo: pronto para postar",
  abaixo_da_referencia: "abaixo de 30 min e o arco ainda está incompleto",
  no_alvo: "dentro da meta",
  acima: "acima da meta (dá para cortar)",
};

function Projeto({ projeto, panel }: { projeto: ProjectPanelOut; panel: SeriesPanelOut }) {
  const meta = panel.meta_min;
  const pct = Math.min(100, (projeto.total_min / meta) * 100);
  return (
    <section aria-label={`Painel da série ${projeto.projeto}`}>
      <h2>{projeto.projeto}</h2>
      <progress value={pct} max={100} style={{ width: "100%" }} />
      <p>
        <strong>{projeto.total_min} min</strong> de {meta} · {SITUACAO[projeto.situacao]}
      </p>
      <ul>
        {Object.entries(projeto.por_classe_min).map(([classe, min]) => (
          <li key={classe}>
            {classe}: {min} min
          </li>
        ))}
      </ul>
      <small>
        {projeto.sessoes.map((s) => `sessão ${s.sessao}: ${s.gravado_h} h → ${s.produto_min} min, ${s.dias} dias`).join(" · ")}
      </small>
      {projeto.capitulos_com_pouco_material.length > 0 && (
        <>
          <h3>Capítulos com pouco material</h3>
          <p>Referência de {panel.referencia_capitulo_s} s por capítulo.</p>
          <ul>
            {projeto.capitulos_com_pouco_material.map((c) => (
              <li key={c.capitulo}>
                capítulo {c.capitulo} · {SEGUNDOS.format(c.produto_s)} s estimados
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

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
  return (
    <>
      {panel.projetos.map((projeto) => (
        <Projeto key={projeto.projeto_id} projeto={projeto} panel={panel} />
      ))}
    </>
  );
}
