import {
  ChatReadError,
  readPrivateChat,
  researchStatus,
} from "./private-chat.ts";
import type { PrivateChat } from "./private-chat.ts";
import { followRun } from "./run-events.ts";

export function watchPrivateChat(
  change: (chat: PrivateChat | null, notice: string) => void,
  { read = readPrivateChat, follow = followRun } = {},
) {
  let request: AbortController | undefined;
  // A refresh during a read waits for it and then reads once more. Cancelling
  // the read instead would starve the page while steps end faster than a read.
  let reading = false;
  let again = false;
  let refreshTimer: ReturnType<typeof setTimeout>;
  let expiryTimer: ReturnType<typeof setTimeout>;
  let disposed = false;
  let streamKey: string | undefined;
  let stopStream: (() => void) | undefined;
  let progress: string | null = null;
  let current: PrivateChat | null = null;
  let status = "Loading your chat…";
  // The investigations that the run's events report as ended. The saved state
  // shows them only once the last ones start, so the page counts them itself.
  let researched = 0;

  function counted(snapshot: PrivateChat): PrivateChat {
    const research = snapshot.research;
    if (!research || researched <= research.done) return snapshot;
    const done = Math.min(researched, research.total);
    return { ...snapshot, status: researchStatus({ ...research, done }) };
  }

  function schedule(delay: number) {
    if (disposed) return;
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, delay);
  }

  function watch(snapshot: PrivateChat) {
    const key =
      snapshot.active &&
      snapshot.runId &&
      snapshot.threadId &&
      snapshot.expiresAt
        ? `${snapshot.threadId}/${snapshot.runId}`
        : undefined;
    if (key === streamKey) return;
    stopStream?.();
    streamKey = key;
    progress = null;
    researched = 0;
    if (key) {
      stopStream = follow(
        snapshot.threadId!,
        snapshot.runId!,
        snapshot.expiresAt!,
        {
          refresh(reattach) {
            if (reattach) streamKey = undefined;
            schedule(100);
          },
          progress(notice) {
            if (disposed) return;
            progress = notice;
            change(current, notice ?? status);
          },
          research(done) {
            if (disposed) return;
            researched = done;
            if (!current?.research) return;
            current = counted(current);
            status = current.status;
            change(current, progress ?? status);
          },
        },
      );
    }
  }

  async function refresh() {
    if (disposed) return;
    clearTimeout(refreshTimer);
    if (reading) {
      again = true;
      return;
    }
    reading = true;
    const connection = new AbortController();
    request = connection;
    try {
      const snapshot = await read(connection.signal);
      if (connection.signal.aborted || disposed) return;
      clearTimeout(expiryTimer);
      watch(snapshot);
      current = counted(snapshot);
      status = current.status;
      change(current, progress ?? status);
      clearTimeout(refreshTimer);
      if (snapshot.active) schedule(3000);
      if (snapshot.expiresAt) {
        const expiry = Date.parse(snapshot.expiresAt);
        expiryTimer = setTimeout(
          () => {
            if (expiry <= Date.now()) {
              current = null;
              change(null, "This chat is no longer available in this browser.");
            }
            void refresh();
          },
          Math.min(expiry - Date.now(), 2_147_483_647),
        );
      }
    } catch (error) {
      if (connection.signal.aborted || disposed) return;
      clearTimeout(expiryTimer);
      current = null;
      progress = null;
      change(
        null,
        error instanceof ChatReadError
          ? error.message
          : "The chat could not be loaded. Please try again.",
      );
      if (error instanceof ChatReadError && error.inaccessible) {
        stopStream?.();
        streamKey = undefined;
        clearTimeout(refreshTimer);
      } else {
        schedule(3000);
      }
    } finally {
      reading = false;
      if (again && !disposed) {
        again = false;
        void refresh();
      }
    }
  }

  void refresh();
  return {
    refresh,
    stop() {
      disposed = true;
      request?.abort();
      stopStream?.();
      clearTimeout(refreshTimer);
      clearTimeout(expiryTimer);
    },
  };
}
