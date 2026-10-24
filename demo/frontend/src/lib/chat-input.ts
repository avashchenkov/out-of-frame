export type DemoLimits = {
  identity_chats: number;
  lifetime_days: number;
  submissions: number;
  message_chars: number;
  daily_reset: string;
};

const REFUSALS: Record<string, string> = {
  identity_chats_exhausted:
    "You have reached your usage limit. Contact the author for further access.",
  daily_chats_exhausted:
    "Today's limit for new chats has been reached. Please try again tomorrow.",
  submissions_exhausted: "The submission limit for this chat has been reached.",
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
  action: "new" | "answer" | "retry",
  text: string,
  threadId: string | null,
  signal: AbortSignal,
  fetchPage: typeof fetch = fetch,
) {
  const path =
    action === "new"
      ? "chat"
      : action === "retry"
        ? "retry"
        : `threads/${encodeURIComponent(threadId ?? "")}/runs`;
  let response: Response;
  try {
    response = await fetchPage(`/api/demo/${path}`, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Demo-CSRF": "1" },
      body: JSON.stringify(action === "retry" ? {} : { text }),
      signal: AbortSignal.any([signal, AbortSignal.timeout(35_000)]),
    });
    if (response.ok) return;
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
