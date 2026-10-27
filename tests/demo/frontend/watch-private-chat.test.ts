import assert from "node:assert/strict";
import { test } from "node:test";
import { watchPrivateChat } from "../../../demo/frontend/src/lib/watch-private-chat.ts";
import { ChatReadError } from "../../../demo/frontend/src/lib/private-chat.ts";
import type { PrivateChat } from "../../../demo/frontend/src/lib/private-chat.ts";
import type { followRun } from "../../../demo/frontend/src/lib/run-events.ts";

const CHAT: PrivateChat = {
  threadId: "11111111-1111-4111-8111-111111111111",
  runId: "22222222-2222-4222-8222-222222222222",
  messages: [{ id: "question", type: "ai", content: "Saved question" }],
  failures: [],
  status: "Working…",
  active: true,
  expiresAt: "2100-01-01T00:00:00Z",
};

async function settle() {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

test("refused streams wait before reattaching, even after focus or periodic refresh", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 1000 });
  let reads = 0;
  let attachments = 0;
  let handlers!: Parameters<typeof followRun>[3];
  const watcher = watchPrivateChat(() => {}, {
    read: async () => {
      reads++;
      return CHAT;
    },
    follow: (_thread, _run, _expiry, callbacks) => {
      handlers = callbacks;
      attachments++;
      return () => {};
    },
  });
  await settle();
  handlers.refresh(true, 5000);
  await watcher.refresh();
  t.mock.timers.tick(4999);
  await settle();
  assert.equal(reads, 1);
  assert.equal(attachments, 1);
  t.mock.timers.tick(1);
  await settle();
  assert.equal(reads, 2);
  assert.equal(attachments, 2);
  handlers.refresh(true, 5000);
  watcher.stop();
  t.mock.timers.tick(10000);
  await settle();
  assert.equal(reads, 2);
});

test("rate-limited reads pause queued refreshes and release their stream", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 1000 });
  let reads = 0;
  let stops = 0;
  let handlers!: Parameters<typeof followRun>[3];
  const notices: string[] = [];
  const watcher = watchPrivateChat((_chat, notice) => notices.push(notice), {
    read: async () => {
      if (++reads === 2) {
        handlers.refresh();
        throw new ChatReadError(false, 7000);
      }
      return CHAT;
    },
    follow: (_thread, _run, _expiry, callbacks) => {
      handlers = callbacks;
      return () => {
        stops++;
      };
    },
  });
  await settle();
  await watcher.refresh();
  assert.match(notices.at(-1)!, /busy/);
  assert.equal(stops, 1);
  await watcher.refresh();
  t.mock.timers.tick(6999);
  await settle();
  assert.equal(reads, 2);
  t.mock.timers.tick(1);
  await settle();
  assert.equal(reads, 3);
  watcher.stop();
});

test("a disconnect followed by a transient read failure recovers without submission", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let reads = 0;
  let attachments = 0;
  let handlers!: Parameters<typeof followRun>[3];
  const views: (PrivateChat | null)[] = [];
  const watcher = watchPrivateChat((chat) => views.push(chat), {
    read: async () => {
      if (++reads === 2) throw new ChatReadError(false);
      return CHAT;
    },
    follow: (_thread, _run, _expiry, callbacks) => {
      handlers = callbacks;
      attachments++;
      return () => {};
    },
  });
  await settle();
  handlers.refresh(true);
  t.mock.timers.tick(100);
  await settle();
  assert.equal(views.at(-1), null);
  t.mock.timers.tick(3000);
  await settle();
  assert.equal(views.at(-1), CHAT);
  assert.equal(attachments, 2);
  assert.equal(reads, 3);
  watcher.stop();
});

