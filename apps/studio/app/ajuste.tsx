"use client";

import { useState } from "react";

function toSeconds(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw.replace(",", "."));
  return Number.isFinite(value) ? value : null;
}

/** Formulário inline do "Ajustar": início e fim em segundos do arquivo. Vazio ou texto não vira 0. */
export default function AjusteForm({
  start,
  end,
  onSubmit,
  onCancel,
}: {
  start: number;
  end: number;
  onSubmit: (start: number, end: number) => void;
  onCancel: () => void;
}) {
  const [from, setFrom] = useState(String(start));
  const [to, setTo] = useState(String(end));
  const [problem, setProblem] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const s = toSeconds(from);
    const t = toSeconds(to);
    if (s === null || t === null) {
      setProblem("Informe números em segundos.");
    } else if (t <= s) {
      setProblem("O fim precisa ser depois do início.");
    } else {
      onSubmit(s, t);
    }
  }

  return (
    <form onSubmit={submit}>
      <label>
        Novo início (s do arquivo){" "}
        <input value={from} onChange={(e) => setFrom(e.target.value)} inputMode="decimal" size={8} />
      </label>{" "}
      <label>
        Novo fim (s do arquivo){" "}
        <input value={to} onChange={(e) => setTo(e.target.value)} inputMode="decimal" size={8} />
      </label>{" "}
      <button type="submit">Salvar ajuste</button>
      <button type="button" onClick={onCancel}>
        Cancelar
      </button>
      {problem && <p role="alert">{problem}</p>}
    </form>
  );
}
