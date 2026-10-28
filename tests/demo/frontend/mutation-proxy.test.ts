import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import { mutationProxy } from "../../../demo/frontend/src/server/mutation-proxy.ts";

const ID = "11111111-1111-4111-8111-111111111111";
const THREAD = "22222222-2222-4222-8222-222222222222";
const RUN = "33333333-3333-4333-8333-333333333333";
const SECRET = "test-proxy-secret-at-least-32-chars";
const EXPIRY = 4102444800;
const MARKER = "PRIVATE_SOURCE_TEXT_MUST_NOT_REACH_THE_BROWSER";
const CONFIG = {
  origin: "https://demo.example.com",
  backend: new URL("http://backend:2026"),
  secret: SECRET,
  liveEnabled: true,
};

function token(identity = ID, expires = EXPIRY) {
  const payload = `${identity}.${expires}`;
  return `${payload}.${createHmac("sha256", SECRET).update(payload).digest("hex")}`;
}

function request(
  path: string[],
  body: unknown = {},
  headers: Record<string, string> = {},
  method = "POST",
) {
  return new Request(`https://demo.example.com/api/demo/${path.join("/")}`, {
    method,
    headers: {
      origin: CONFIG.origin,
      "x-demo-csrf": "1",
      "content-type": "application/json",
      cookie: `oof_identity=${token()}`,
      ...headers,
    },
    body: method === "DELETE" ? undefined : JSON.stringify(body),
  });
}

test("first admission creates a server identity and sets only the authenticated cookie", async () => {
  let identity = "";
  let calls = 0;
  const expires = Math.floor(Date.now() / 1000) + 3600;
  const fetchBackend: typeof fetch = async (url, options) => {
    calls++;
    assert.equal(String(url), "http://backend:2026/demo/chat");
    assert.equal(options?.method, "POST");
    assert.equal(options?.cache, "no-store");
    assert.equal(options?.redirect, "error");
    const headers = new Headers(options?.headers);
    identity = headers.get("x-demo-identity")!;
    assert.match(identity, /^[0-9a-f-]{36}$/);
    assert.notEqual(identity, ID);
    assert.deepEqual(Object.fromEntries(headers), {
      "content-type": "application/json",
      "x-demo-csrf": "1",
      "x-demo-identity": identity,
      "x-demo-key": SECRET,
    });
    assert.deepEqual(JSON.parse(String(options?.body)), {
      text: "Berlin address",
      replace: false,
    });
    return Response.json(
      {
        thread_id: THREAD,
        run_id: RUN,
        cookie: token(identity, expires),
        sources: MARKER,
      },
      {
        headers: {
          "set-cookie": `untrusted=${MARKER}`,
          location: MARKER,
          "access-control-allow-origin": "*",
        },
      },
    );
  };
  const response = await mutationProxy(
    request(
      ["chat"],
      { text: "Berlin address" },
      {
        cookie: "",
        "x-demo-identity": ID,
        "x-demo-key": MARKER,
        authorization: MARKER,
        "x-forwarded-for": "1.2.3.4",
      },
    ),
    ["chat"],
    CONFIG,
    fetchBackend,
  );
  assert.equal(calls, 1);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.equal(
    response.headers.get("set-cookie"),
    `oof_identity=${token(identity, expires)}; Path=/; Expires=${new Date(expires * 1000).toUTCString()}; HttpOnly; Secure; SameSite=Lax`,
  );
  assert.equal(response.headers.get("location"), null);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
  assert.deepEqual(await response.json(), {
    thread_id: THREAD,
    run_id: RUN,
    expires_at: new Date(expires * 1000).toISOString(),
  });
});

