"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

/** Feedback em texto livre sobre um segmento (Q26). Fica guardado; a interpretação automática ainda não existe. */
export default function Feedback({ mediaId, segStart }: { mediaId: number; segStart: number }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");

  async function send() {
    const res = await fetch(`${API}/media/${mediaId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, seg_start_s: segStart }),
    });
    if (res.ok) {
      setText("");
      setOpen(false);
      setStatus("Anotado.");
    } else {
      setStatus(`erro ${res.status}`);
    }
  }

  if (!open) {
    return (
      <>
        <button onClick={() => setOpen(true)}>Comentar</button> <small>{status}</small>
      </>
    );
  }
  return (
    <div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        placeholder="O que está errado ou certo neste trecho?"
        style={{ width: "100%" }}
      />
      <button disabled={!text.trim()} onClick={() => void send()}>
        Enviar
      </button>
      <button onClick={() => setOpen(false)}>Cancelar</button>
    </div>
  );
}
