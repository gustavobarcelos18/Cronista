import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, errorOf, getJson, send } from "../lib/api";

function resposta(status: number, corpo: unknown): Response {
  return new Response(typeof corpo === "string" ? corpo : JSON.stringify(corpo), { status });
}

afterEach(() => vi.unstubAllGlobals());

describe("lib/api", () => {
  it("erro de rede vira ApiError com status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("falhou")));
    const erro = await getJson("/x").catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(ApiError);
    expect((erro as ApiError).status).toBe(0);
    expect((erro as ApiError).message).toMatch(/Engine fora do ar/);
  });

  it("resposta não-2xx usa o detail do FastAPI e guarda o corpo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta(404, { detail: "sessão não existe" })));
    const erro = (await getJson("/x").catch((e: unknown) => e)) as ApiError;
    expect(erro.status).toBe(404);
    expect(erro.message).toBe("sessão não existe");
    expect(erro.body).toEqual({ detail: "sessão não existe" });
  });

  it("sem detail em texto, a mensagem cai para o caminho e o status", async () => {
    expect(await errorOf(resposta(500, "<html>"), "falha")).toBe("falha (500).");
    expect(await errorOf(resposta(422, { detail: [{ msg: "x" }] }), "falha")).toBe("falha (422).");
  });

  it("GET ok devolve o JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta(200, [1, 2])));
    expect(await getJson<number[]>("/x")).toEqual([1, 2]);
  });

  it("send envia JSON com o método pedido e sem corpo quando não há dados", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(resposta(200, { ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    await send("/a", { n: 1 }, "PUT");
    await send("/b");
    const [, comCorpo] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [, semCorpo] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(comCorpo.method).toBe("PUT");
    expect(comCorpo.body).toBe('{"n":1}');
    expect(semCorpo.body).toBeUndefined();
    expect(semCorpo.headers).toBeUndefined();
  });

  it("send levanta ApiError em HTTP não-2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta(409, { detail: "conflito" })));
    await expect(send("/x", {})).rejects.toMatchObject({ status: 409, message: "conflito" });
  });
});
