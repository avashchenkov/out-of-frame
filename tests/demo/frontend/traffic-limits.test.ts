import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import {
  TrafficLimits,
  trafficConfig,
} from "../../../demo/frontend/src/server/traffic-limits.ts";
import { proxyRequest } from "../../../demo/frontend/src/server/proxy.ts";

const THREAD = "11111111-1111-4111-8111-111111111111";
const RUN = "22222222-2222-4222-8222-222222222222";
const SECRET = "test-proxy-secret-at-least-32-chars";
const CONFIG = {
  origin: "https://demo.example.com",
  backend: new URL("http://backend:2026"),
  secret: SECRET,
  liveEnabled: true,
};
const STREAM = ["threads", THREAD, "runs", RUN, "stream"];

function request(
  owner = 1,
  path = STREAM,
  signal?: AbortSignal,
  method = "GET",
  expires = 4102444800,
) {
  const id = `${String(owner).padStart(8, "0")}-1111-4111-8111-111111111111`;
  const payload = `${id}.${expires}`;
  const signature = createHmac("sha256", SECRET).update(payload).digest("hex");
  return new Request(`${CONFIG.origin}/api/demo/${path.join("/")}`, {
    method,
    signal,
    headers: {
      cookie: `oof_identity=${payload}.${signature}`,
      origin: CONFIG.origin,
      "x-demo-csrf": "1",
      "content-type": "application/json",
    },
    ...(method === "POST" ? { body: '{"text":"hello"}' } : {}),
  });
}

function fixture() {
  let now = 0;
  let calls = 0;
  let cancellations = 0;
  const controls: ReadableStreamDefaultController<Uint8Array>[] = [];
  const signals: AbortSignal[] = [];
  const traffic = new TrafficLimits(trafficConfig({}), () => now);
  const backend: typeof fetch = async (_url, options) => {
    calls++;
    signals.push(options!.signal!);
    return new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controls.push(controller);
        },
        cancel() {
          cancellations++;
        },
      }),
      { headers: { "Content-Type": "text/event-stream" } },
    );
  };
  return {
    traffic,
    backend,
    controls,
    signals,
    advance(ms: number) {
      now += ms;
    },
    get calls() {
      return calls;
    },
    get cancellations() {
      return cancellations;
    },
    open(owner = 1, signal?: AbortSignal) {
      return proxyRequest(
        request(owner, STREAM, signal),
        STREAM,
        CONFIG,
        backend,
        traffic,
      );
    },
  };
}

test("ten concurrent streams are admitted globally, including pending upstream headers", async () => {
  const f = fixture();
  const responses = await Promise.all(
    Array.from({ length: 12 }, (_, i) => f.open(i + 1)),
  );
  try {
    assert.equal(f.calls, 10);
    assert.deepEqual(
      responses.map((r) => r.status),
      [...Array(10).fill(200), 429, 429],
    );
    assert.equal(responses[10].headers.get("Retry-After"), "5");
    assert.equal(
      responses[10].headers.get("cache-control"),
      "private, no-store",
    );
    assert.deepEqual(await responses[10].json(), { error: "demo_busy" });
  } finally {
    await Promise.all(responses.slice(0, 10).map((r) => r.body!.cancel()));
  }
  const next = await f.open(20);
  assert.equal(next.status, 200);
  await next.body!.cancel();
});

test("one signed identity gets two streams across tabs and run URLs", async () => {
  const f = fixture();
  const first = await f.open();
  const second = await f.open();
  const otherRun = [...STREAM];
  otherRun[3] = THREAD;
  const refused = await proxyRequest(
    request(1, otherRun),
    otherRun,
    CONFIG,
    f.backend,
    f.traffic,
  );
  assert.equal(refused.status, 429);
  assert.equal(f.calls, 2);
  // Reading a saved chat remains possible while its stream slots are full.
  const saved = await proxyRequest(
    request(1, ["session"]),
    ["session"],
    CONFIG,
    async () => Response.json({ thread_id: null }),
    f.traffic,
  );
  assert.equal(saved.status, 200);
  await first.body!.cancel();
  const replacement = await f.open();
  assert.equal(replacement.status, 200);
  await second.body!.cancel();
  await replacement.body!.cancel();
});

test("disconnect releases exactly one slot even if the response is not read", async () => {
  const f = fixture();
  const controller = new AbortController();
  const first = await f.open(1, controller.signal);
  const second = await f.open();
  controller.abort();
  await first.body!.cancel();
  assert.equal(f.signals[0].aborted, true);
  const replacement = await f.open();
  assert.equal(replacement.status, 200);
  assert.equal((await f.open()).status, 429);
  await second.body!.cancel();
  await replacement.body!.cancel();
  assert.equal(f.cancellations, 3);
});

