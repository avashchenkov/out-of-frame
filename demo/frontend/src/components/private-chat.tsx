"use client";

import { useEffect, useRef, useState } from "react";
import { Thread } from "./thread";
import type { ChatMessage, PrivateChat as Chat } from "../lib/private-chat";
import { watchPrivateChat } from "../lib/watch-private-chat";
import { ChatInput } from "./chat-input";
import { ConfirmDialog } from "./confirm-dialog";
import {
  ChatSubmitError,
  IDENTITY_LIMIT_NOTICE,
  deleteChat,
  readDemoLimits,
  submitChat,
} from "../lib/chat-input";
import type { DemoLimits } from "../lib/chat-input";

export function PrivateChat({
  liveEnabled,
  contactEmail,
}: {
  liveEnabled: boolean;
  contactEmail?: string;
}) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [notice, setNotice] = useState("Loading your chat…");
  // A chat usually loads at once. The loading notice shows only after a
  // second, so that it does not flash on every visit.
  const [loading, setLoading] = useState(true);
  const [slow, setSlow] = useState(false);
  const [reload, setReload] = useState(0);
  const [limits, setLimits] = useState<DemoLimits | null>(null);
  const [limitsFailed, setLimitsFailed] = useState(false);
  const [operation, setOperation] = useState<"submit" | "delete" | null>(null);
  const busy = operation !== null;
  const [confirm, setConfirm] = useState<"new" | "delete" | null>(null);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<ChatSubmitError | null>(null);
  const [dailyReset, setDailyReset] = useState<string | null>(null);
  // The first message of a new chat shows at once, until the chat holds it.
  const [sent, setSent] = useState<string | null>(null);
  const submission = useRef<AbortController | null>(null);

  useEffect(() => () => submission.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    readDemoLimits(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setLimits(value);
          setLimitsFailed(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setLimits(null);
          setLimitsFailed(true);
        }
      });
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (error?.code !== "daily_chats_exhausted") return;
    const controller = new AbortController();
    readDemoLimits(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setLimits(value);
        setDailyReset(new Date(value.daily_reset).toLocaleString());
      })
      .catch(() => {});
    return () => controller.abort();
  }, [error]);

  async function send(text: string, retry = false): Promise<boolean> {
    if (!liveEnabled || !limits || !chat || submission.current || locked)
      return false;
    if (chat.active) return false;
    if (
      chat.threadId &&
      (!(retry ? chat.canRetry : chat.canAnswer) || !chat.submissionsRemaining)
    )
      return false;
    if (
      !retry &&
      (!text.trim() || Array.from(text).length > limits.message_chars)
    )
      return false;
    if (!chat.threadId && !retry) setSent(text);
    const done = await performChange((signal) =>
      submitChat(
        retry ? "retry" : chat.threadId ? "answer" : "new",
        text,
        chat.threadId,
        signal,
      ),
    );
    if (!done) setSent(null);
    return done;
  }

  async function remove() {
    if (!chat || (!chat.threadId && !chat.deleting)) return;
    setConfirm(null);
    setSent(null);
    await performChange((signal) => deleteChat(signal), true);
  }

  async function performChange(
    action: (signal: AbortSignal) => Promise<unknown>,
    deleting = false,
  ): Promise<boolean> {
    if (submission.current) return false;
    const controller = new AbortController();
    submission.current = controller;
    setOperation(deleting ? "delete" : "submit");
    setError(null);
    setDailyReset(null);
    try {
      await action(controller.signal);
      if (controller.signal.aborted) return false;
      setLocked(false);
      setConfirm(null);
      setChat(null);
      setNotice("Loading your chat…");
      setReload((value) => value + 1);
      return true;
    } catch (failure) {
      if (controller.signal.aborted) return false;
      const failed =
        failure instanceof ChatSubmitError
          ? failure
          : new ChatSubmitError(undefined, true);
      setError(failed);
      setLocked(failed.uncertain);
      if (failed.code === "daily_chats_exhausted" && limits) {
        setDailyReset(
          Date.parse(limits.daily_reset) > Date.now()
            ? new Date(limits.daily_reset).toLocaleString()
            : null,
        );
      }
      if (failed.code === "deletion_pending") {
        setChat(null);
        setReload((value) => value + 1);
      }
      return false;
    } finally {
      submission.current = null;
      if (!controller.signal.aborted) setOperation(null);
    }
  }

  useEffect(() => {
    const watcher = watchPrivateChat((snapshot, status) => {
      setChat(snapshot);
      setNotice(status);
      setLoading(false);
    });
    function visible() {
      if (document.visibilityState === "visible") void watcher.refresh();
    }
    window.addEventListener("focus", watcher.refresh);
    document.addEventListener("visibilitychange", visible);
    return () => {
      watcher.stop();
      window.removeEventListener("focus", watcher.refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [reload]);

  useEffect(() => {
    if (!loading) return;
    const timer = setTimeout(() => setSlow(true), 1000);
    return () => {
      clearTimeout(timer);
      setSlow(false);
    };
  }, [loading]);

  const messages = chat?.messages ?? [];
  const pending =
    sent !== null &&
    messages.length === 0 &&
    (operation === "submit" || !chat || !!chat.threadId);
  const shown: ChatMessage[] = pending
    ? [{ id: "sent", type: "human", content: sent }]
    : messages;
  const started = !!chat && (!!chat.threadId || !!chat.deleting);
  // Without an input box, the chat actions sit in a card of their own, with a
  // hint about what comes next.
  const ended = !!chat?.threadId && !chat.canAnswer && !chat.canRetry;
  const hint = !ended
    ? null
    : chat.active && !chat.deleting
      ? "You can close this page. The check keeps running."
      : chat.messages.some((message) => message.id.startsWith("final-report"))
        ? "To check another address, start a new chat."
        : null;
  const working =
    operation !== "delete" && !chat?.deleting && (pending || !!chat?.active)
      ? busy
        ? "Working…"
        : notice
      : null;

  const contact = contactEmail && (
    <>
      {" "}
      <a href={`mailto:${encodeURIComponent(contactEmail)}`}>
        Contact the author
      </a>
    </>
  );

  return (
    <Thread
      messages={shown}
      welcome={shown.length === 0 && !started}
      working={working}
      notice={
        operation === "delete"
          ? "Deleting your chat…"
          : busy
            ? "Submitting your request…"
            : notice
      }
      quiet={
        working !== null ||
        (loading && !slow) ||
        (!!chat && !chat.threadId && !chat.deleting && !busy)
      }
      reloadable={!chat || limitsFailed || !!error || notice !== chat.status}
      failures={chat?.failures ?? []}
      submissionsRemaining={
        chat?.threadId
          ? chat.canAnswer
            ? chat.submissionsRemaining
            : undefined
          : chat && !chat.deleting && chat.chatsRemaining !== 0
            ? limits?.submissions
            : undefined
      }
      onReload={() => {
        if (submission.current) return;
        setConfirm(null);
        setLocked(false);
        setLimitsFailed(false);
        setError(null);
        setChat(null);
        setNotice("Loading your chat…");
        setLoading(true);
        setReload((value) => value + 1);
      }}
      busy={busy}
      actions={
        chat &&
        (chat.threadId || chat.deleting) && (
          <div className={ended ? "chat-actions chat-end" : "chat-actions"}>
            {hint && <p>{hint}</p>}
            <div className="chat-buttons">
              <button
                type="button"
                className="button button-secondary button-small"
                // New chat deletes the current chat first, so like Delete chat it
                // works after an uncertain request too.
                disabled={
                  busy || !liveEnabled || chat.deleting || !chat.chatsRemaining
                }
                onClick={() => setConfirm("new")}
              >
                New chat
              </button>
              <button
                type="button"
                className="button button-secondary button-small button-delete"
                disabled={busy}
                onClick={() => setConfirm("delete")}
              >
                Delete chat
              </button>
            </div>
          </div>
        )
      }
    >
      {confirm === "new" && chat?.threadId && (
        <ConfirmDialog
          title="Start a new chat?"
          confirmLabel="Start new chat"
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            void remove();
          }}
        >
          <p>
            This deletes the current chat and its report, and any running check
            stops. You cannot open them again.
          </p>
        </ConfirmDialog>
      )}
      {confirm === "delete" && chat && (chat.threadId || chat.deleting) && (
        <ConfirmDialog
          title="Delete this chat?"
          confirmLabel="Delete chat"
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            void remove();
          }}
        >
          <p>
            The chat and its report will be deleted, and any running check
            stops. You cannot open them again. Usage limits and the access
            cookie remain.
          </p>
        </ConfirmDialog>
      )}
      {chat && !chat.threadId && chat.chatsRemaining === 0 && (
        <p role="status" className="callout">
          {IDENTITY_LIMIT_NOTICE}
          {contact}
        </p>
      )}
      {error && (
        <p role="alert" className="callout callout-error">
          {error.message}
          {error.code === "daily_chats_exhausted" &&
            dailyReset &&
            ` Next reset: ${dailyReset}.`}
          {error.code === "identity_chats_exhausted" && contact}
        </p>
      )}
      {liveEnabled && limits && chat ? (
        <ChatInput
          key={chat.threadId ?? "new"}
          chat={chat}
          limits={limits}
          busy={busy || confirm !== null}
          locked={locked}
          onSend={send}
          onRetry={() => {
            void send("", true);
          }}
        />
      ) : !liveEnabled || limitsFailed ? (
        <p className="callout">
          Live chat is currently unavailable.
          {limitsFailed && " Reload chat to try again."}
        </p>
      ) : null}
    </Thread>
  );
}
