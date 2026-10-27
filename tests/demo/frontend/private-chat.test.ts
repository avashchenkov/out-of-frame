import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ChatReadError,
  readPrivateChat,
} from "../../../demo/frontend/src/lib/private-chat.ts";

const ID = "11111111-1111-4111-8111-111111111111";
const RUN = "22222222-2222-4222-8222-222222222222";
const SESSION = {
  thread_id: ID,
  run_id: RUN,
  status: "interrupted",
  complete: false,
  expires_at: "2100-01-01T00:00:00Z",
  submissions_remaining: 6,
  chats_remaining: 1,
};
const STATE = {
  values: {
    messages: [
      { id: null, type: "human", content: "A Berlin address" },
      { id: "question", type: "ai", content: "Where do you travel?" },
    ],
    failures: ["plans"],
  },
  next: ["wait_for_answer"],
  interrupts: [{ id: "ask", value: "Where do you travel?" }],
};

function responses(...bodies: unknown[]) {
  const paths: string[] = [];
  const fetchPage: typeof fetch = async (url, options) => {
    paths.push(String(url));
    assert.equal(options?.method, "GET");
    assert.equal(options?.credentials, "same-origin");
    assert.equal(options?.cache, "no-store");
    assert.ok(options?.signal);
    assert.ok(bodies.length, "unexpected request");
    return Response.json(bodies.shift());
  };
  return { fetchPage, paths };
}

test("an empty browser session reads no thread and starts no run", async () => {
  const { fetchPage, paths } = responses({ thread_id: null });
  const chat = await readPrivateChat(new AbortController().signal, fetchPage);
  assert.deepEqual(paths, ["/api/demo/session"]);
  assert.equal(chat.threadId, null);
  assert.deepEqual(chat.messages, []);
  assert.equal(chat.active, false);
});

test("reload restores visible messages, failures and remaining submissions", async () => {
  const { fetchPage, paths } = responses(SESSION, STATE, SESSION);
  const chat = await readPrivateChat(new AbortController().signal, fetchPage);
  assert.deepEqual(paths, [
    "/api/demo/session",
    `/api/demo/threads/${ID}/state`,
    "/api/demo/session",
  ]);
  assert.equal(chat.messages.length, 2);
  assert.equal(chat.messages[1].content, "Where do you travel?");
  assert.equal(new Set(chat.messages.map((message) => message.id)).size, 2);
  assert.equal(chat.submissionsRemaining, 6);
  assert.equal(chat.chatsRemaining, 1);
  assert.equal(chat.runId, RUN);
  assert.match(chat.failures[0], /Development plans could not be loaded/);
  assert.equal(chat.status, "Waiting for your answer.");
  assert.equal(chat.active, false);
});

test("a different latest run discards a snapshot even with unchanged counters", async () => {
  const changed = { ...SESSION, run_id: ID };
  const { fetchPage } = responses(
    SESSION,
    STATE,
    changed,
    changed,
    STATE,
    changed,
  );
  const chat = await readPrivateChat(new AbortController().signal, fetchPage);
  assert.equal(chat.runId, ID);
});

test("queued, running, failed and completed chats use server completion", async () => {
  for (const [status, complete, active, notice] of [
    ["pending", false, true, /queued and will start automatically/],
    ["running", false, true, /^Working…$/],
    ["error", false, false, /run stopped/],
    ["success", false, false, /Waiting for your answer/],
    ["success", true, false, /Report complete/],
  ] as const) {
    const session = { ...SESSION, status, complete };
    const { fetchPage } = responses(session, STATE, session);
    const chat = await readPrivateChat(new AbortController().signal, fetchPage);
    assert.equal(chat.active, active);
    assert.match(chat.status, notice);
    assert.equal(chat.canRetry, status === "error" && !complete);
    assert.equal(chat.canAnswer, !active && !complete && status !== "error");
  }
});

