"use client";

import type { ProjectPanelOut, SeriesPanelOut } from "@cronista/contracts";
import { useEffect, useState } from "react";
import { getJson } from "../lib/api";

const SEGUNDOS = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

const SITUACAO: Record<ProjectPanelOut["situacao"], string> = {
  curto_ok: "abaixo da referência, com arco completo",
  abaixo_da_referencia: "abaixo da referência, com arco incompleto",
  no_alvo: "dentro da faixa de referência",
  acima: "acima da faixa de referência",
};

function Projeto({ projeto, panel }: { projeto: ProjectPanelOut; panel: SeriesPanelOut }) {
  const meta = panel.meta_min;
  const pct = Math.min(100, (projeto.total_min / meta) * 100);
  return (
    <section aria-label={`Painel da série ${projeto.projeto}`}>
      <h2>{projeto.projeto}</h2>
      <progress value={pct} max={100} style={{ width: "100%" }} />
      <p>
        <strong>{SEGUNDOS.format(projeto.total_min)} min estimados</strong> · {SITUACAO[projeto.situacao]}
        {" "}(referência de {panel.minimo_min} a {panel.maximo_min} min, alvo de {meta} min)
      </p>
      <ul>
        {Object.entries(projeto.por_classe_min).map(([classe, min]) => (
          <li key={classe}>
            {classe}: {min} min
          </li>
        ))}
      </ul>
      <small>
        {projeto.sessoes.map((s) => `sessão ${s.sessao}: ${SEGUNDOS.format(s.gravado_h)} h de gravação → ${SEGUNDOS.format(s.produto_min)} min estimados, marcações de “Novo dia”: ${s.dias}`).join(" · ")}
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
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    getJson<SeriesPanelOut>("/series", signal)
      .then((next) => {
        if (!signal.aborted) {
          setPanel(next);
          setError("");
        }
      })
      .catch((e: Error) => {
        if (!signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [revisao]);

  if (error) return <p role="alert">Painel da série indisponível. {error}</p>;
  if (!panel) return <p>Carregando painel da série…</p>;
  return (
    <>
      {panel.projetos.map((projeto) => (
        <Projeto key={projeto.projeto_id} projeto={projeto} panel={panel} />
      ))}
    </>
  );
}
