"use client";

import { useEffect, useRef, useState } from "react";
import { Thread } from "./thread";
import type { PrivateChat as Chat } from "../lib/private-chat";
import { watchPrivateChat } from "../lib/watch-private-chat";
import { ChatInput } from "./chat-input";
import { ChatSubmitError, readDemoLimits, submitChat } from "../lib/chat-input";
import type { DemoLimits } from "../lib/chat-input";

export function PrivateChat({
  liveEnabled,
  contactEmail,
}: {
  liveEnabled: boolean;
  contactEmail?: string;
}) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [notice, setNotice] = useState("Loading your private chat…");
  const [reload, setReload] = useState(0);
  const [limits, setLimits] = useState<DemoLimits | null>(null);
  const [limitsFailed, setLimitsFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<ChatSubmitError | null>(null);
  const [dailyReset, setDailyReset] = useState<string | null>(null);
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
    if (
      !liveEnabled ||
      !limits ||
      !chat ||
      submission.current ||
      locked ||
      chat.active
    )
      return false;
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
    const controller = new AbortController();
    submission.current = controller;
    setBusy(true);
    setError(null);
    setDailyReset(null);
    try {
      await submitChat(
        retry ? "retry" : chat.threadId ? "answer" : "new",
        text,
        chat.threadId,
        controller.signal,
      );
      if (controller.signal.aborted) return false;
      setChat(null);
      setNotice("Loading your private chat…");
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
      if (failed.code === "daily_chats_exhausted") {
        setDailyReset(
          Date.parse(limits.daily_reset) > Date.now()
            ? new Date(limits.daily_reset).toLocaleString()
            : null,
        );
      }
      return false;
    } finally {
      submission.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  useEffect(() => {
    const watcher = watchPrivateChat((snapshot, status) => {
      setChat(snapshot);
      setNotice(status);
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

  return (
    <Thread
      messages={chat?.messages ?? []}
      notice={busy ? "Submitting your request…" : notice}
      failures={chat?.failures ?? []}
      submissionsRemaining={
        chat ? (chat.submissionsRemaining ?? limits?.submissions) : undefined
      }
      onReload={() => {
        if (submission.current) return;
        setLocked(false);
        setLimitsFailed(false);
        setError(null);
        setChat(null);
        setNotice("Loading your private chat…");
        setReload((value) => value + 1);
      }}
      busy={busy}
    >
      {error && (
        <p role="alert">
          {error.message}
          {error.code === "daily_chats_exhausted" &&
            dailyReset &&
            ` Next reset: ${dailyReset}.`}
        </p>
      )}
      {liveEnabled && limits && chat ? (
        <ChatInput
          chat={chat}
          limits={limits}
          busy={busy}
          locked={locked}
          onSend={send}
          onRetry={() => {
            void send("", true);
          }}
        />
      ) : !liveEnabled || limitsFailed ? (
        <p className="input-note">
          Live chat is currently unavailable.
          {limitsFailed && " Reload chat to try again."}
        </p>
      ) : null}
      {contactEmail && (
        <p className="input-note">
          Questions or feedback?{" "}
          <a href={`mailto:${encodeURIComponent(contactEmail)}`}>
            Contact the author
          </a>
          .
        </p>
      )}
    </Thread>
  );
}
