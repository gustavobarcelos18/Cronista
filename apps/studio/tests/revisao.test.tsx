import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Revisao from "../app/revisao";

afterEach(() => vi.unstubAllGlobals());

describe("Revisao", () => {
  it("uma resposta atrasada nunca troca os segmentos do arquivo selecionado", async () => {
    const older = Promise.withResolvers<Response>();
    const sessions = [{ id: 1, project_id: 1, project: "Série", files: [
      { id: 1, name: "A.mp4" }, { id: 2, name: "B.mp4" },
    ] }];
    function segment(classe: string) {
      return Response.json([{ start_s: 0, end_s: 20, score: 0.8, classe, razoes: [], markers: [], features: {} }]);
    }
    vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/sessions")) return Response.json(sessions);
      if (url.endsWith("/series")) return Response.json({ projetos: [] });
      if (url.endsWith("/1/segments")) return older.promise;
      if (url.endsWith("/2/segments")) return segment("conversa");
      if (url.endsWith("/events")) return Response.json([]);
      return Response.json({ detail: "indisponível" }, { status: 404 });
    }));
    render(<Revisao />);
    fireEvent.click(await screen.findByRole("button", { name: "A.mp4" }));
    fireEvent.click(screen.getByRole("button", { name: "B.mp4" }));
    expect(await screen.findByText("conversa")).toBeInTheDocument();
    await act(async () => older.resolve(segment("farm")));
    expect(screen.queryByText("farm")).not.toBeInTheDocument();
    expect(screen.getByText("conversa")).toBeInTheDocument();
  });

  it("engine desligado mostra a mensagem de erro, sem ficar em estado intermediário", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<Revisao />);
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Engine fora do ar");
    expect(screen.queryByText("Escolha um arquivo à esquerda.")).not.toBeInTheDocument();
  });

  it("explica quando ainda não há arquivos para escolher", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/sessions")
          ? Promise.resolve(new Response("[]", { status: 200 }))
          : Promise.reject(new TypeError("sem rota")),
      ),
    );
    render(<Revisao />);
    await waitFor(() => expect(screen.getByText(/Nenhum arquivo de gravação/)).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