test("lost access clears content, closes the stream and stops retries", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let reads = 0;
  let stops = 0;
  const views: (PrivateChat | null)[] = [];
  const watcher = watchPrivateChat((chat) => views.push(chat), {
    read: async () => {
      if (++reads > 1) throw new ChatReadError(true);
      return CHAT;
    },
    follow: () => () => {
      stops++;
    },
  });
  await settle();
  t.mock.timers.tick(3000);
  await settle();
  assert.equal(views.at(-1), null);
  assert.equal(stops, 1);
  t.mock.timers.tick(10000);
  await settle();
  assert.equal(reads, 2);
  watcher.stop();
});

test("an event during a state read leaves no timer after disposal", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let reads = 0;
  let handlers!: Parameters<typeof followRun>[3];
  let resolve!: (chat: PrivateChat) => void;
  const waiting = new Promise<PrivateChat>((done) => {
    resolve = done;
  });
  const watcher = watchPrivateChat(() => {}, {
    read: async () => (++reads === 1 ? CHAT : waiting),
    follow: (_thread, _run, _expiry, callbacks) => {
      handlers = callbacks;
      return () => {};
    },
  });
  await settle();
  handlers.refresh();
  t.mock.timers.tick(100);
  handlers.refresh();
  resolve(CHAT);
  await settle();
  watcher.stop();
  t.mock.timers.tick(10000);
  await watcher.refresh();
  await settle();
  assert.equal(reads, 2);
});

test("expiry clears the view even while its next read remains pending", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 1000 });
  let reads = 0;
  const views: (PrivateChat | null)[] = [];
  const watcher = watchPrivateChat((chat) => views.push(chat), {
    read: async () =>
      ++reads === 1
        ? { ...CHAT, expiresAt: new Date(1200).toISOString() }
        : new Promise<PrivateChat>(() => {}),
    follow: () => () => {},
  });
  await settle();
  t.mock.timers.tick(200);
  await settle();
  assert.equal(views.at(-1), null);
  watcher.stop();
});

test("events during a state read do not cancel it and lead to one more read", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const second = { ...CHAT, status: "Researching objects on the web: 1 of 3…" };
  const third = { ...CHAT, status: "Researching objects on the web: 2 of 3…" };
  let reads = 0;
  let handlers!: Parameters<typeof followRun>[3];
  let resolve!: (chat: PrivateChat) => void;
  const views: (PrivateChat | null)[] = [];
  const watcher = watchPrivateChat((chat) => views.push(chat), {
    read: async () => {
      reads++;
      if (reads === 1) return CHAT;
      if (reads === 2)
        return new Promise<PrivateChat>((done) => {
          resolve = done;
        });
      return third;
    },
    follow: (_thread, _run, _expiry, callbacks) => {
      handlers = callbacks;
      return () => {};
    },
  });
  await settle();
  // Investigations end faster than a read takes.
  handlers.refresh();
  t.mock.timers.tick(100);
  for (let i = 0; i < 3; i++) {
    handlers.refresh();
    t.mock.timers.tick(100);
  }
  await settle();
  assert.equal(reads, 2);
  resolve(second);
  await settle();
  await settle();
  assert.deepEqual(
    views.slice(1).map((chat) => chat?.status),
    [second.status, third.status],
  );
  assert.equal(reads, 3);
  watcher.stop();
});

test("counted investigations move the research status ahead of the saved state", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const researching = {
    ...CHAT,
    status: "Researching objects on the web: 0 of 3…",
    research: { done: 0, total: 3 },
  };
  let handlers!: Parameters<typeof followRun>[3];
  const views: [PrivateChat | null, string][] = [];
  const watcher = watchPrivateChat(
    (chat, notice) => views.push([chat, notice]),
    {
      read: async () => researching,
      follow: (_thread, _run, _expiry, callbacks) => {
        handlers = callbacks;
        return () => {};
      },
    },
  );
  await settle();
  handlers.research(2);
  const [chat, notice] = views.at(-1)!;
  assert.equal(notice, "Researching objects on the web: 2 of 3…");
  // The chat's own status matches, so the page offers no reload.
  assert.equal(chat?.status, notice);
  handlers.research(5);
  assert.equal(views.at(-1)![1], "Researching objects on the web: 3 of 3…");
  watcher.stop();
});