test("replacement uses the existing identity and never renews its cookie", async () => {
  const fetchBackend: typeof fetch = async (_url, options) => {
    assert.equal(new Headers(options?.headers).get("x-demo-identity"), ID);
    assert.deepEqual(JSON.parse(String(options?.body)), {
      text: "New address",
      replace: true,
    });
    return Response.json({
      thread_id: THREAD,
      run_id: RUN,
      cookie: token(),
      input: MARKER,
    });
  };
  const response = await mutationProxy(
    request(["chat"], { text: "New address", replace: true }),
    ["chat"],
    CONFIG,
    fetchBackend,
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(
    (await response.json()).expires_at,
    new Date(EXPIRY * 1000).toISOString(),
  );
});

test("answers use fixed run settings and retries leave checkpoint selection to Aegra", async () => {
  const answer = ["threads", THREAD, "runs"];
  const fetchBackend: typeof fetch = async (url, options) => {
    assert.equal(String(url), `http://backend:2026/threads/${THREAD}/runs`);
    assert.deepEqual(JSON.parse(String(options?.body)), {
      assistant_id: "agent",
      multitask_strategy: "reject",
      on_disconnect: "continue",
      durability: "sync",
      stream_mode: ["values", "updates"],
      stream_subgraphs: false,
      command: { resume: "At 08:00" },
    });
    return Response.json({
      thread_id: THREAD,
      run_id: RUN,
      status: "pending",
      output: MARKER,
      metadata: MARKER,
    });
  };
  const response = await mutationProxy(
    request(answer, { text: "At 08:00" }),
    answer,
    CONFIG,
    fetchBackend,
  );
  assert.deepEqual(await response.json(), {
    thread_id: THREAD,
    run_id: RUN,
    status: "pending",
  });
  assert.equal(response.headers.get("set-cookie"), null);
  const retryBackend: typeof fetch = async (url, options) => {
    assert.equal(String(url), "http://backend:2026/demo/retry");
    assert.equal(options?.body, undefined);
    assert.equal(new Headers(options?.headers).get("x-demo-identity"), ID);
    return Response.json({
      thread_id: THREAD,
      run_id: RUN,
      status: "pending",
      checkpoint: MARKER,
    });
  };
  const retry = await mutationProxy(
    request(["retry"]),
    ["retry"],
    CONFIG,
    retryBackend,
  );
  assert.deepEqual(await retry.json(), {
    thread_id: THREAD,
    run_id: RUN,
    status: "pending",
  });
  assert.equal(retry.headers.get("set-cookie"), null);
});

test("deletion remains available when submissions are disabled and retains the identity", async () => {
  const fetchBackend: typeof fetch = async (url, options) => {
    assert.equal(String(url), "http://backend:2026/demo/chat");
    assert.equal(options?.method, "DELETE");
    assert.equal(options?.body, undefined);
    return Response.json({ deleted: true, internal: MARKER });
  };
  const response = await mutationProxy(
    request(["chat"], {}, {}, "DELETE"),
    ["chat"],
    { ...CONFIG, liveEnabled: false },
    fetchBackend,
  );
  assert.deepEqual(await response.json(), { deleted: true });
  assert.equal(response.headers.get("set-cookie"), null);
});

test("origin, CSRF and JSON checks reject browser cross-site requests before forwarding", async () => {
  let calls = 0;
  const fetchBackend: typeof fetch = async () => {
    calls++;
    throw new Error("must not be called");
  };
  for (const [headers, status] of [
    [{ origin: "" }, 403],
    [{ origin: "null" }, 403],
    [{ origin: "https://attacker.example" }, 403],
    [{ "sec-fetch-site": "cross-site" }, 403],
    [{ "x-demo-csrf": "" }, 403],
    [{ "content-type": "text/plain" }, 415],
    [{ "content-type": "application/x-www-form-urlencoded" }, 415],
  ] as const) {
    const response = await mutationProxy(
      request(["chat"], { text: "Hello" }, headers),
      ["chat"],
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, status);
    assert.equal(response.headers.get("set-cookie"), null);
  }
  assert.equal(calls, 0);
});

test("execution overrides, malformed bodies and unsupported routes cannot start a run", async () => {
  let calls = 0;
  const fetchBackend: typeof fetch = async () => {
    calls++;
    throw new Error("must not be called");
  };
  for (const body of [
    null,
    [],
    "Hello",
    {},
    { text: " " },
    { text: 1 },
    { text: "Hi", replace: "yes" },
    { text: "Hi", assistant_id: "other" },
    { text: "Hi", config: {} },
    { text: "Hi", command: { resume: "other" } },
    { text: "Hi", identity: ID },
    { text: "Hi", checkpoint: { checkpoint_id: ID } },
  ]) {
    const response = await mutationProxy(
      request(["chat"], body),
      ["chat"],
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, 422);
  }
  for (const path of [
    ["threads"],
    ["threads", THREAD, "state"],
    ["threads", THREAD, "runs", "stream"],
    ["threads", "invalid", "runs"],
  ]) {
    const response = await mutationProxy(
      request(path, { text: "Hi" }),
      path,
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, 403);
  }
  for (const [path, body] of [
    [["retry"], { checkpoint: ID }],
    [["threads", THREAD, "runs"], { text: "Hi", replace: true }],
  ] as const) {
    assert.equal(
      (
        await mutationProxy(
          request([...path], body),
          [...path],
          CONFIG,
          fetchBackend,
        )
      ).status,
      422,
    );
  }
  assert.equal(calls, 0);
});

test("the request byte limit also applies to chunked bodies", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("x".repeat(17_000)));
    },
    cancel() {
      cancelled = true;
    },
  });
  const req = new Request("https://demo.example.com/api/demo/chat", {
    method: "POST",
    headers: {
      origin: CONFIG.origin,
      "x-demo-csrf": "1",
      "content-type": "application/json",
    },
    body,
    duplex: "half",
  } as RequestInit);
  let calls = 0;
  const response = await mutationProxy(req, ["chat"], CONFIG, async () => {
    calls++;
    throw new Error("must not be called");
  });
  assert.equal(response.status, 413);
  assert.equal(cancelled, true);
  assert.equal(calls, 0);
});