test("a running chat names its current step and counts the researched objects", async () => {
  const running = { ...SESSION, status: "running" };
  const research = (done: number) => ({
    ...STATE,
    next: Array(3 - done).fill("investigate_object"),
    research_total: 3,
  });
  for (const [state, notice] of [
    [{ ...STATE, next: [] }, "Working…"],
    [{ ...STATE, next: ["triage_objects"] }, "Checking the places nearby…"],
    [research(0), "Researching objects on the web: 0 of 3…"],
    [research(2), "Researching objects on the web: 2 of 3…"],
    [{ ...STATE, next: ["write_report"] }, "Writing the report…"],
    [{ ...STATE, next: ["fill_references"] }, "Writing the report…"],
  ] as const) {
    const { fetchPage } = responses(running, state, running);
    const chat = await readPrivateChat(new AbortController().signal, fetchPage);
    assert.equal(chat.status, notice);
  }
});

test("replacement or deletion in another tab discards the old snapshot", async () => {
  const { fetchPage } = responses(
    SESSION,
    STATE,
    { thread_id: null },
    { thread_id: null },
  );
  const chat = await readPrivateChat(new AbortController().signal, fetchPage);
  assert.equal(chat.threadId, null);
  assert.deepEqual(chat.messages, []);
  const deleting = responses({
    thread_id: null,
    deleting: true,
    chats_remaining: 0,
  });
  const pending = await readPrivateChat(
    new AbortController().signal,
    deleting.fetchPage,
  );
  assert.equal(pending.active, true);
  assert.equal(pending.deleting, true);
  assert.equal(pending.chatsRemaining, 0);
  assert.deepEqual(pending.messages, []);
});

test("deleting a chat preserves the identity quota and expiry in an empty session", async () => {
  const { fetchPage } = responses({
    thread_id: null,
    chats_remaining: 0,
    expires_at: SESSION.expires_at,
  });
  const chat = await readPrivateChat(new AbortController().signal, fetchPage);
  assert.deepEqual(chat.messages, []);
  assert.equal(chat.chatsRemaining, 0);
  assert.equal(chat.expiresAt, SESSION.expires_at);
});

test("a run ending during a read reloads state before declaring completion", async () => {
  const running = { ...SESSION, status: "running" };
  const done = { ...SESSION, status: "success", complete: true };
  const report = {
    ...STATE,
    values: {
      messages: [
        { id: "final-report", type: "ai", content: "Finished report" },
      ],
      failures: [],
    },
  };
  const { fetchPage } = responses(running, STATE, done, done, report, done);
  const chat = await readPrivateChat(new AbortController().signal, fetchPage);
  assert.equal(chat.status, "Report complete.");
  assert.equal(chat.messages[0].content, "Finished report");
});

test("expired, denied or missing access never returns saved messages or raw errors", async () => {
  for (const status of [401, 404, 503]) {
    const fetchPage: typeof fetch = async () =>
      Response.json({ error: "PRIVATE_INTERNAL_ERROR" }, { status });
    await assert.rejects(
      readPrivateChat(new AbortController().signal, fetchPage),
      (error: unknown) =>
        error instanceof ChatReadError && !error.message.includes("PRIVATE"),
    );
  }
  const expired = { ...SESSION, expires_at: "2000-01-01T00:00:00Z" };
  const { fetchPage } = responses(expired, STATE, expired);
  await assert.rejects(
    readPrivateChat(new AbortController().signal, fetchPage),
    /no longer available/,
  );
});

test("an answer in another tab reloads even when both runs end interrupted", async () => {
  const answered = { ...SESSION, submissions_remaining: 5 };
  const nextQuestion = {
    ...STATE,
    values: {
      ...STATE.values,
      messages: [
        { id: "question-2", type: "ai", content: "When do you leave?" },
      ],
    },
  };
  const { fetchPage } = responses(
    SESSION,
    STATE,
    answered,
    answered,
    nextQuestion,
    answered,
  );
  const chat = await readPrivateChat(new AbortController().signal, fetchPage);
  assert.equal(chat.messages[0].content, "When do you leave?");
  assert.equal(chat.submissionsRemaining, 5);
  assert.equal(chat.status, "Waiting for your answer.");
});
