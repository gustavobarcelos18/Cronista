"use client";

import { useState } from "react";
import { send as post } from "../lib/api";

/** Feedback em texto livre sobre um segmento (Q26). Fica guardado; a interpretação automática ainda não existe. */
export default function Feedback({ mediaId, segStart }: { mediaId: number; segStart: number }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");

  async function send() {
    try {
      await post(`/media/${mediaId}/feedback`, { text, seg_start_s: segStart });
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "erro ao enviar");
      return;
    }
    setText("");
    setOpen(false);
    setStatus("Anotado.");
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
        aria-label="Comentário sobre este trecho"
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
