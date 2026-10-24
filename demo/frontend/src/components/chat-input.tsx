"use client";

import { useState } from "react";
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

  if (!chat.threadId && !started)
    return (
      <section className="start-notice" aria-label="Before your first message">
        <p>
          English-language AI demo for adults. Use public places and fictional
          travel plans. Start requests a free, limited AI report. Availability
          is not guaranteed. Reports give facts, not advice to buy or rent.
          Check the sources.
        </p>
        <p>
          We process your messages, addresses and journey times using Anthropic,
          Nominatim, Overpass, Berlin B-Plan WFS, Transitous and Tavily. Other
          visitors cannot see your chat or report.
        </p>
        <p>
          An essential cookie keeps access and allows up to{" "}
          {limits.identity_chats} chats. We keep your current chat on our server
          for up to {limits.lifetime_days} days after your first message.
          Starting another chat does not extend this period. Clearing cookies
          loses access but does not delete server data. Minimal quota records
          remain until the cookie expires. Provider retention differs. Avoid
          names and sensitive personal details. New chat or Delete chat removes
          the current chat and report earlier.
        </p>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setStarted(true)}
        >
          Start private chat
        </button>
      </section>
    );

  if (chat.canRetry)
    return (
      <button type="button" disabled={disabled} onClick={onRetry}>
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
      <fieldset className="composer" disabled={disabled}>
        <label htmlFor="message">Your message</label>
        <textarea
          id="message"
          value={text}
          onChange={(event) => setText(event.target.value)}
          aria-describedby="message-limit"
          rows={3}
          placeholder="Enter a Berlin address or paste a listing…"
        />
        <button
          type="submit"
          disabled={!text.trim() || length > limits.message_chars}
        >
          Send
        </button>
      </fieldset>
      <p id="message-limit" className="input-note">
        {length} / {limits.message_chars} characters.
      </p>
    </form>
  );
}
