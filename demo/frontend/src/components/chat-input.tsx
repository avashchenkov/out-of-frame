"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { PrivateChat } from "../lib/private-chat";
import type { DemoLimits } from "../lib/chat-input";

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
  const [started, setStarted] = useState(false);
  const [text, setText] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);
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

  // After Start, the message box takes the button's place and gets the focus.
  useEffect(() => {
    if (started) field.current?.focus();
  }, [started]);

  if (!chat.threadId && !started)
    return (
      <div className="input-box start-bar">
        <p className="start-placeholder" aria-hidden="true">
          Enter a Berlin address or paste a listing…
        </p>
        <button
          type="button"
          className="button button-primary"
          disabled={disabled}
          onClick={() => setStarted(true)}
        >
          Start chat
        </button>
      </div>
    );

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

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (disabled || !text.trim() || length > limits.message_chars) return;
        if (await onSend(text)) setText("");
      }}
    >
      <fieldset className="input-box composer" disabled={disabled}>
        <label htmlFor="message" className="box-label">
          {chat.threadId ? "Your answer" : "Address or listing"}
        </label>
        <textarea
          id="message"
          ref={field}
          value={text}
          onChange={(event) => setText(event.target.value)}
          aria-describedby="message-limit"
          rows={3}
          placeholder={
            chat.threadId
              ? "Type your answer…"
              : "Enter a Berlin address or paste a listing…"
          }
        />
        <div className="box-footer">
          <p id="message-limit" className="box-meta">
            {length} / {limits.message_chars} characters
            {!chat.threadId && ` · ${remaining} submissions in this chat`}
          </p>
          <button
            type="submit"
            className="button button-primary"
            disabled={!text.trim() || length > limits.message_chars}
          >
            Send
          </button>
        </div>
      </fieldset>
    </form>
  );
}

export function StartNotice({ limits }: { limits: DemoLimits }) {
  return (
    <section className="start-notice" aria-labelledby="start-title">
      <h2 id="start-title" className="box-label">
        Before you start
      </h2>
      <p className="start-limits">
        {limits.submissions} submissions per chat · {limits.message_chars}{" "}
        characters per message
      </p>
      <p>
        An AI demo in English, for users aged 18 or over. Use public places and
        fictional travel plans. Start requests a free AI report under the{" "}
        <Link href="/terms">service terms</Link> and the limits shown here.
        Availability is not guaranteed. Reports give facts, not advice to buy or
        rent.
      </p>
      <p>
        We process your messages, addresses and journey times using Anthropic
        and the services listed in our{" "}
        <Link href="/privacy">Privacy notice</Link>. Other visitors cannot see
        your chat or report.
      </p>
      <p>
        An essential cookie keeps access and allows up to{" "}
        {limits.identity_chats} chats. Access to your current chat ends{" "}
        {limits.lifetime_days} days after your first message, and automatic
        cleanup then deletes it from our server. Starting another chat does not
        extend this period. Clearing cookies loses access but does not delete
        server data. Minimal quota records remain until the cookie expires.
        Provider retention differs. Avoid names and sensitive personal details.
        New chat or Delete chat removes the current chat and report earlier.
      </p>
      <p>AI results can be wrong: check the sources.</p>
    </section>
  );
}
