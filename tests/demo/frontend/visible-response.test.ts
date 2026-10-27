import assert from "node:assert/strict";
import { test } from "node:test";
import {
  visibleEvent,
  visibleResponse,
} from "../../../demo/frontend/src/server/visible-response.ts";

const MARKER = "PRIVATE_SOURCE_TEXT_MUST_NOT_REACH_THE_BROWSER";
const ID = "11111111-1111-4111-8111-111111111111";

test("state exposes only conversation, failures and input interrupts", () => {
  const state = visibleResponse("state", {
    values: {
      messages: [
        { type: "human", id: "user", content: "Hello", metadata: MARKER },
        {
          type: "ai",
          id: "question",
          content: "Address?",
          additional_kwargs: MARKER,
        },
        {
          type: "ai",
          id: "final-report",
          content: "# Report\n[Source](https://example.com)",
          tool_calls: MARKER,
        },
        { type: "tool", content: MARKER },
        { type: "system", content: MARKER },
        { type: "ai", content: [{ text: MARKER }] },
      ],
      failures: ["map", MARKER],
      sources: MARKER,
      findings: MARKER,
      report: MARKER,
    },
    next: ["wait_for_answer", MARKER],
    interrupts: [
      { id: "q", value: "Address?", internal: MARKER },
      { id: "private", value: { source: MARKER } },
    ],
    tasks: MARKER,
    checkpoint: MARKER,
    metadata: MARKER,
  });
  assert.deepEqual(state, {
    values: {
      messages: [
        { type: "human", id: "user", content: "Hello" },
        { type: "ai", id: "question", content: "Address?" },
        {
          type: "ai",
          id: "final-report",
          content: "# Report\n[Source](https://example.com)",
        },
      ],
      failures: ["map"],
    },
    next: ["wait_for_answer"],
    interrupts: [{ id: "q", value: "Address?" }],
  });
  assert.ok(!JSON.stringify(state).includes(MARKER));
});

test("state counts the research without exposing its tasks", () => {
  const task = (name: string) => ({ name, result: MARKER, state: MARKER });
  const state = visibleResponse("state", {
    values: {},
    next: ["investigate_object", "investigate_object", MARKER],
    tasks: [
      task("investigate_object"),
      task("investigate_object"),
      task("investigate_object"),
      task(MARKER),
    ],
  });
  assert.deepEqual(state, {
    values: { messages: [], failures: [] },
    next: ["investigate_object", "investigate_object"],
    interrupts: [],
    research_total: 3,
  });
  for (const node of [
    "extract_input",
    "detect_language",
    "geocode_input",
    "get_map_objects",
    "get_plans",
    "plan_journeys",
    "triage_objects",
    "get_addresses",
    "write_report",
    "fill_references",
  ])
    assert.deepEqual(visibleResponse("state", { next: [node] }).next, [node]);
});

test("every JSON read removes internal fields and rejects data in status fields", () => {
  for (const kind of ["thread", "run", "session", "limits"] as const) {
    const result = visibleResponse(kind, {
      thread_id: ID,
      run_id: ID,
      status: "success",
      complete: true,
      chats_remaining: 1,
      submissions_remaining: 6,
      expires_at: "2026-11-20T12:00:00+00:00",
      daily_reset: "2026-10-25T00:00:00+02:00",
      daily_chats: 5,
      identity_chats: 2,
      lifetime_days: 30,
      submissions: 7,
      message_chars: 2000,
      values: MARKER,
      input: MARKER,
      output: MARKER,
      metadata: MARKER,
      cookie: MARKER,
      error_message: MARKER,
      sources: MARKER,
    });
    assert.ok(!JSON.stringify(result).includes(MARKER));
    assert.ok(Object.keys(result).length > 0);
    const malformed = visibleResponse(kind, {
      thread_id: { source: MARKER },
      run_id: MARKER,
      status: MARKER,
      complete: MARKER,
      chats_remaining: MARKER,
      daily_chats: -1,
      expires_at: MARKER,
      daily_reset: MARKER,
    });
    assert.deepEqual(malformed, {});
  }
  assert.deepEqual(
    visibleResponse("session", {
      thread_id: null,
      status: null,
      deleting: true,
    }),
    { thread_id: null, status: null, deleting: true },
  );
});

test("update events name every public step and nothing else", () => {
  for (const node of [
    "extract_input",
    "detect_language",
    "geocode_input",
    "get_addresses",
  ])
    assert.deepEqual(visibleEvent("updates", { [node]: { secret: MARKER } }), {
      [node]: { progress: node },
    });
  assert.equal(visibleEvent("updates", { private_node: MARKER }), null);
});
