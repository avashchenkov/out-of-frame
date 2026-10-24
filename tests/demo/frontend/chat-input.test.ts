import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ChatSubmitError,
  deleteChat,
  readDemoLimits,
  submitChat,
} from "../../../demo/frontend/src/lib/chat-input.ts";

const signal = () => new AbortController().signal;
const LIMITS = {
  identity_chats: 2,
  lifetime_days: 30,
  submissions: 7,
  message_chars: 2000,
  daily_reset: "2100-01-01T00:00:00Z",
};

test("the page uses configured limits without fallback numbers", async () => {
  const limits = await readDemoLimits(signal(), async (url, options) => {
    assert.equal(url, "/api/demo/limits");
    assert.equal(options?.cache, "no-store");
    return Response.json({ ...LIMITS, message_chars: 123 });
  });
  assert.equal(limits.message_chars, 123);
  await assert.rejects(
    readDemoLimits(signal(), async () => new Response(null, { status: 503 })),
  );
  for (const data of [
    {},
    { ...LIMITS, submissions: -1 },
    { ...LIMITS, daily_reset: "invalid" },
  ]) {
    await assert.rejects(
      readDemoLimits(signal(), async () => Response.json(data)),
    );
  }
});

test("replacement uses one admission request and leaves deletion to the server", async () => {
  const calls: string[] = [];
  await assert.rejects(
    submitChat(
      "replace",
      "A new scenario",
      "old-thread",
      signal(),
      async (url, options) => {
        calls.push(`${options?.method} ${url}`);
        assert.deepEqual(JSON.parse(String(options?.body)), {
          text: "A new scenario",
          replace: true,
        });
        return Response.json(
          { error: "daily_chats_exhausted" },
          { status: 429 },
        );
      },
    ),
    ChatSubmitError,
  );
  assert.deepEqual(calls, ["POST /api/demo/chat"]);
});

test("explicit deletion sends no input, execution overrides or cookie edits", async () => {
  let calls = 0;
  await deleteChat(signal(), async (url, options) => {
    calls++;
    assert.equal(url, "/api/demo/chat");
    assert.equal(options?.method, "DELETE");
    assert.equal(options?.body, undefined);
    assert.equal(options?.credentials, "same-origin");
    assert.deepEqual(options?.headers, { "X-Demo-CSRF": "1" });
    return Response.json({ deleted: true });
  });
  assert.equal(calls, 1);
});

test("pending or ambiguous deletion is never reported as success or repeated", async () => {
  for (const kind of ["pending", "malformed", "incomplete", "network"]) {
    let calls = 0;
    await assert.rejects(
      deleteChat(signal(), async () => {
        calls++;
        if (kind === "network") throw new Error("PRIVATE_ERROR");
        if (kind === "pending")
          return Response.json({ error: "deletion_pending" }, { status: 409 });
        if (kind === "incomplete") return Response.json({ deleted: false });
        return new Response("PRIVATE_ERROR");
      }),
      (error: unknown) =>
        error instanceof ChatSubmitError &&
        !error.message.includes("PRIVATE") &&
        (kind === "pending"
          ? error.code === "deletion_pending"
          : error.uncertain),
    );
    assert.equal(calls, 1);
  }
});

test("first messages, answers and retries use fixed same-origin CSRF requests", async () => {
  for (const action of ["new", "answer", "retry"] as const) {
    let calls = 0;
    await submitChat(
      action,
      "A fictional trip",
      "thread-id",
      signal(),
      async (url, options) => {
        calls++;
        assert.equal(
          url,
          `/api/demo/${action === "new" ? "chat" : action === "answer" ? "threads/thread-id/runs" : "retry"}`,
        );
        assert.equal(options?.method, "POST");
        assert.equal(options?.credentials, "same-origin");
        assert.equal(options?.cache, "no-store");
        assert.deepEqual(options?.headers, {
          "Content-Type": "application/json",
          "X-Demo-CSRF": "1",
        });
        assert.deepEqual(
          JSON.parse(String(options?.body)),
          action === "retry" ? {} : { text: "A fictional trip" },
        );
        return Response.json({ thread_id: "thread-id", run_id: "run-id" });
      },
    );
    assert.equal(calls, 1);
  }
});

test("quota refusals stay distinct without exposing backend text", async () => {
  for (const code of [
    "identity_chats_exhausted",
    "daily_chats_exhausted",
    "submissions_exhausted",
  ]) {
    let calls = 0;
    await assert.rejects(
      submitChat("new", "Hello", null, signal(), async () => {
        calls++;
        return Response.json(
          { error: code, details: "PRIVATE_BACKEND_TEXT" },
          { status: 429 },
        );
      }),
      (error: unknown) => {
        assert.ok(error instanceof ChatSubmitError);
        assert.equal(error.uncertain, false);
        assert.equal(error.code, code);
        assert.ok(!error.message.includes("PRIVATE"));
        if (code === "identity_chats_exhausted")
          assert.match(error.message, /Contact the author/);
        if (code === "daily_chats_exhausted")
          assert.match(error.message, /try again tomorrow/);
        return true;
      },
    );
    assert.equal(calls, 1);
  }
});

test("ambiguous results require reconciliation and never resend automatically", async () => {
  for (const outcome of ["network", "malformed", "server"] as const) {
    let calls = 0;
    await assert.rejects(
      submitChat("new", "Hello", null, signal(), async () => {
        calls++;
        if (outcome === "network") throw new Error("PRIVATE_ERROR");
        if (outcome === "malformed")
          return new Response("PRIVATE_ERROR", { status: 502 });
        return Response.json({ error: "PRIVATE_ERROR" }, { status: 503 });
      }),
      (error: unknown) =>
        error instanceof ChatSubmitError &&
        error.uncertain &&
        !error.message.includes("PRIVATE"),
    );
    assert.equal(calls, 1);
  }
});
