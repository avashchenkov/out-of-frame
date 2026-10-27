type RunConnection = Pick<
  EventTarget,
  "addEventListener" | "removeEventListener"
> & {
  close: () => void;
  readonly readyState: number;
};
type Handlers = {
  progress: (notice: string | null) => void;
  refresh: (reattach?: boolean) => void;
};

const PROGRESS = new Set([
  "get_map_objects",
  "get_plans",
  "plan_journeys",
  "triage_objects",
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
    handlers.progress(failed ? null : "Connection lost. Reconnecting…");
    handlers.refresh(reattach);
  });
  return close;
}
