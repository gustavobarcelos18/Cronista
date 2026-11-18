/** Acesso ao engine: um só lugar para a URL, o erro de rede e o `detail` que o FastAPI devolve. */

export const API = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000";

/** Falha de uma chamada: rede fora do ar (`status` 0) ou resposta não-2xx (`status` do HTTP). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown = null,
  ) {
    super(message);
  }
}

/** Texto de erro de uma resposta: o `detail` em texto, ou `<fallback> (<status>).` */
export async function errorOf(res: Response, fallback: string): Promise<string> {
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  return typeof body.detail === "string" ? body.detail : `${fallback} (${res.status}).`;
}

async function call(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API}${path}`, init);
  } catch {
    throw new ApiError("Engine fora do ar. Rode `cronista api`.", 0);
  }
}

async function fail(res: Response, path: string): Promise<never> {
  const body: unknown = await res
    .clone()
    .json()
    .catch(() => null);
  throw new ApiError(await errorOf(res, path), res.status, body);
}

/** GET que devolve o JSON ou levanta `ApiError` (rede ou HTTP não-2xx). */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await call(path, { signal });
  if (!res.ok) await fail(res, path);
  return (await res.json()) as T;
}

/** Envia JSON (POST por padrão). Levanta `ApiError` em rede fora do ar ou HTTP não-2xx; o `body` do erro guarda o JSON. */
export async function send<T>(
  path: string,
  body?: unknown,
  method: "POST" | "PUT" = "POST",
): Promise<T> {
  const res = await call(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) await fail(res, path);
  return (await res.json()) as T;
}
