"use client";

import type { LearningOut } from "@cronista/contracts";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

/** Proposta de pesos por manter/tirar trecho (7E). Só vale depois de aceita. */
export default function Aprendizado({ projectId }: { projectId: number }) {
  const [info, setInfo] = useState<LearningOut | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch(`${API}/projects/${projectId}/learning`)
      .then((r) => r.json() as Promise<LearningOut>)
      .then(setInfo)
      .catch(() => setMessage("Engine fora do ar."));
  }, [projectId]);

  async function accept() {
    const res = await fetch(`${API}/projects/${projectId}/learning/accept`, { method: "POST" });
    if (res.ok) {
      setInfo((await res.json()) as LearningOut);
      setMessage("Aceito: vale na próxima vez que a relevância rodar (`cronista relevance`).");
    } else {
      setMessage("Ainda faltam decisões.");
    }
  }

  if (!info) return message ? <p>{message}</p> : null;
  return (
    <section aria-label="Aprendizado">
      <h3>Aprendizado</h3>
      {info.weights ? (
        <>
          <p>Com {info.n_decisions} decisões suas, sugiro:</p>
          <ul>
            {(info.explanation ?? []).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <button onClick={() => void accept()}>Aceitar pesos</button>
        </>
      ) : (
        <p>
          Aceite ou rejeite pelo menos {info.needed} trechos (5 de cada lado) para eu sugerir pesos.
        </p>
      )}
      <small>{message}</small>
    </section>
  );
}
