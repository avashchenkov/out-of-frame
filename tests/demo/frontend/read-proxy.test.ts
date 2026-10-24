import assert from "node:assert/strict";
import { test } from "node:test";
import {
  readProxy,
  disabledRoute,
  proxyConfig,
} from "../../../demo/frontend/src/server/read-proxy.ts";
import { readIdentity } from "../../../demo/frontend/src/server/identity.ts";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const SECRET = "test-proxy-secret-at-least-32-chars";
// Generated with the backend's Python HMAC-SHA256 format, expiring on 2100-01-01.
const TOKEN = `${ID}.4102444800.a179d359cefd6f4401d4b5cc4ce6582c461e3cc0c5009cb27230f3b1395687c5`;
const CONFIG = {
  origin: "https://demo.example.com",
  backend: new URL("http://backend:2026"),
  secret: SECRET,
};
const MARKER = "PRIVATE_SOURCE_TEXT_MUST_NOT_REACH_THE_BROWSER";

function request(path: string, headers: HeadersInit = {}, method = "GET") {
  return new Request(`https://demo.example.com/api/demo/${path}`, {
    method,
    headers: { cookie: `oof_identity=${TOKEN}`, ...headers },
  });
}

test("cookies match Python signatures and reject forgery, expiry and ambiguity", (t) => {
  assert.equal(readIdentity(`other=1; oof_identity=${TOKEN}`, SECRET), ID);
  for (const token of [
    TOKEN.slice(0, -1),
    TOKEN.replace(ID, OTHER),
    TOKEN.replace("4102444800", "4102444801"),
    TOKEN.replace("4102444800", "1000"),
    "../forged",
  ]) {
    assert.equal(readIdentity(`oof_identity=${token}`, SECRET), null);
  }
  assert.equal(
    readIdentity(`oof_identity=${TOKEN}; oof_identity=${TOKEN}`, SECRET),
    null,
  );
  assert.equal(
    readIdentity(`oof_identity=${TOKEN}`, "a different signing secret"),
    null,
  );
  assert.equal(readIdentity(null, SECRET), null);
  t.mock.method(Date, "now", () => 4102444800000);
  assert.equal(readIdentity(`oof_identity=${TOKEN}`, SECRET), null);
});

test("only the signed identity and proxy credential reach the private backend", async () => {
  let calls = 0;
  const fetchBackend: typeof fetch = async (url, options) => {
    calls++;
    assert.equal(String(url), `http://backend:2026/threads/${ID}/state`);
    assert.equal(options?.method, "GET");
    assert.equal(options?.cache, "no-store");
    assert.equal(options?.redirect, "error");
    const headers = new Headers(options?.headers);
    assert.deepEqual(Object.fromEntries(headers), {
      "x-demo-identity": ID,
      "x-demo-key": SECRET,
    });
    return Response.json(
      {
        values: {
          messages: [
            {
              type: "ai",
              id: "question",
              content: "Where do you travel?",
              metadata: MARKER,
            },
          ],
          sources: MARKER,
          report: MARKER,
        },
      },
      {
        headers: {
          "Set-Cookie": `secret=${MARKER}`,
          "Access-Control-Allow-Origin": "*",
          "X-Internal": MARKER,
        },
      },
    );
  };
  const response = await readProxy(
    request(`threads/${ID}/state`, {
      "x-demo-identity": OTHER,
      "x-demo-key": MARKER,
      "x-forwarded-for": "1.2.3.4",
      authorization: MARKER,
    }),
    ["threads", ID, "state"],
    CONFIG,
    fetchBackend,
  );
  assert.equal(calls, 1);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  for (const key of ["set-cookie", "access-control-allow-origin", "x-internal"])
    assert.equal(response.headers.get(key), null);
  const body = await response.text();
  assert.ok(body.includes("Where do you travel?"));
  assert.ok(!body.includes(MARKER));
});

