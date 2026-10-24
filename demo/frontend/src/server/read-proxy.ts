import { readIdentity, UUID } from "./identity.ts";
import { visibleResponse } from "./visible-response.ts";
import type { ReadKind } from "./visible-response.ts";

type ProxyConfig = { origin: string; backend: URL; secret: string };

export function proxyConfig(env: NodeJS.ProcessEnv): ProxyConfig {
  const origin = new URL(env.OUT_OF_FRAME_DEMO_ORIGIN ?? "");
  const backend = new URL(env.OUT_OF_FRAME_DEMO_BACKEND_URL ?? "");
  const secret = env.OUT_OF_FRAME_DEMO_PROXY_SECRET ?? "";
  for (const url of [origin, backend]) {
    if (
      !new Set(["https:", "http:"]).has(url.protocol) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    )
      throw new Error("Invalid proxy URL");
  }
  if (secret.length < 32) throw new Error("Invalid proxy secret");
  return { origin: origin.origin, backend, secret };
}

function route(path: string[]): { kind: ReadKind; upstream: string } | null {
  if (path.length === 1 && (path[0] === "limits" || path[0] === "session")) {
    return { kind: path[0], upstream: `/demo/${path[0]}` };
  }
  if (path[0] !== "threads" || !UUID.test(path[1] ?? "")) return null;
  let kind: ReadKind;
  if (path.length === 2) kind = "thread";
  else if (path.length === 3 && path[2] === "state") kind = "state";
  else if (path.length === 4 && path[2] === "runs" && UUID.test(path[3]))
    kind = "run";
  else return null;
  return { kind, upstream: `/${path.join("/")}` };
}

function json(data: unknown, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      Vary: "Cookie, Origin, Sec-Fetch-Site",
    },
  });
}

export function disabledRoute() {
  return json({ error: "route_disabled" }, 405);
}

export async function readProxy(
  request: Request,
  path: string[],
  config: ProxyConfig,
  fetchBackend: typeof fetch = fetch,
) {
  if (request.method !== "GET") return disabledRoute();
  const target = route(path);
  if (!target || new URL(request.url).search)
    return json({ error: "route_disabled" }, 403);
  const origin = request.headers.get("origin");
  if (
    (origin !== null && origin !== config.origin) ||
    request.headers.get("sec-fetch-site") === "cross-site"
  ) {
    return json({ error: "origin_rejected" }, 403);
  }
  const identity = readIdentity(request.headers.get("cookie"), config.secret);
  if (target.kind !== "limits" && !identity) {
    if (
      target.kind === "session" &&
      !request.headers.get("cookie")?.includes("oof_identity=")
    )
      return json({ thread_id: null });
    return json({ error: "invalid_identity" }, 401);
  }
  try {
    const headers = new Headers({ "x-demo-key": config.secret });
    if (identity && target.kind !== "limits")
      headers.set("x-demo-identity", identity);
    const response = await fetchBackend(
      new URL(target.upstream, config.backend),
      {
        method: "GET",
        headers,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(10_000)]),
      },
    );
    if (!response.ok) {
      await response.body?.cancel();
      return response.status === 404
        ? json({ error: "chat_not_found" }, 404)
        : json({ error: "service_unavailable" }, 502);
    }
    return json(visibleResponse(target.kind, await response.json()));
  } catch {
    return unavailable();
  }
}

export function unavailable() {
  return json({ error: "service_unavailable" }, 503);
}
