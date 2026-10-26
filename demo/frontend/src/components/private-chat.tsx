"use client";

import { useEffect, useRef, useState } from "react";
import { Thread } from "./thread";
import type { PrivateChat as Chat } from "../lib/private-chat";
import { watchPrivateChat } from "../lib/watch-private-chat";
import { ChatInput, StartNotice } from "./chat-input";
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
  const [reload, setReload] = useState(0);
  const [limits, setLimits] = useState<DemoLimits | null>(null);
  const [limitsFailed, setLimitsFailed] = useState(false);
  const [operation, setOperation] = useState<"submit" | "delete" | null>(null);
  const busy = operation !== null;
  const [replaceFor, setReplaceFor] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const replacement = !!chat?.threadId && replaceFor === chat.threadId;
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
    if (!liveEnabled || !limits || !chat || submission.current || locked)
      return false;
    if (replacement) {
      if (!(chat.chatsRemaining && chat.chatsRemaining > 0)) return false;
    } else {
      if (chat.active) return false;
      if (
        chat.threadId &&
        (!(retry ? chat.canRetry : chat.canAnswer) ||
          !chat.submissionsRemaining)
      )
        return false;
    }
    if (
      !retry &&
      (!text.trim() || Array.from(text).length > limits.message_chars)
    )
      return false;
    return performChange((signal) =>
      submitChat(
        replacement
          ? "replace"
          : retry
            ? "retry"
            : chat.threadId
              ? "answer"
              : "new",
        text,
        chat.threadId,
        signal,
      ),
    );
  }

  async function remove() {
    if (!chat || (!chat.threadId && !chat.deleting)) return;
    setConfirmDelete(false);
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
      setReplaceFor(null);
      setConfirmDelete(false);
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
        setReplaceFor(null);
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
      messages={replacement ? [] : (chat?.messages ?? [])}
      notice={
        operation === "delete"
          ? "Deleting your chat…"
          : busy
            ? "Submitting your request…"
            : notice
      }
      quiet={!!chat && !chat.threadId && !chat.deleting && !busy}
      failures={replacement ? [] : (chat?.failures ?? [])}
      intro={
        liveEnabled &&
        limits &&
        chat &&
        (!chat.threadId || replacement) && (
          <>
            {replacement && (
              <section
                aria-label="New chat replaces the current chat"
                className="confirm-box"
              >
                <p>
                  Sending the first message of the new chat deletes the current
                  chat and report and stops any running work. A limit refusal
                  keeps the current chat.
                </p>
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={busy}
                  onClick={() => setReplaceFor(null)}
                >
                  Cancel new chat
                </button>
              </section>
            )}
            <StartNotice limits={limits} />
          </>
        )
      }
      submissionsRemaining={
        chat?.threadId && !replacement
          ? chat.submissionsRemaining
          : chat && !chat.deleting && chat.chatsRemaining !== 0
            ? limits?.submissions
            : undefined
      }
      onReload={() => {
        if (submission.current) return;
        setReplaceFor(null);
        setConfirmDelete(false);
        setLocked(false);
        setLimitsFailed(false);
        setError(null);
        setChat(null);
        setNotice("Loading your chat…");
        setReload((value) => value + 1);
      }}
      busy={busy}
      actions={
        chat &&
        (chat.threadId || chat.deleting) && (
          <div className="chat-actions">
            <button
              type="button"
              className="button button-secondary button-small"
              disabled={
                busy ||
                locked ||
                !liveEnabled ||
                chat.deleting ||
                !chat.chatsRemaining
              }
              onClick={() => {
                setConfirmDelete(false);
                setReplaceFor(chat.threadId);
              }}
            >
              New chat
            </button>
            <button
              type="button"
              className="button button-secondary button-small"
              disabled={busy}
              onClick={() => setConfirmDelete(true)}
            >
              Delete chat
            </button>
          </div>
        )
      }
    >
      {confirmDelete && chat && (chat.threadId || chat.deleting) && (
        <section aria-label="Confirm chat deletion" className="confirm-box">
          <p>
            Delete this browser&apos;s current chat and report? Running work
            will stop. This cannot be undone. Usage limits and the access cookie
            remain.
          </p>
          <div className="confirm-actions">
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={() => {
                void remove();
              }}
            >
              Confirm delete
            </button>
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => setConfirmDelete(false)}
            >
              Cancel
            </button>
          </div>
        </section>
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
          key={replacement ? "replacement" : (chat.threadId ?? "new")}
          chat={
            replacement
              ? {
                  ...chat,
                  threadId: null,
                  active: false,
                  canRetry: false,
                  canAnswer: false,
                  submissionsRemaining: undefined,
                }
              : chat
          }
          limits={limits}
          busy={busy || confirmDelete}
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
