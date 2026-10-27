import { UUID } from "./identity.ts";

type ObjectValue = Record<string, unknown>;
export type ReadKind = "limits" | "session" | "thread" | "state" | "run";
const STATUSES = new Set([
  "idle",
  "busy",
  "pending",
  "running",
  "success",
  "error",
  "timeout",
  "interrupted",
]);
const FAILURES = new Set(["map", "plans", "transit", "web search"]);
// The steps that the page names while a run works. The research runs one task per
// object, so its remaining tasks stay in the list, one entry each.
const NEXT = new Set([
  "wait_for_answer",
  "triage_objects",
  "investigate_object",
  "write_report",
  "fill_references",
]);

function object(value: unknown): ObjectValue {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as ObjectValue)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function pick(
  data: ObjectValue,
  fields: string[],
  valid: (value: unknown) => boolean,
) {
  return Object.fromEntries(
    fields.filter((key) => valid(data[key])).map((key) => [key, data[key]]),
  );
}

function isId(value: unknown) {
  return typeof value === "string" && UUID.test(value);
}

function isCount(value: unknown) {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isDate(value: unknown) {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T[\d:.+-]+Z?$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function values(data: ObjectValue) {
  const messages = list(data.messages).flatMap((raw) => {
    const message = object(raw);
    if (
      (message.type !== "human" && message.type !== "ai") ||
      typeof message.content !== "string"
    )
      return [];
    return [
      {
        type: message.type,
        content: message.content,
        id: typeof message.id === "string" ? message.id : null,
      },
    ];
  });
  return {
    messages,
    failures: list(data.failures).filter(
      (item) => typeof item === "string" && FAILURES.has(item),
    ),
  };
}

export function visibleResponse(kind: ReadKind, raw: unknown): ObjectValue {
  const data = object(raw);
  if (kind === "state") {
    // Only the number of research tasks leaves the server, never the tasks.
    const research = list(data.tasks).filter(
      (task) => object(task).name === "investigate_object",
    ).length;
    return {
      values: values(object(data.values)),
      next: list(data.next).filter(
        (node) => typeof node === "string" && NEXT.has(node),
      ),
      interrupts: list(data.interrupts).flatMap((raw) => {
        const item = object(raw);
        return typeof item.id === "string" && typeof item.value === "string"
          ? [{ id: item.id, value: item.value }]
          : [];
      }),
      ...(research > 0 ? { research_total: research } : {}),
    };
  }
  if (kind === "limits") {
    return {
      ...pick(
        data,
        [
          "daily_chats",
          "identity_chats",
          "lifetime_days",
          "submissions",
          "message_chars",
        ],
        isCount,
      ),
      ...pick(data, ["daily_reset"], isDate),
    };
  }
  const result = {
    ...pick(data, ["thread_id", "run_id"], isId),
    ...pick(
      data,
      ["status"],
      (value) => typeof value === "string" && STATUSES.has(value),
    ),
  };
  if (kind !== "session") return result;
  return {
    ...result,
    ...(data.thread_id === null ? { thread_id: null } : {}),
    ...(data.status === null ? { status: null } : {}),
    ...pick(
      data,
      ["complete", "deleting"],
      (value) => typeof value === "boolean",
    ),
    ...pick(data, ["chats_remaining", "submissions_remaining"], isCount),
    ...pick(data, ["expires_at"], isDate),
  };
}

const PROGRESS = new Set([
  "get_map_objects",
  "get_plans",
  "plan_journeys",
  "triage_objects",
  "investigate_object",
  "write_report",
]);

export function visibleEvent(event: string, raw: unknown): ObjectValue | null {
  const data = object(raw);
  if (event === "values") return values(data);
  if (event === "updates") {
    const nodes = Object.keys(data).filter((node) => PROGRESS.has(node));
    return nodes.length
      ? Object.fromEntries(nodes.map((node) => [node, { progress: node }]))
      : null;
  }
  if (event === "metadata") return pick(data, ["run_id", "thread_id"], isId);
  if (event === "error") return { error: "run_failed" };
  if (event === "end") {
    return {
      status: ["success", "error", "interrupted", "timeout"].includes(
        String(data.status),
      )
        ? data.status
        : "error",
    };
  }
  return null;
}
