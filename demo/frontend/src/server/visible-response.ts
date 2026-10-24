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
    return {
      values: values(object(data.values)),
      next: list(data.next).filter((node) => node === "wait_for_answer"),
      interrupts: list(data.interrupts).flatMap((raw) => {
        const item = object(raw);
        return typeof item.id === "string" && typeof item.value === "string"
          ? [{ id: item.id, value: item.value }]
          : [];
      }),
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
