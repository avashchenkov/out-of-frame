import { randomUUID } from "node:crypto";
import { COOKIE_NAME, UUID, readIdentity, verifyIdentity } from "./identity.ts";
import { disabledRoute, privateJson, unavailable } from "./read-proxy.ts";
import type { ProxyConfig } from "./read-proxy.ts";
import { visibleResponse } from "./visible-response.ts";

type Input = Record<string, unknown>;
type Action = "chat" | "answer" | "retry" | "delete";
const ERRORS = new Set([
  "invalid_identity",
  "identity_expired",
  "chat_not_found",
  "chat_exists",
  "chat_complete",
  "run_active",
  "no_question",
  "no_retry",
  "deletion_pending",
  "identity_chats_exhausted",
  "daily_chats_exhausted",
  "submissions_exhausted",
  "message_required",
  "message_too_long",
  "invalid_request",
]);

function route(
  method: string,
  path: string[],
): { action: Action; upstream: string } | null {
  if (path.length === 1 && path[0] === "chat") {
    if (method === "POST") return { action: "chat", upstream: "/demo/chat" };
    if (method === "DELETE")
      return { action: "delete", upstream: "/demo/chat" };
  }
  if (method !== "POST") return null;
  if (path.length === 1 && path[0] === "retry")
    return { action: "retry", upstream: "/demo/retry" };
  if (
    path.length === 3 &&
    path[0] === "threads" &&
    UUID.test(path[1]) &&
    path[2] === "runs"
  )
    return { action: "answer", upstream: `/${path.join("/")}` };
  return null;
}

async function input(request: Request): Promise<Input> {
  const reader = request.body?.getReader();
  const decoder = new TextDecoder();
  let text = "";
  let size = 0;
  try {
    while (reader) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > 16_384) {
        await reader.cancel();
        throw new RangeError("request_too_large");
      }
      text += decoder.decode(chunk.value, { stream: true });
    }
  } finally {
    reader?.releaseLock();
  }
  text += decoder.decode();
  const value: unknown = text ? JSON.parse(text) : {};
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("invalid_request");
  return value as Input;
}

function allowedInput(action: Action, body: Input) {
  const fields =
    action === "chat"
      ? ["text", "replace"]
      : action === "answer"
        ? ["text"]
        : [];
  if (Object.keys(body).some((key) => !fields.includes(key))) return false;
  if (action === "chat" || action === "answer") {
    if (typeof body.text !== "string" || !body.text.trim()) return false;
  }
  return (
    action !== "chat" ||
    body.replace === undefined ||
    typeof body.replace === "boolean"
  );
}

function backendBody(action: Action, body: Input) {
  if (action === "chat")
    return { text: body.text, replace: body.replace ?? false };
  if (action === "answer")
    return {
      assistant_id: "agent",
      multitask_strategy: "reject",
      on_disconnect: "continue",
      durability: "sync",
      stream_mode: ["values", "updates"],
      stream_subgraphs: false,
      command: { resume: body.text },
    };
  return undefined;
}

export async function mutationProxy(
  request: Request,
  path: string[],
  config: ProxyConfig,
  fetchBackend: typeof fetch = fetch,
) {
  if (request.method !== "POST" && request.method !== "DELETE")
    return disabledRoute();
  const target = route(request.method, path);
  if (!target || new URL(request.url).search)
    return privateJson({ error: "route_disabled" }, 403);
  if (
    request.headers.get("origin") !== config.origin ||
    request.headers.get("sec-fetch-site") === "cross-site"
  )
    return privateJson({ error: "origin_rejected" }, 403);
  if (request.headers.get("x-demo-csrf") !== "1")
    return privateJson({ error: "csrf_required" }, 403);
  if (
    request.method === "POST" &&
    request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !==
      "application/json"
  )
    return privateJson({ error: "json_required" }, 415);
  if (target.action !== "delete" && !config.liveEnabled)
    return privateJson({ error: "live_unavailable" }, 503);

  const cookie = request.headers.get("cookie");
  const owner = readIdentity(cookie, config.secret);
  const hasCookie = (cookie ?? "")
    .split(";")
    .some((part) => part.trim().startsWith(`${COOKIE_NAME}=`));
  if (!owner && (hasCookie || target.action !== "chat"))
    return privateJson({ error: "invalid_identity" }, 401);
  let body: Input;
  try {
    body = await input(request);
  } catch (error) {
    return privateJson(
      {
        error:
          error instanceof RangeError ? "request_too_large" : "invalid_request",
      },
      error instanceof RangeError ? 413 : 422,
    );
  }
  if (!allowedInput(target.action, body))
    return privateJson({ error: "invalid_request" }, 422);
  if (owner && Date.now() >= owner.expires * 1000)
    return privateJson({ error: "invalid_identity" }, 401);

  const identity = owner?.identity ?? randomUUID();
  try {
    const payload = backendBody(target.action, body);
    const headers = new Headers({
      "x-demo-key": config.secret,
      "x-demo-identity": identity,
      "x-demo-csrf": "1",
    });
    if (payload !== undefined) headers.set("content-type", "application/json");
    const response = await fetchBackend(
      new URL(target.upstream, config.backend),
      {
        method: request.method,
        headers,
        body: payload === undefined ? undefined : JSON.stringify(payload),
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]),
      },
    );
    const data: Input = await response.json();
    if (!response.ok) {
      const code = typeof data?.error === "string" ? data.error : data?.detail;
      if (
        response.status >= 400 &&
        response.status < 500 &&
        typeof code === "string" &&
        ERRORS.has(code)
      )
        return privateJson({ error: code }, response.status);
      if (response.status === 404)
        return privateJson({ error: "chat_not_found" }, 404);
      return unavailable();
    }
    if (owner && Date.now() >= owner.expires * 1000)
      return privateJson({ error: "invalid_identity" }, 401);
    if (target.action === "delete")
      return data.deleted === true
        ? privateJson({ deleted: true })
        : unavailable();
    const visible = visibleResponse("run", data);
    if (
      typeof visible.thread_id !== "string" ||
      typeof visible.run_id !== "string"
    )
      return unavailable();
    if (target.action !== "chat") return privateJson(visible);

    const issued = verifyIdentity(data.cookie, config.secret);
    if (
      !issued ||
      issued.identity !== identity ||
      (owner && issued.expires !== owner.expires)
    )
      return unavailable();
    const result = privateJson({
      ...visible,
      expires_at: new Date(issued.expires * 1000).toISOString(),
    });
    if (!owner)
      result.headers.set(
        "Set-Cookie",
        `${COOKIE_NAME}=${data.cookie}; Path=/; Expires=${new Date(issued.expires * 1000).toUTCString()}; HttpOnly; Secure; SameSite=Lax`,
      );
    return result;
  } catch {
    return unavailable();
  }
}
