"use client";

import type { Script, ScriptLine, ScriptOut } from "@cronista/contracts";
import { useEffect, useState } from "react";
import { ApiError, getJson, send } from "../lib/api";

export default function Roteiro({ sessionId }: { sessionId: number }) {
  const [script, setScript] = useState<Script | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    getJson<ScriptOut>(`/sessions/${sessionId}/script`)
      .then((out) => setScript(out.script))
      .catch((e: Error) =>
        setStatus(
          e instanceof ApiError && e.status === 404
            ? "Roteiro ainda não importado (`cronista roteiro-import`)."
            : e.message,
        ),
      );
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
    let out: ScriptOut;
    try {
      out = await send<ScriptOut>(`/sessions/${sessionId}/script`, script, "PUT");
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as { detail?: { errors?: string[]; message?: string } } | null) : null;
      const detail = body?.detail;
      const fromBody = detail && typeof detail === "object" ? (detail.errors ?? (detail.message ? [detail.message] : null)) : null;
      setErrors(fromBody ?? [e instanceof Error ? e.message : "erro ao salvar"]);
      setStatus("Não salvo.");
      return;
    }
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