test("missing or forged identities cannot answer, retry or delete", async () => {
  let calls = 0;
  const fetchBackend: typeof fetch = async () => {
    calls++;
    throw new Error("must not be called");
  };
  for (const [method, path] of [
    ["POST", ["retry"]],
    ["POST", ["threads", THREAD, "runs"]],
    ["DELETE", ["chat"]],
  ] as const) {
    const response = await mutationProxy(
      request(
        [...path],
        { text: "Hi" },
        { cookie: "", "x-demo-identity": ID },
        method,
      ),
      [...path],
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, 401);
  }
  for (const cookie of [
    "oof_identity=forged",
    `oof_identity=${token()}; oof_identity=${token()}`,
  ]) {
    const response = await mutationProxy(
      request(["chat"], { text: "Hi" }, { cookie }),
      ["chat"],
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, 401);
  }
  assert.equal(calls, 0);
});

test("live submissions default to disabled without affecting reads or deletion", async () => {
  let calls = 0;
  const fetchBackend: typeof fetch = async () => {
    calls++;
    throw new Error("must not be called");
  };
  for (const path of [["chat"], ["retry"], ["threads", THREAD, "runs"]]) {
    const response = await mutationProxy(
      request(path, { text: "Hi" }),
      path,
      { ...CONFIG, liveEnabled: false },
      fetchBackend,
    );
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { error: "live_unavailable" });
    assert.equal(response.headers.get("set-cookie"), null);
  }
  assert.equal(calls, 0);
});

test("backend refusals preserve fixed codes, never set cookies and never retry", async () => {
  for (const [status, code] of [
    [429, "daily_chats_exhausted"],
    [429, "identity_chats_exhausted"],
    [429, "submissions_exhausted"],
    [409, "deletion_pending"],
    [409, "run_active"],
    [422, "message_too_long"],
  ] as const) {
    // Aegra turns HTTPException into its Agent Protocol error body, with the
    // code in `message`; plain FastAPI puts it in `detail`.
    for (const body of [
      { error: "unknown_error", message: code, details: MARKER },
      { detail: code, source: MARKER },
    ]) {
      let calls = 0;
      const response = await mutationProxy(
        request(["chat"], { text: "Hi" }, { cookie: "" }),
        ["chat"],
        CONFIG,
        async () => {
          calls++;
          return Response.json(body, {
            status,
            headers: { "set-cookie": MARKER },
          });
        },
      );
      assert.equal(response.status, status);
      assert.deepEqual(await response.json(), { error: code });
      assert.equal(response.headers.get("set-cookie"), null);
      assert.equal(calls, 1);
    }
  }
  for (const fetchBackend of [
    async () => Response.json({ detail: MARKER }, { status: 500 }),
    async () => Response.json({ detail: MARKER }, { status: 403 }),
    async () => {
      throw new Error(MARKER);
    },
    async () => new Response(MARKER),
  ]) {
    const response = await mutationProxy(
      request(["chat"], { text: "Hi" }),
      ["chat"],
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, 503);
    assert.ok(!(await response.text()).includes(MARKER));
    assert.equal(response.headers.get("set-cookie"), null);
  }
});

test("malformed or renewed backend credentials cannot become browser cookies", async () => {
  for (const cookie of [
    token(THREAD),
    token(ID, 1000),
    token(ID, EXPIRY + 1),
    `${token()}; Domain=example.com`,
    MARKER,
  ]) {
    const response = await mutationProxy(
      request(["chat"], { text: "Hi" }),
      ["chat"],
      CONFIG,
      async () => Response.json({ thread_id: THREAD, run_id: RUN, cookie }),
    );
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("set-cookie"), null);
  }
});

test("expiry while awaiting admission cannot return private data or renew access", async (t) => {
  let now = (EXPIRY - 1) * 1000;
  t.mock.method(Date, "now", () => now);
  const response = await mutationProxy(
    request(["chat"], { text: "Hi" }),
    ["chat"],
    CONFIG,
    async () => {
      now = (EXPIRY + 1) * 1000;
      return Response.json({
        thread_id: THREAD,
        run_id: RUN,
        cookie: token(),
        private: MARKER,
      });
    },
  );
  assert.equal(response.status, 401);
  assert.ok(!(await response.text()).includes(MARKER));
  assert.equal(response.headers.get("set-cookie"), null);
});
