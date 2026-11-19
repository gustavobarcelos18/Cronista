import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Revisao from "../app/revisao";

afterEach(() => vi.unstubAllGlobals());

describe("Revisao", () => {
  it("engine desligado mostra a mensagem de erro, sem ficar em estado intermediário", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<Revisao />);
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Engine fora do ar");
    expect(screen.getByText("Escolha um arquivo à esquerda.")).toBeInTheDocument();
  });

  it("engine no ar sem sessões não mostra erro e pede um arquivo", async () => {
    // Só /sessions responde; o resto (painel da série) falha e o painel some, como com um engine parcial.
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/sessions")
          ? Promise.resolve(new Response("[]", { status: 200 }))
          : Promise.reject(new TypeError("sem rota")),
      ),
    );
    render(<Revisao />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Escolha um arquivo à esquerda.")).toBeInTheDocument();
  });
});