test("unknown routes, queries, methods, origins and identities never reach Aegra", async () => {
  const fetchBackend: typeof fetch = async () => {
    throw new Error("must not be called");
  };
  const cases = [
    [request("threads"), ["threads"], 403],
    [request(`threads/${ID}/history`), ["threads", ID, "history"], 403],
    [
      request(`threads/${ID}/runs/${OTHER}/stream`),
      ["threads", ID, "runs", OTHER, "stream"],
      403,
    ],
    [request("limits?checkpoint_id=anything"), ["limits"], 403],
    [
      request("limits", { origin: "https://attacker.example" }),
      ["limits"],
      403,
    ],
    [request("limits", { origin: "null" }), ["limits"], 403],
    [request("limits", { "sec-fetch-site": "cross-site" }), ["limits"], 403],
    [
      request("session", { cookie: `oof_identity=${TOKEN.slice(0, -1)}` }),
      ["session"],
      401,
    ],
    [
      request(`threads/${ID}`, { cookie: "", "x-demo-identity": ID }),
      ["threads", ID],
      401,
    ],
    [request("chat", {}, "POST"), ["chat"], 405],
  ] as const;
  for (const [req, path, status] of cases) {
    const response = await readProxy(req, [...path], CONFIG, fetchBackend);
    assert.equal(response.status, status);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
  }
  assert.equal(disabledRoute().status, 405);
});

test("cookie-free session reads create no identity and limits need no visitor cookie", async () => {
  const noFetch: typeof fetch = async () => {
    throw new Error("must not be called");
  };
  const empty = await readProxy(
    request("session", { cookie: "" }),
    ["session"],
    CONFIG,
    noFetch,
  );
  assert.deepEqual(await empty.json(), { thread_id: null });
  assert.equal(empty.headers.get("set-cookie"), null);
  const fetchBackend: typeof fetch = async (url, options) => {
    assert.equal(String(url), "http://backend:2026/demo/limits");
    assert.deepEqual(Object.fromEntries(new Headers(options?.headers)), {
      "x-demo-key": SECRET,
    });
    return Response.json({ daily_chats: 5, internal: MARKER });
  };
  const limits = await readProxy(
    request("limits", { cookie: "" }),
    ["limits"],
    CONFIG,
    fetchBackend,
  );
  assert.deepEqual(await limits.json(), { daily_chats: 5 });
  assert.equal(limits.headers.get("set-cookie"), null);
});

test("backend ownership refusals are preserved and raw errors stay private", async () => {
  for (const [status, expected] of [
    [404, 404],
    [401, 502],
    [500, 502],
    [302, 502],
  ]) {
    const fetchBackend: typeof fetch = async () =>
      new Response(MARKER, { status });
    const response = await readProxy(
      request(`threads/${OTHER}`),
      ["threads", OTHER],
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, expected);
    assert.ok(!(await response.text()).includes(MARKER));
  }
  for (const fetchBackend of [
    async () => {
      throw new Error(MARKER);
    },
    async () => new Response(MARKER),
  ]) {
    const response = await readProxy(
      request("session"),
      ["session"],
      CONFIG,
      fetchBackend,
    );
    assert.equal(response.status, 503);
    assert.ok(!(await response.text()).includes(MARKER));
  }
});

test("server configuration rejects missing settings and ambiguous URLs", () => {
  const env = {
    OUT_OF_FRAME_DEMO_ORIGIN: CONFIG.origin,
    OUT_OF_FRAME_DEMO_BACKEND_URL: CONFIG.backend.href,
    OUT_OF_FRAME_DEMO_PROXY_SECRET: SECRET,
  };
  assert.equal(proxyConfig(env).origin, CONFIG.origin);
  for (const value of [
    "",
    "file:///tmp/private",
    "https://user:password@example.com",
    "https://example.com/api",
    "https://example.com/?key=value",
  ]) {
    assert.throws(() =>
      proxyConfig({ ...env, OUT_OF_FRAME_DEMO_BACKEND_URL: value }),
    );
  }
  assert.throws(() =>
    proxyConfig({ ...env, OUT_OF_FRAME_DEMO_PROXY_SECRET: "short" }),
  );
  assert.throws(() => proxyConfig({}));
});
