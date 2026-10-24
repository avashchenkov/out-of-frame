import assert from "node:assert/strict";
import { test } from "node:test";
import { followRun } from "../../../demo/frontend/src/lib/run-events.ts";

const THREAD = "11111111-1111-4111-8111-111111111111";
const RUN = "22222222-2222-4222-8222-222222222222";
const EXPIRY = "2100-01-01T00:00:00Z";

function fixture(expiresAt = EXPIRY) {
  const source = new EventTarget();
  const transport = Object.assign(source, {
    readyState: 0,
    close: () => {
      closes++;
    },
  });
  let closes = 0;
  let refreshes = 0;
  const urls: string[] = [];
  const notices: (string | null)[] = [];
  const reattachments: boolean[] = [];
  const stop = followRun(
    THREAD,
    RUN,
    expiresAt,
    {
      refresh: (reattach) => {
        refreshes++;
        reattachments.push(!!reattach);
      },
      progress: (notice) => notices.push(notice),
    },
    (url) => {
      urls.push(url);
      return transport;
    },
  );
  return {
    source,
    transport,
    reattachments,
    stop,
    urls,
    notices,
    get closes() {
      return closes;
    },
    get refreshes() {
      return refreshes;
    },
    send(type: string, data: unknown) {
      source.dispatchEvent(
        new MessageEvent(type, { data: JSON.stringify(data) }),
      );
    },
  };
}

test("an existing run uses one native EventSource through connection loss", () => {
  const f = fixture();
  assert.deepEqual(f.urls, [`/api/demo/threads/${THREAD}/runs/${RUN}/stream`]);
  f.source.dispatchEvent(new Event("error"));
  assert.deepEqual(f.notices, ["Connection lost. Reconnecting…"]);
  assert.equal(f.refreshes, 1);
  assert.equal(f.closes, 0);
  f.source.dispatchEvent(new Event("open"));
  assert.equal(f.notices.at(-1), null);
  assert.equal(f.urls.length, 1);
  f.stop();
});

test("progress uses fixed notices; replayed values request current state", () => {
  const f = fixture();
  f.send("updates", {
    get_map_objects: {},
    private_node: "PRIVATE_SOURCE_TEXT",
  });
  assert.deepEqual(f.notices, ["Fetched the map."]);
  f.send("values", { messages: [{ content: "OLD_REPLAYED_QUESTION" }] });
  assert.equal(f.refreshes, 1);
  assert.deepEqual(f.notices, ["Fetched the map."]);
  f.send("updates", { constructor: "PRIVATE_ERROR", unknown: {} });
  assert.equal(f.notices.length, 1);
  f.stop();
});

test("a permanently closed transport requests a new attachment after recovery", () => {
  const f = fixture();
  f.transport.readyState = 2;
  f.source.dispatchEvent(new Event("error"));
  assert.equal(f.closes, 1);
  assert.deepEqual(f.reattachments, [true]);
});

test("end closes only the attachment and delegates completion to a state read", () => {
  const f = fixture();
  f.send("end", { status: "success" });
  assert.equal(f.closes, 1);
  assert.equal(f.refreshes, 1);
  assert.deepEqual(f.notices, [null]);
  f.send("values", {});
  f.send("updates", { write_report: {} });
  f.stop();
  assert.equal(f.closes, 1);
  assert.equal(f.refreshes, 1);
});

test("run errors close the attachment while interrupted streams can reconnect", () => {
  for (const error of ["run_failed", "stream_unavailable"]) {
    const f = fixture();
    f.send("error", { error });
    assert.equal(f.closes, error === "run_failed" ? 1 : 0);
    assert.equal(f.refreshes, 1);
    assert.ok(!JSON.stringify(f.notices).includes(error));
    f.stop();
  }
});

test("expiry and disposal discard all late stream events", (t) => {
  const f = fixture();
  t.mock.method(Date, "now", () => Date.parse(EXPIRY));
  f.send("updates", { write_report: {} });
  assert.equal(f.closes, 1);
  assert.equal(f.refreshes, 1);
  assert.deepEqual(f.notices, []);
  f.send("values", {});
  assert.equal(f.refreshes, 1);
  const expired = fixture();
  assert.deepEqual(expired.urls, []);
  assert.equal(expired.refreshes, 1);
});
