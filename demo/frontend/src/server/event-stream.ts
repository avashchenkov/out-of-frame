import { createParser } from "eventsource-parser";
import { visibleEvent } from "./visible-response.ts";

const ENCODER = new TextEncoder();
const ERROR_EVENT = 'event: error\ndata: {"error":"stream_unavailable"}\n\n';
// Aegra values include private source texts before projection.
const MAX_EVENT_CHARS = 16 * 1024 * 1024;

export function validEventId(id: string, runId: string) {
  const prefix = `${runId}_event_`;
  return id.startsWith(prefix) && /^[0-9]{1,16}$/.test(id.slice(prefix.length));
}

export function eventStream(
  body: ReadableStream<Uint8Array>,
  runId: string,
  expires: number,
  signal: AbortSignal,
  disconnect: () => void,
) {
  const reader = body.getReader();
  const inaccessible = () => signal.aborted || Date.now() >= expires * 1000;
  const abort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener("abort", abort, { once: true });

  async function* events() {
    const decoder = new TextDecoder();
    let output: string[] = [];
    let ended = false;
    const parser = createParser({
      maxBufferSize: MAX_EVENT_CHARS,
      onEvent(message) {
        if (ended || inaccessible()) return;
        const event = message.event ?? "message";
        if (!["values", "updates", "metadata", "error", "end"].includes(event))
          return;
        const data = event === "error" ? {} : JSON.parse(message.data);
        const visible = visibleEvent(event, data);
        if (visible === null) return;
        const id =
          message.id && validEventId(message.id, runId)
            ? `id: ${message.id}\n`
            : "";
        output.push(
          `${id}event: ${event}\ndata: ${JSON.stringify(visible)}\n\n`,
        );
        if (event === "end") ended = true;
      },
      onComment() {
        if (!ended && !inaccessible()) output.push(": keepalive\n\n");
      },
      onError(error) {
        if (error.type === "max-buffer-size-exceeded")
          throw new Error("invalid_stream");
      },
    });
    try {
      while (!ended && !inaccessible()) {
        const chunk = await reader.read();
        if (chunk.done) break;
        parser.feed(decoder.decode(chunk.value, { stream: true }));
        for (const frame of output) {
          if (inaccessible()) return;
          yield ENCODER.encode(frame);
        }
        output = [];
      }
      if (!ended && !inaccessible()) yield ENCODER.encode(ERROR_EVENT);
    } catch {
      if (!inaccessible()) yield ENCODER.encode(ERROR_EVENT);
    } finally {
      signal.removeEventListener("abort", abort);
      disconnect();
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  }

  const iterator = events();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const result = await iterator.next();
      if (result.done) controller.close();
      else controller.enqueue(result.value);
    },
    async cancel() {
      signal.removeEventListener("abort", abort);
      disconnect();
      await reader.cancel().catch(() => undefined);
      await iterator.return();
    },
  });
}
