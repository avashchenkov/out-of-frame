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

const PROGRESS: Record<string, string> = {
  get_map_objects: "Fetched the map.",
  get_plans: "Fetched the development plans.",
  plan_journeys: "Planned the journeys.",
  triage_objects: "Checked the objects that the map makes clear.",
  investigate_object: "Investigated an object on the web.",
  write_report: "Wrote the report.",
};

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
  listen("updates", (event) => {
    try {
      for (const node of Object.keys(JSON.parse(event.data))) {
        if (Object.hasOwn(PROGRESS, node)) handlers.progress(PROGRESS[node]);
      }
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
