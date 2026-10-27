import { readIdentity, UUID } from "./identity.ts";
import { visibleResponse } from "./visible-response.ts";
import type { ReadKind } from "./visible-response.ts";
import { eventStream, validEventId } from "./event-stream.ts";
import type { TrafficLimits } from "./traffic-limits.ts";

export type ProxyConfig = {
  origin: string;
  backend: URL;
  secret: string;
  liveEnabled?: boolean;
};

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
  return {
    origin: origin.origin,
    backend,
    secret,
    liveEnabled: env.OUT_OF_FRAME_DEMO_LIVE_ENABLED === "true",
  };
}

function route(
  path: string[],
): { kind: ReadKind | "stream"; upstream: string } | null {
  if (path.length === 1 && (path[0] === "limits" || path[0] === "session")) {
    return { kind: path[0], upstream: `/demo/${path[0]}` };
  }
  if (path[0] !== "threads" || !UUID.test(path[1] ?? "")) return null;
  let kind: ReadKind | "stream";
  if (path.length === 2) kind = "thread";
  else if (path.length === 3 && path[2] === "state") kind = "state";
  else if (path.length === 4 && path[2] === "runs" && UUID.test(path[3]))
    kind = "run";
  else if (
    path.length === 5 &&
    path[2] === "runs" &&
    UUID.test(path[3]) &&
    path[4] === "stream"
  )
    kind = "stream";
  else return null;
  return { kind, upstream: `/${path.join("/")}` };
}

const PRIVATE_HEADERS = {
  "Cache-Control": "private, no-store",
  "X-Content-Type-Options": "nosniff",
  Vary: "Cookie, Origin, Sec-Fetch-Site",
};

export function privateJson(data: unknown, status = 200) {
  return Response.json(data, {
    status,
    headers: PRIVATE_HEADERS,
  });
}

const json = privateJson;

export function disabledRoute() {
  return json({ error: "route_disabled" }, 405);
}

export function busyResponse() {
  const response = json({ error: "demo_busy" }, 429);
  response.headers.set("Retry-After", "5");
  return response;
}

export async function readProxy(
  request: Request,
  path: string[],
  config: ProxyConfig,
  fetchBackend: typeof fetch = fetch,
  traffic?: TrafficLimits,
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
  const lastEventId = request.headers.get("last-event-id");
  if (
    target.kind === "stream" &&
    lastEventId !== null &&
    !validEventId(lastEventId, path[3])
  )
    return json({ error: "invalid_event_id" }, 422);
  const release =
    target.kind === "stream"
      ? traffic?.openStream(identity!.identity)
      : undefined;
  if (release === null) return busyResponse();
  const connection = new AbortController();
  const signal = AbortSignal.any([request.signal, connection.signal]);
  const headerTimer = setTimeout(() => disconnect(), 10_000);
  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  let disconnected = false;
  const disconnect = () => {
    if (disconnected) return;
    disconnected = true;
    clearTimeout(headerTimer);
    clearTimeout(expiryTimer);
    signal.removeEventListener("abort", disconnect);
    connection.abort();
    release?.();
  };
  signal.addEventListener("abort", disconnect, { once: true });
  let streaming = false;
  try {
    signal.throwIfAborted();
    const headers = new Headers({ "x-demo-key": config.secret });
    if (identity && target.kind !== "limits")
      headers.set("x-demo-identity", identity.identity);
    if (target.kind === "stream") {
      headers.set("accept", "text/event-stream");
      if (lastEventId !== null) headers.set("last-event-id", lastEventId);
    }
    const response = await fetchBackend(
      new URL(target.upstream, config.backend),
      {
        method: "GET",
        headers,
        cache: "no-store",
        redirect: "error",
        signal,
      },
    );
    if (!response.ok) {
      await response.body?.cancel();
      return response.status === 404
        ? json({ error: "chat_not_found" }, 404)
        : json({ error: "service_unavailable" }, 502);
    }
    if (target.kind === "stream") {
      clearTimeout(headerTimer);
      if (
        !response.body ||
        response.headers
          .get("content-type")
          ?.split(";")[0]
          .trim()
          .toLowerCase() !== "text/event-stream"
      ) {
        await response.body?.cancel();
        return unavailable();
      }
      const lifetime = (identity?.expires ?? 0) * 1000 - Date.now();
      if (lifetime <= 0) {
        await response.body.cancel();
        return json({ error: "invalid_identity" }, 401);
      }
      expiryTimer = setTimeout(
        disconnect,
        Math.min(Math.max(0, lifetime), 2_147_483_647),
      );
      expiryTimer.unref();
      const result = new Response(
        eventStream(
          response.body,
          path[3],
          identity?.expires ?? 0,
          signal,
          disconnect,
        ),
        {
          headers: {
            ...PRIVATE_HEADERS,
            "Content-Type": "text/event-stream; charset=utf-8",
            "X-Accel-Buffering": "no",
          },
        },
      );
      streaming = true;
      return result;
    }
    const data: unknown = await response.json();
    if (
      target.kind !== "limits" &&
      identity &&
      Date.now() >= identity.expires * 1000
    )
      return json({ error: "invalid_identity" }, 401);
    return json(visibleResponse(target.kind, data));
  } catch {
    return unavailable();
  } finally {
    if (!streaming) disconnect();
  }
}

export function unavailable() {
  return json({ error: "service_unavailable" }, 503);
}
