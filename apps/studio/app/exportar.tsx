"use client";

import type { ExportStatusOut } from "@cronista/contracts";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

export default function Exportar({ sessionId }: { sessionId: number }) {
  const [status, setStatus] = useState<ExportStatusOut | null>(null);
  const running = status?.state === "running";

  useEffect(() => {
    let alive = true;
    const poll = () =>
      fetch(`${API}/sessions/${sessionId}/export`)
        .then((r) => r.json() as Promise<ExportStatusOut>)
        .then((s) => alive && setStatus(s))
        .catch(() => undefined);
    void poll();
    if (!running) return () => void (alive = false);
    const timer = setInterval(() => void poll(), 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [sessionId, running]);

  async function start() {
    const res = await fetch(`${API}/sessions/${sessionId}/export`, { method: "POST" });
    if (res.ok || res.status === 409) setStatus((await res.json()) as ExportStatusOut);
    else setStatus({ state: "error", message: `erro ${res.status}` });
  }

  return (
    <section>
      <h2>Exportar para o Resolve</h2>
      <button disabled={running} onClick={() => void start()}>
        {running ? "Exportando…" : "Re-exportar montagem"}
      </button>{" "}
      <small>Usa as decisões e o roteiro atuais; o que não mudou é reaproveitado.</small>
      {status && status.state !== "idle" && status.state !== "running" && (
        <p role={status.state === "error" ? "alert" : undefined}>
          {status.message}
          {status.version != null && ` · versão ${status.version}`}
          {status.directory && ` · ${status.directory}`}
        </p>
      )}
      <ul>
        {[...(status?.problems ?? []), ...(status?.warnings ?? [])].map((w) => (
          <li key={w}>
            <small>{w}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}
