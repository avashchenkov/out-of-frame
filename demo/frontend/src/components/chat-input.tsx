"use client";

import Link from "next/link";
import { useState } from "react";
import type { PrivateChat } from "../lib/private-chat";
import type { DemoLimits } from "../lib/chat-input";

// Without an identity cookie the visitor still has every chat.
function chatsLeft(chat: PrivateChat, limits: DemoLimits) {
  return chat.chatsRemaining ?? limits.identity_chats;
}

export function ChatInput({
  chat,
  limits,
  busy,
  locked,
  onSend,
  onRetry,
}: {
  chat: PrivateChat;
  limits: DemoLimits;
  busy: boolean;
  locked: boolean;
  onSend: (text: string) => Promise<boolean>;
  onRetry: () => void;
}) {
  const [text, setText] = useState("");
  const length = Array.from(text).length;
  const remaining = chat.threadId
    ? (chat.submissionsRemaining ?? 0)
    : limits.submissions;
  const disabled =
    busy ||
    locked ||
    chat.active ||
    remaining === 0 ||
    (!chat.threadId && chat.chatsRemaining === 0);

  if (chat.canRetry)
    return (
      <button
        type="button"
        className="button button-primary"
        disabled={disabled}
        onClick={onRetry}
      >
        Retry saved run
      </button>
    );
  if (chat.threadId && !chat.canAnswer) return null;

  // A new chat starts with the first message: the box is ready at once, and
  // the short notice below it is the first layer of the terms and Privacy
  // notice.
  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (disabled || !text.trim() || length > limits.message_chars) return;
        // The sent text shows in the conversation; it comes back on failure.
        setText("");
        if (!(await onSend(text))) setText(text);
      }}
    >
      <fieldset className="input-box composer" disabled={disabled}>
        <label htmlFor="message" className="visually-hidden">
          {chat.threadId ? "Your answer" : "Address or listing"}
        </label>
        <textarea
          id="message"
          value={text}
          onChange={(event) => setText(event.target.value)}
          aria-describedby={
            chat.threadId ? "message-limit" : "message-limit start-notice"
          }
          rows={2}
          placeholder={
            chat.threadId
              ? "Type your answer…"
              : "Enter a Berlin address or paste a listing…"
          }
        />
        <div className="box-footer">
          <p id="message-limit" className="box-meta">
            {length} / {limits.message_chars.toLocaleString("en-US")}
          </p>
          <button
            type="submit"
            className="button button-primary"
            disabled={!text.trim() || length > limits.message_chars}
          >
            {chat.threadId
              ? "Send"
              : `Start chat (${chatsLeft(chat, limits)} left)`}
          </button>
        </div>
      </fieldset>
      {!chat.threadId && (
        <p id="start-notice" className="start-notice">
          AI demo for adults. Avoid personal details. Starting a chat accepts
          the <Link href="/terms">service terms</Link>; the{" "}
          <Link href="/privacy">Privacy notice</Link> explains how Anthropic and
          others process your messages. AI can be wrong: check the sources.
        </p>
      )}
    </form>
  );
}
