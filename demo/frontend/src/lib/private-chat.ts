export type ChatMessage = {
  id: string;
  type: "human" | "ai";
  content: string;
};

export type PrivateChat = {
  threadId: string | null;
  runId?: string;
  messages: ChatMessage[];
  failures: string[];
  status: string;
  active: boolean;
  canAnswer?: boolean;
  canRetry?: boolean;
  expiresAt?: string;
  submissionsRemaining?: number;
  chatsRemaining?: number;
  deleting?: boolean;
  // The web research in progress, by the saved state.
  research?: { done: number; total: number };
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FAILURE_NOTICES: Record<string, string> = {
  map: "The map could not be loaded, so the report may be incomplete.",
  plans:
    "Development plans could not be loaded, so the report may be incomplete.",
  transit: "The journey planner failed, so some journeys are unavailable.",
  "web search": "Web search failed, so an object may stay unidentified.",
};

type Session = {
  thread_id: string | null;
  run_id?: string;
  status?: string;
  complete?: boolean;
  deleting?: boolean;
  expires_at?: string;
  submissions_remaining?: number;
  chats_remaining?: number;
};

export function researchStatus({
  done,
  total,
}: {
  done: number;
  total: number;
}) {
  return `Researching objects on the web: ${done} of ${total}…`;
}

// The research runs one task per object, and each finished task leaves the
// list, though the saved state shows it late.
function findResearch(state: { next?: string[]; research_total?: number }) {
  const next = state.next ?? [];
  const total = state.research_total ?? 0;
  if (!next.includes("investigate_object") || total <= 0) return undefined;
  const left = next.filter((node) => node === "investigate_object").length;
  return { done: total - left, total };
}

// The step that a working run is on, as the state's next steps show it.
function workingStatus(state: { next?: string[]; research_total?: number }) {
  const next = state.next ?? [];
  const research = findResearch(state);
  if (research) return researchStatus(research);
  if (next.includes("write_report") || next.includes("fill_references"))
    return "Writing the report…";
  if (next.includes("get_addresses"))
    return "Looking up the addresses of the places…";
  if (next.includes("triage_objects")) return "Checking the places nearby…";
  if (
    ["get_map_objects", "get_plans", "plan_journeys"].some((node) =>
      next.includes(node),
    )
  )
    return "Loading the map, development plans and journeys…";
  if (next.includes("geocode_input")) return "Finding the address on the map…";
  if (next.includes("extract_input") || next.includes("detect_language"))
    return "Reading your message…";
  return "Working…";
}

export class ChatReadError extends Error {
  readonly inaccessible: boolean;
  readonly retryAfterMs?: number;
  constructor(inaccessible: boolean, retryAfterMs?: number) {
    super(
      inaccessible
        ? "This chat is no longer available in this browser."
        : retryAfterMs
          ? "The demo is busy. Retrying shortly."
          : "The chat could not be loaded. Please try again.",
    );
    this.inaccessible = inaccessible;
    this.retryAfterMs = retryAfterMs;
  }
}

export async function readPrivateChat(
  signal: AbortSignal,
  fetchPage: typeof fetch = fetch,
): Promise<PrivateChat> {
  async function get(path: string) {
    const response = await fetchPage(`/api/demo/${path}`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
    });
    if (response.status === 429) {
      const seconds = Number(response.headers.get("Retry-After"));
      throw new ChatReadError(
        false,
        Number.isFinite(seconds) && seconds > 0
          ? Math.min(60, Math.max(1, seconds)) * 1000
          : 5000,
      );
    }
    if (!response.ok)
      throw new ChatReadError([401, 404].includes(response.status));
    return response.json();
  }

  for (let attempt = 0; attempt < 3; attempt++) {
    const session: Session = await get("session");
    const empty: PrivateChat = {
      threadId: null,
      messages: [],
      failures: [],
      status: "No chat in this browser.",
      active: false,
      chatsRemaining: session.chats_remaining,
      expiresAt: session.expires_at,
    };
    if (session.thread_id === null) {
      return session.deleting
        ? {
            ...empty,
            status: "Chat deletion is in progress.",
            active: true,
            deleting: true,
          }
        : empty;
    }
    if (!UUID.test(session.thread_id)) throw new ChatReadError(false);
    const state = await get(`threads/${session.thread_id}/state`);
    // A different tab may have deleted or replaced the chat while state was loading.
    const current: Session = await get("session");
    if (
      current.thread_id !== session.thread_id ||
      current.run_id !== session.run_id ||
      current.deleting ||
      current.status !== session.status ||
      current.complete !== session.complete ||
      current.submissions_remaining !== session.submissions_remaining
    )
      continue;
    if (
      !current.expires_at ||
      !Number.isFinite(Date.parse(current.expires_at)) ||
      Date.parse(current.expires_at) <= Date.now()
    )
      throw new ChatReadError(true);

    const active = ["pending", "running", "busy"].includes(
      current.status ?? "",
    );
    let status = "Chat paused.";
    if (current.complete) status = "Report complete.";
    else if (current.status === "pending")
      status =
        "Service is busy. Your request is queued and will start automatically.";
    else if (active) status = workingStatus(state);
    else if (["error", "timeout"].includes(current.status ?? ""))
      status = "The run stopped. Your conversation has been saved.";
    else if (
      state.interrupts?.length ||
      state.next?.includes("wait_for_answer")
    )
      status = "Waiting for your answer.";

    return {
      threadId: current.thread_id,
      runId: UUID.test(current.run_id ?? "") ? current.run_id : undefined,
      messages: (state.values?.messages ?? []).map(
        (message: ChatMessage, index: number) => ({
          ...message,
          id: `${message.id ?? "message"}-${index}`,
        }),
      ),
      failures: (state.values?.failures ?? []).flatMap((code: string) =>
        FAILURE_NOTICES[code] ? [FAILURE_NOTICES[code]] : [],
      ),
      status,
      active,
      canAnswer:
        !active &&
        !current.complete &&
        !["error", "timeout"].includes(current.status ?? "") &&
        !!(state.interrupts?.length || state.next?.includes("wait_for_answer")),
      canRetry:
        !active &&
        !current.complete &&
        ["error", "timeout"].includes(current.status ?? ""),
      expiresAt: current.expires_at,
      submissionsRemaining: current.submissions_remaining,
      chatsRemaining: current.chats_remaining,
      ...(active && findResearch(state)
        ? { research: findResearch(state) }
        : {}),
    };
  }
  throw new ChatReadError(false);
}
