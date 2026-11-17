"use client";

import type { Script, ScriptLine, ScriptOut } from "@cronista/contracts";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

export default function Roteiro({ sessionId }: { sessionId: number }) {
  const [script, setScript] = useState<Script | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    fetch(`${API}/sessions/${sessionId}/script`)
      .then(async (res) => {
        if (!res.ok) {
          setStatus("Roteiro ainda não importado (`cronista roteiro-import`).");
          return;
        }
        setScript(((await res.json()) as ScriptOut).script);
      })
      .catch(() => setStatus("Engine fora do ar."));
  }, [sessionId]);

  function edit(index: number, text: string) {
    setScript((cur) => {
      if (!cur) return cur;
      // est_s sai: o engine recalcula a duração falada a partir do texto novo.
      const lines = (cur.lines ?? []).map((l, i): ScriptLine => (i === index ? { ...l, text, est_s: null } : l));
      return { ...cur, lines };
    });
  }

  function remove(index: number) {
    setScript((cur) => (cur ? { ...cur, lines: (cur.lines ?? []).filter((_, i) => i !== index) } : cur));
  }

  async function save() {
    if (!script) return;
    setStatus("Salvando…");
    const res = await fetch(`${API}/sessions/${sessionId}/script`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(script),
    });
    if (!res.ok) {
      const body = (await res.json()) as { detail?: { errors?: string[]; message?: string } };
      setErrors(body.detail?.errors ?? [body.detail?.message ?? `erro ${res.status}`]);
      setStatus("Não salvo.");
      return;
    }
    const out = (await res.json()) as ScriptOut;
    setScript(out.script);
    setWarnings(out.warnings ?? []);
    setErrors([]);
    setStatus("Salvo (a versão anterior ficou no histórico).");
  }

  if (!script) return status ? <p>{status}</p> : null;
  return (
    <section>
      <h2>Roteiro ({script.lines?.length ?? 0} falas)</h2>
      {(script.lines ?? []).map((l, i) => (
        <div key={i} style={{ marginBottom: 8 }}>
          <small>
            {l.segment_id}
            {l.kind === "antecipacao" ? " · antecipação" : ""}
            {l.est_s ? ` · ~${l.est_s}s` : ""}
          </small>
          <textarea
            value={l.text}
            onChange={(e) => edit(i, e.target.value)}
            rows={2}
            style={{ width: "100%", display: "block" }}
          />
          <button onClick={() => remove(i)}>Remover</button>
        </div>
      ))}
      <button onClick={() => void save()}>Salvar roteiro</button> <small>{status}</small>
      {errors.map((e) => (
        <p key={e} role="alert">
          {e}
        </p>
      ))}
      <ul>
        {warnings.map((w) => (
          <li key={w}>
            <small>{w}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}