test("upstream errors, invalid streams and normal endings release reservations", async () => {
  const f = fixture();
  for (const backend of [
    async () => {
      throw new Error("unavailable");
    },
    async () => new Response("private", { status: 404 }),
    async () => Response.json({ private: true }),
    async () =>
      new Response('event: end\ndata: {"status":"success"}\n\n', {
        headers: { "Content-Type": "text/event-stream" },
      }),
  ]) {
    for (let i = 0; i < 3; i++) {
      const result = await proxyRequest(
        request(),
        STREAM,
        CONFIG,
        backend,
        f.traffic,
      );
      assert.notEqual(result.status, 429);
      await result.text();
    }
  }
  const final = await f.open();
  assert.equal(final.status, 200);
  await final.body!.cancel();
});

test("expiry closes unread streams and releases their slots", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 4102444799000 });
  const f = fixture();
  const first = await f.open();
  const second = await f.open();
  t.mock.timers.tick(1000);
  assert.ok(f.signals.every((signal) => signal.aborted));
  for (let i = 0; i < 2; i++) {
    const next = await proxyRequest(
      request(1, STREAM, undefined, "GET", 4102444900),
      STREAM,
      CONFIG,
      f.backend,
      f.traffic,
    );
    assert.equal(next.status, 200);
    await next.body!.cancel();
  }
  await first.body!.cancel();
  await second.body!.cancel();
});

test("pending upstream headers hold slots until cancellation or timeout", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture();
  const backend: typeof fetch = async (_url, options) =>
    new Promise((_resolve, reject) => {
      options!.signal!.addEventListener(
        "abort",
        () => reject(new Error("aborted")),
        { once: true },
      );
    });
  const aborted = new AbortController();
  const first = proxyRequest(
    request(1, STREAM, aborted.signal),
    STREAM,
    CONFIG,
    backend,
    f.traffic,
  );
  const second = proxyRequest(request(), STREAM, CONFIG, backend, f.traffic);
  assert.equal((await f.open()).status, 429);
  aborted.abort();
  assert.equal((await first).status, 503);
  const replacement = await f.open();
  assert.equal(replacement.status, 200);
  assert.equal((await f.open()).status, 429);
  t.mock.timers.tick(10000);
  assert.equal((await second).status, 503);
  const next = await f.open();
  assert.equal(next.status, 200);
  await replacement.body!.cancel();
  await next.body!.cancel();
});

test("invalid identities and cursors cannot occupy stream slots", async () => {
  const f = fixture();
  const noIdentity = request();
  noIdentity.headers.delete("cookie");
  const forged = request();
  forged.headers.set("cookie", "oof_identity=forged");
  const badCursor = request();
  badCursor.headers.set("Last-Event-ID", "wrong-run_event_1");
  for (const req of [noIdentity, forged, badCursor]) {
    const result = await proxyRequest(
      req,
      STREAM,
      CONFIG,
      f.backend,
      f.traffic,
    );
    assert.ok([401, 422].includes(result.status));
  }
  assert.equal(f.calls, 0);
  const first = await f.open();
  const second = await f.open();
  assert.equal(first.status, 200);
  assert.equal(second.status, 200);
  await first.body!.cancel();
  await second.body!.cancel();
});

test("a single rate bucket covers reads, streams and mutations before backend work", async () => {
  const f = fixture();
  let calls = 0;
  const backend: typeof fetch = async () => {
    calls++;
    return Response.json({ thread_id: null });
  };
  for (let i = 0; i < 40; i++) {
    const result = await proxyRequest(
      request(i + 1, ["session"]),
      ["session"],
      CONFIG,
      backend,
      f.traffic,
    );
    assert.equal(result.status, 200);
  }
  for (const [method, path] of [
    ["GET", ["limits"]],
    ["GET", STREAM],
    ["POST", ["chat"]],
    ["DELETE", ["chat"]],
  ] as const) {
    const result = await proxyRequest(
      request(1, [...path], undefined, method),
      [...path],
      CONFIG,
      backend,
      f.traffic,
    );
    assert.equal(result.status, 429);
    assert.equal(result.headers.get("set-cookie"), null);
    assert.deepEqual(await result.json(), { error: "demo_busy" });
  }
  assert.equal(calls, 40);
  f.advance(50);
  assert.equal(
    (
      await proxyRequest(
        request(1, ["session"]),
        ["session"],
        CONFIG,
        backend,
        f.traffic,
      )
    ).status,
    200,
  );
  assert.equal((await f.open()).status, 429);
  f.advance(10_000);
  for (let i = 0; i < 40; i++) assert.equal(f.traffic.allowRequest(), true);
  assert.equal(f.traffic.allowRequest(), false);
});

test("traffic settings have safe defaults and reject invalid values", () => {
  assert.deepEqual(trafficConfig({}), {
    streams: 10,
    streamsPerIdentity: 2,
    requestsPerSecond: 20,
    requestBurst: 40,
  });
  assert.equal(trafficConfig({ OUT_OF_FRAME_DEMO_STREAMS: "5" }).streams, 5);
  for (const value of ["", "0", "-1", "NaN", "Infinity", "1.5", "1e3"]) {
    assert.throws(() => trafficConfig({ OUT_OF_FRAME_DEMO_STREAMS: value }));
  }
});
