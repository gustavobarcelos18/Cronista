"use client";

import type { LearningOut } from "@cronista/contracts";
import { useEffect, useState } from "react";
import { ApiError, getJson, send } from "../lib/api";

/** Proposta de pesos por manter/tirar trecho (7E). Só vale depois de aceita. */
export default function Aprendizado({ projectId, revisao }: { projectId: number; revisao: number }) {
  const [info, setInfo] = useState<LearningOut | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getJson<LearningOut>(`/projects/${projectId}/learning`, controller.signal)
      .then((next) => !controller.signal.aborted && setInfo(next))
      .catch((e: Error) => !controller.signal.aborted && setMessage(e.message));
    return () => controller.abort();
  }, [projectId, revisao]);

  async function accept() {
    try {
      setInfo(await send<LearningOut>(`/projects/${projectId}/learning/accept`));
      setMessage("Aceito: vale na próxima vez que a relevância rodar (`cronista relevance`).");
    } catch (e) {
      // Só o 409 quer dizer "faltam decisões"; o resto (rede, 404, 500) mostra o motivo real.
      const missing = e instanceof ApiError && e.status === 409;
      setMessage(missing ? "Ainda faltam decisões." : e instanceof Error ? e.message : "erro ao aceitar");
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
          Revise pelo menos {info.needed} segmentos, com pelo menos 5 aceitos ou ajustados e 5 rejeitados.
        </p>
      )}
      <small>{message}</small>
    </section>
  );
}
