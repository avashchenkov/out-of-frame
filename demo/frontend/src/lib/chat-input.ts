export type DemoLimits = {
  identity_chats: number;
  lifetime_days: number;
  submissions: number;
  message_chars: number;
  daily_reset: string;
};

export const IDENTITY_LIMIT_NOTICE =
  "You have reached your usage limit. Contact the author for further access.";
const REFUSALS: Record<string, string> = {
  demo_busy: "The demo is busy. Please wait a moment and try again.",
  identity_chats_exhausted: IDENTITY_LIMIT_NOTICE,
  daily_chats_exhausted:
    "This is a demo service, so new chats are limited per day across all visitors. Today's limit has been reached. Please try again tomorrow or contact the author.",
  submissions_exhausted: "This chat has reached its message limit.",
  live_unavailable: "Live chat is currently unavailable.",
  chat_exists: "A chat already exists in this browser. Reload chat to open it.",
  chat_complete: "This report is complete. This chat cannot be continued.",
  run_active: "The agent is already working. Wait for its reply.",
  no_question:
    "There is no question to answer. Reload chat to check its status.",
  no_retry: "This chat cannot be retried. Reload chat to check its status.",
  deletion_pending: "Chat deletion is in progress. Please try again later.",
  invalid_identity: "This chat is no longer available in this browser.",
  identity_expired: "This chat is no longer available in this browser.",
  chat_not_found: "This chat is no longer available in this browser.",
  message_too_long: "Your message exceeds the character limit.",
  message_required: "Enter a message before sending.",
};

export class ChatSubmitError extends Error {
  readonly uncertain: boolean;
  readonly code?: string;
  constructor(code?: string, uncertain = false) {
    super(
      code && Object.hasOwn(REFUSALS, code)
        ? REFUSALS[code]
        : "The request status is unknown. Reload chat before sending again.",
    );
    this.uncertain = uncertain || !code || !Object.hasOwn(REFUSALS, code);
    this.code = code && Object.hasOwn(REFUSALS, code) ? code : undefined;
  }
}

export async function readDemoLimits(
  signal: AbortSignal,
  fetchPage: typeof fetch = fetch,
): Promise<DemoLimits> {
  const response = await fetchPage("/api/demo/limits", {
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
  });
  if (!response.ok) throw new Error("limits_unavailable");
  const data = await response.json();
  for (const key of [
    "identity_chats",
    "lifetime_days",
    "submissions",
    "message_chars",
  ]) {
    if (!Number.isSafeInteger(data[key]) || data[key] <= 0)
      throw new Error("invalid_limits");
  }
  if (
    typeof data.daily_reset !== "string" ||
    !Number.isFinite(Date.parse(data.daily_reset))
  )
    throw new Error("invalid_limits");
  return data;
}

export async function submitChat(
  action: "new" | "replace" | "answer" | "retry",
  text: string,
  threadId: string | null,
  signal: AbortSignal,
  fetchPage: typeof fetch = fetch,
) {
  const path =
    action === "new" || action === "replace"
      ? "chat"
      : action === "retry"
        ? "retry"
        : `threads/${encodeURIComponent(threadId ?? "")}/runs`;
  return chatRequest(
    path,
    action === "retry"
      ? {}
      : action === "replace"
        ? { text, replace: true }
        : { text },
    signal,
    fetchPage,
  );
}

export async function deleteChat(
  signal: AbortSignal,
  fetchPage: typeof fetch = fetch,
) {
  const response = await chatRequest("chat", undefined, signal, fetchPage);
  try {
    if ((await response.json()).deleted !== true)
      throw new Error("not_deleted");
  } catch {
    throw new ChatSubmitError(undefined, true);
  }
}

async function chatRequest(
  path: string,
  body: Record<string, unknown> | undefined,
  signal: AbortSignal,
  fetchPage: typeof fetch,
) {
  try {
    const response = await fetchPage(`/api/demo/${path}`, {
      method: body === undefined ? "DELETE" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers:
        body === undefined
          ? { "X-Demo-CSRF": "1" }
          : { "Content-Type": "application/json", "X-Demo-CSRF": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.any([signal, AbortSignal.timeout(35_000)]),
    });
    if (response.ok) return response;
    const data = await response.json();
    throw new ChatSubmitError(
      typeof data.error === "string" ? data.error : undefined,
      response.status >= 500,
    );
  } catch (error) {
    if (error instanceof ChatSubmitError) throw error;
    throw new ChatSubmitError(undefined, true);
  }
}
