type RunConnection = Pick<
  EventTarget,
  "addEventListener" | "removeEventListener"
> & {
  close: () => void;
  readonly readyState: number;
};
type Handlers = {
  progress: (notice: string | null) => void;
  refresh: (reattach?: boolean, delayMs?: number) => void;
  // The investigations that ended in this run, counted from its events.
  research: (done: number) => void;
};

const PROGRESS = new Set([
  "extract_input",
  "detect_language",
  "geocode_input",
  "get_map_objects",
  "get_plans",
  "plan_journeys",
  "triage_objects",
  "get_addresses",
  "investigate_object",
  "write_report",
]);

export function followRun(
  threadId: string,
  runId: string,
  expiresAt: string,
  handlers: Handlers,
  connect: (url: string) => RunConnection = (url) => new EventSource(url),
): () => void {
  if (!(Date.parse(expiresAt) > Date.now())) {
    handlers.refresh();
    return () => {};
  }
  const connection = connect(
    `/api/demo/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/stream`,
  );
  let closed = false;
  const listeners = new Map<string, EventListener>();
  let researched = 0;
  function close() {
    if (closed) return;
    closed = true;
    for (const [type, listener] of listeners)
      connection.removeEventListener(type, listener);
    connection.close();
  }
  function listen(type: string, handler: (event: MessageEvent) => void) {
    const listener: EventListener = (event) => {
      if (closed) return;
      if (Date.parse(expiresAt) <= Date.now()) {
        close();
        handlers.refresh();
        return;
      }
      handler(event as MessageEvent);
    };
    listeners.set(type, listener);
    connection.addEventListener(type, listener);
  }
  listen("open", () => handlers.progress(null));
  // The state names the current step and counts the research, so a finished
  // step only asks for a fresh read.
  listen("updates", (event) => {
    try {
      const nodes = Object.keys(JSON.parse(event.data));
      if (nodes.includes("investigate_object")) handlers.research(++researched);
      if (nodes.some((node) => PROGRESS.has(node))) handlers.refresh();
    } catch {
      handlers.refresh();
    }
  });
  // Replayed values may be older than the loaded snapshot. Read current state instead.
  listen("values", () => handlers.refresh());
  listen("end", () => {
    close();
    handlers.progress(null);
    handlers.refresh();
  });
  listen("error", (event) => {
    let failed = false;
    try {
      failed = JSON.parse(event.data).error === "run_failed";
    } catch {
      // Native connection errors have no event data.
    }
    const reattach = !failed && connection.readyState === 2;
    if (failed || reattach) close();
    handlers.progress(
      failed
        ? null
        : reattach
          ? "Live updates are temporarily unavailable. Retrying shortly."
          : "Connection lost. Reconnecting…",
    );
    // EventSource cannot expose an HTTP 429 or Retry-After. A refused stream
    // is CLOSED: wait five seconds before asking the watcher to attach again.
    handlers.refresh(reattach, reattach ? 5000 : undefined);
  });
  return close;
}
