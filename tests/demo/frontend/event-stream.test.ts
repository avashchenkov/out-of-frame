import assert from "node:assert/strict";
import { test } from "node:test";
import { readProxy } from "../../../demo/frontend/src/server/read-proxy.ts";

const ID = "11111111-1111-4111-8111-111111111111";
const RUN = "22222222-2222-4222-8222-222222222222";
const OTHER = "33333333-3333-4333-8333-333333333333";
const SECRET = "test-proxy-secret-at-least-32-chars";
const TOKEN = `${ID}.4102444800.a179d359cefd6f4401d4b5cc4ce6582c461e3cc0c5009cb27230f3b1395687c5`;
const CONFIG = {
  origin: "https://demo.example.com",
  backend: new URL("http://backend:2026"),
  secret: SECRET,
};
const PATH = ["threads", ID, "runs", RUN, "stream"];
const MARKER = "PRIVATE_SOURCE_TEXT_MUST_NOT_REACH_THE_BROWSER";
const ENCODER = new TextEncoder();

function request(headers: Record<string, string> = {}, signal?: AbortSignal) {
  return new Request(`https://demo.example.com/api/demo/${PATH.join("/")}`, {
    headers: { cookie: `oof_identity=${TOKEN}`, ...headers },
    signal,
  });
}

function frame(event: string, data: unknown, sequence?: number) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n${sequence ? `id: ${RUN}_event_${sequence}\n` : ""}\n`;
}

function source(text: string, byteSize = 17) {
  const bytes = ENCODER.encode(text);
  let offset = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (offset === bytes.length) controller.close();
      else {
        controller.enqueue(bytes.slice(offset, offset + byteSize));
        offset = Math.min(offset + byteSize, bytes.length);
      }
    },
  });
}

function sse(body: ReadableStream<Uint8Array>) {
  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Set-Cookie": `secret=${MARKER}`,
      Location: "http://private-backend/",
      "X-Internal": MARKER,
    },
  });
}

test("live and replay streams use the same projection across fragmented UTF-8 and CRLF", async () => {
  const wire =
    `\uFEFF: ${MARKER}\r\n\r\n` +
    frame("metadata", { run_id: RUN, thread_id: ID, attempt: MARKER }, 1) +
    `event: values\r\ndata: {"messages":\r\ndata: [{"type":"ai","content":"Grüße 👋","id":"question","metadata":"${MARKER}"}],\r\ndata: "sources":"${MARKER}","report":"${MARKER}"}\r\nid: ${RUN}_event_2\r\n\r\n` +
    frame(
      "updates",
      { write_report: { report: MARKER }, internal_node: { text: MARKER } },
      3,
    ) +
    frame(
      "values|investigate_object",
      { messages: [{ type: "ai", content: MARKER }] },
      4,
    ) +
    frame("messages/partial", { content: MARKER }, 5) +
    frame("debug", { text: MARKER }, 6) +
    frame("error", { message: MARKER, error: MARKER }, 7) +
    frame("end", { status: "interrupted", internal: MARKER }, 8);
  for (const cursor of [null, `${RUN}_event_1`]) {
    let calls = 0;
    const fetchBackend: typeof fetch = async (url, options) => {
      calls++;
      assert.equal(String(url), `http://backend:2026/${PATH.join("/")}`);
      assert.equal(options?.method, "GET");
      assert.equal(options?.cache, "no-store");
      assert.equal(options?.redirect, "error");
      assert.deepEqual(Object.fromEntries(new Headers(options?.headers)), {
        accept: "text/event-stream",
        "x-demo-key": SECRET,
        "x-demo-identity": ID,
        ...(cursor ? { "last-event-id": cursor } : {}),
      });
      return sse(source(wire, 1));
    };
    const response = await readProxy(
      request({
        ...(cursor ? { "last-event-id": cursor } : {}),
        "x-demo-key": MARKER,
        "x-demo-identity": OTHER,
        authorization: MARKER,
      }),
      PATH,
      CONFIG,
      fetchBackend,
    );
    const output = await response.text();
    assert.equal(calls, 1);
    assert.equal(
      response.headers.get("content-type"),
      "text/event-stream; charset=utf-8",
    );
    assert.equal(response.headers.get("cache-control"), "private, no-store");
    assert.equal(response.headers.get("x-accel-buffering"), "no");
    for (const header of [
      "set-cookie",
      "access-control-allow-origin",
      "location",
      "x-internal",
    ])
      assert.equal(response.headers.get(header), null);
    assert.ok(output.includes(": keepalive\n\n"));
    assert.ok(output.includes("Grüße 👋"));
    assert.ok(output.includes('"write_report":{"progress":"write_report"}'));
    assert.ok(output.includes('"error":"run_failed"'));
    assert.ok(output.includes('"status":"interrupted"'));
    assert.ok(output.includes(`id: ${RUN}_event_8`));
    assert.ok(!output.includes(MARKER));
    for (const event of [
      "debug",
      "messages/partial",
      "values|investigate_object",
    ])
      assert.ok(!output.includes(`event: ${event}`));
  }
});

