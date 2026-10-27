"use client";

import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import { ConversationMessages } from "./messages";
import type { ChatMessage } from "../../lib/private-chat";
import type { ReactNode } from "react";

function ScrollToBottom() {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();
  if (isAtBottom) return null;

  return (
    <button
      className="button scroll-to-bottom"
      onClick={() => scrollToBottom()}
    >
      Scroll to bottom
    </button>
  );
}

function Status({
  notice,
  quiet,
  busy,
  onReload,
}: {
  notice: string;
  quiet: boolean;
  busy: boolean;
  onReload: () => void;
}) {
  // The idle notice stays for screen readers only; problems are shown.
  return (
    <div className={quiet ? "visually-hidden" : "chat-status"}>
      <p id="chat-availability" role="status">
        {notice}
      </p>
      {!quiet && (
        <button
          type="button"
          className="button button-link"
          disabled={busy}
          onClick={onReload}
        >
          Reload chat
        </button>
      )}
    </div>
  );
}

export function Thread({
  messages,
  notice,
  quiet,
  failures,
  submissionsRemaining,
  actions,
  intro,
  onReload,
  busy,
  children,
}: {
  messages: ChatMessage[];
  notice: string;
  quiet: boolean;
  failures: string[];
  submissionsRemaining?: number;
  actions?: ReactNode;
  intro?: ReactNode;
  onReload: () => void;
  busy: boolean;
  children: ReactNode;
}) {
  const status = (
    <Status notice={notice} quiet={quiet} busy={busy} onReload={onReload} />
  );
  const quota = !quiet && submissionsRemaining !== undefined && (
    <p className="chat-quota">
      {submissionsRemaining}{" "}
      {submissionsRemaining === 1 ? "message" : "messages"} left
    </p>
  );
  const failureList = failures.length > 0 && (
    <aside aria-label="Unavailable sources" className="failures">
      {failures.map((failure) => (
        <p key={failure}>{failure}</p>
      ))}
    </aside>
  );

  // The chat fills the screen between the header and footer: only the
  // conversation scrolls, and the input box stays below it.
  return (
    <div className="chat-shell">
      {quiet && !actions ? (
        status
      ) : (
        <div className="chat-bar">
          {status}
          {quota}
          {actions}
        </div>
      )}

      <main className="chat-main">
        {messages.length === 0 ? (
          <div className="conversation">
            <div className="conversation-content">
              <section className="hero" aria-labelledby="welcome-title">
                <h1 id="welcome-title">See what is outside the frame.</h1>
                <p className="lead">
                  Enter a Berlin address. Find out what is nearby, what will be
                  built and how long your daily trips take.
                </p>
              </section>
              {intro}
              {failureList}
            </div>
          </div>
        ) : (
          <StickToBottom
            className="conversation"
            initial="instant"
            resize="instant"
          >
            <StickToBottom.Content className="conversation-content">
              <ConversationMessages messages={messages} />
              {failureList}
              <p className="meta-note">
                Reports describe facts. They do not recommend whether to buy or
                rent.
              </p>
            </StickToBottom.Content>
            <ScrollToBottom />
          </StickToBottom>
        )}

        <div className="composer-area">{children}</div>
      </main>
    </div>
  );
}
