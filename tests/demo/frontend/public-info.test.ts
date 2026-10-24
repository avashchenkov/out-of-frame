import assert from "node:assert/strict";
import { test } from "node:test";
import {
  contactEmail,
  operatorDetails,
  publicLimits,
} from "../../../demo/frontend/src/server/public-info.ts";

const ENV = {
  OUT_OF_FRAME_DEMO_ORIGIN: "https://demo.example.com",
  OUT_OF_FRAME_DEMO_BACKEND_URL: "http://backend:2026",
  OUT_OF_FRAME_DEMO_PROXY_SECRET: "test-proxy-secret-at-least-32-chars",
} as NodeJS.ProcessEnv;
const LIMITS = {
  identity_chats: 2,
  lifetime_days: 30,
  submissions: 7,
  message_chars: 2000,
};

test("operator details come from the environment and reject markup", () => {
  assert.deepEqual(
    operatorDetails({
      OUT_OF_FRAME_DEMO_OPERATOR_NAME: " Ada Example ",
      OUT_OF_FRAME_DEMO_OPERATOR_ADDRESS: "Street 1; ;10115 Berlin;Germany",
      OUT_OF_FRAME_DEMO_CONTACT_EMAIL: "contact@example.com",
      OUT_OF_FRAME_DEMO_HOSTING_PROVIDER: "Example Hosting GmbH",
    } as NodeJS.ProcessEnv),
    {
      name: "Ada Example",
      address: ["Street 1", "10115 Berlin", "Germany"],
      email: "contact@example.com",
      hostingProvider: "Example Hosting GmbH",
    },
  );
  assert.deepEqual(
    operatorDetails({
      OUT_OF_FRAME_DEMO_OPERATOR_NAME: "<script>",
      OUT_OF_FRAME_DEMO_OPERATOR_ADDRESS: "x".repeat(201),
      OUT_OF_FRAME_DEMO_CONTACT_EMAIL: "not an email",
    } as NodeJS.ProcessEnv),
    {
      name: undefined,
      address: [],
      email: undefined,
      hostingProvider: undefined,
    },
  );
  assert.equal(contactEmail({} as NodeJS.ProcessEnv), undefined);
});

test("notice pages read limits with the proxy key and no visitor data", async () => {
  let seen: { url: string; init?: RequestInit } | undefined;
  const limits = await publicLimits(ENV, async (url, init) => {
    seen = { url: String(url), init };
    return Response.json({ ...LIMITS, daily_reset: "2026-10-26T00:00:00" });
  });
  assert.deepEqual(limits, LIMITS);
  assert.equal(seen?.url, "http://backend:2026/demo/limits");
  assert.deepEqual(seen?.init?.headers, {
    "x-demo-key": ENV.OUT_OF_FRAME_DEMO_PROXY_SECRET,
  });
});

test("unavailable or invalid limits fall back to text without numbers", async () => {
  const cases: (typeof fetch)[] = [
    async () => new Response("", { status: 503 }),
    async () => Response.json({ ...LIMITS, submissions: "7" }),
    async () => Response.json({ ...LIMITS, lifetime_days: 0 }),
    async () => {
      throw new Error("offline");
    },
  ];
  for (const fetchBackend of cases)
    assert.equal(await publicLimits(ENV, fetchBackend), null);
  assert.equal(
    await publicLimits({} as NodeJS.ProcessEnv, async () =>
      Response.json(LIMITS),
    ),
    null,
  );
});