test("the first event arrives before EOF; disconnect only closes the GET attachment", async () => {
  let cancelled = 0;
  let calls = 0;
  let upstreamSignal: AbortSignal | undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(ENCODER.encode(frame("metadata", { run_id: RUN }, 1)));
    },
    cancel() {
      cancelled++;
    },
  });
  const fetchBackend: typeof fetch = async (_url, options) => {
    calls++;
    assert.equal(options?.method, "GET");
    upstreamSignal = options?.signal ?? undefined;
    return sse(body);
  };
  const response = await readProxy(request(), PATH, CONFIG, fetchBackend);
  const reader = response.body!.getReader();
  const first = await reader.read();
  assert.ok(
    new TextDecoder().decode(first.value).includes(`"run_id":"${RUN}"`),
  );
  await reader.cancel();
  assert.equal(cancelled, 1);
  assert.equal(upstreamSignal?.aborted, true);
  assert.equal(calls, 1);
});

test("abort and identity expiry close a silent attachment without another run", async (t) => {
  t.mock.method(Date, "now", () => 4102444799000);
  for (const abortEarly of [true, false]) {
    let cancelled = 0;
    const controller = new AbortController();
    const body = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled++;
      },
    });
    const response = await readProxy(
      request({}, controller.signal),
      PATH,
      CONFIG,
      async () => sse(body),
    );
    const pending = response.body!.getReader().read();
    if (abortEarly) controller.abort();
    assert.equal((await pending).done, true);
    assert.equal(cancelled, 1);
  }
});

test("invalid cursors, missing identities and cross-origin reads never open a stream", async () => {
  let calls = 0;
  const fetchBackend: typeof fetch = async () => {
    calls++;
    return sse(source(""));
  };
  for (const [headers, status] of [
    [{ "last-event-id": `${OTHER}_event_1` }, 422],
    [{ "last-event-id": MARKER }, 422],
    [{ "last-event-id": `${RUN}_event_` }, 422],
    [{ cookie: "" }, 401],
    [{ origin: "https://attacker.example" }, 403],
  ] as const) {
    const response = await readProxy(
      request(headers),
      PATH,
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, status);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
  }
  assert.equal(calls, 0);
});

test("malformed, oversized and interrupted upstream streams expose fixed errors only", async () => {
  const inputs = [
    `event: values\ndata: ${MARKER}\n\n`,
    `event: values\ndata: "${"x".repeat(17 * 1024 * 1024)}`,
    frame("metadata", { run_id: RUN }, 1), // EOF without end.
  ];
  for (const input of inputs) {
    const response = await readProxy(request(), PATH, CONFIG, async () =>
      sse(source(input, 65536)),
    );
    const text = await response.text();
    assert.ok(text.includes('"error":"stream_unavailable"'));
    assert.ok(!text.includes(MARKER));
    assert.ok(text.length < 1024);
  }
  const badType = await readProxy(request(), PATH, CONFIG, async () =>
    Response.json({ output: MARKER }),
  );
  assert.equal(badType.status, 503);
  assert.ok(!(await badType.text()).includes(MARKER));
});

test("unknown event IDs and post-end data are discarded", async () => {
  const wire =
    `event: values\ndata: {"messages":[]}\nid: ${MARKER}\n\n` +
    frame("end", { status: MARKER }, 2) +
    frame("values", { messages: [{ type: "ai", content: MARKER }] }, 3);
  const response = await readProxy(request(), PATH, CONFIG, async () =>
    sse(source(wire, 65536)),
  );
  const output = await response.text();
  assert.ok(!output.includes(MARKER));
  assert.ok(output.includes('"status":"error"'));
});

test("expiry while waiting for headers or queued data cannot expose a late message", async (t) => {
  let now = 4102444799000;
  t.mock.method(Date, "now", () => now);
  let cancelled = false;
  const fetchLate: typeof fetch = async () => {
    now = 4102444801000;
    return sse(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            ENCODER.encode(
              frame(
                "values",
                { messages: [{ type: "ai", content: MARKER }] },
                1,
              ),
            ),
          );
        },
        cancel() {
          cancelled = true;
        },
      }),
    );
  };
  const late = await readProxy(request(), PATH, CONFIG, fetchLate);
  assert.equal(late.status, 401);
  assert.ok(!(await late.text()).includes(MARKER));
  assert.equal(cancelled, true);

  now = 4102444799000;
  let upstream: ReadableStreamDefaultController<Uint8Array> | undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      upstream = controller;
      controller.enqueue(ENCODER.encode(frame("metadata", { run_id: RUN }, 1)));
    },
  });
  const response = await readProxy(request(), PATH, CONFIG, async () =>
    sse(body),
  );
  const reader = response.body!.getReader();
  assert.ok(
    new TextDecoder().decode((await reader.read()).value).includes("metadata"),
  );
  now = 4102444801000;
  upstream!.enqueue(
    ENCODER.encode(
      frame("values", { messages: [{ type: "ai", content: MARKER }] }, 2),
    ),
  );
  assert.equal((await reader.read()).done, true);
});
