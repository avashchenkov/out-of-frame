"use client";

import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import { BrandMark } from "../brand-mark";
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
  reloadable,
  busy,
  onReload,
}: {
  notice: string;
  quiet: boolean;
  reloadable: boolean;
  busy: boolean;
  onReload: () => void;
}) {
  // The idle notice stays for screen readers only; problems are shown, and
  // only a problem offers a reload.
  return (
    <div className={quiet ? "visually-hidden" : "chat-status"}>
      <p id="chat-availability" role="status">
        {notice}
      </p>
      {!quiet && reloadable && (
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
  welcome,
  working,
  notice,
  quiet,
  reloadable,
  failures,
  submissionsRemaining,
  actions,
  intro,
  onReload,
  busy,
  children,
}: {
  messages: ChatMessage[];
  welcome: boolean;
  working: string | null;
  notice: string;
  quiet: boolean;
  reloadable: boolean;
  failures: string[];
  submissionsRemaining?: number;
  actions?: ReactNode;
  intro?: ReactNode;
  onReload: () => void;
  busy: boolean;
  children: ReactNode;
}) {
  const status = (
    <Status
      notice={notice}
      quiet={quiet}
      reloadable={reloadable}
      busy={busy}
      onReload={onReload}
    />
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

  // Once the chat has messages, its status follows the last of them. The chat
  // actions sit below, with the input box.
  const inline = messages.length > 0;
  const reported = messages.some((message) =>
    message.id.startsWith("final-report"),
  );

  // The chat fills the screen between the header and footer: only the
  // conversation scrolls, and the input box stays below it. Before the first
  // message, the welcome and the input box sit together in the middle.
  return (
    <div className="chat-shell">
      {inline ? null : quiet ? (
        status
      ) : (
        <div className="chat-bar">
          {status}
          {quota}
        </div>
      )}

      <main className={welcome ? "chat-main chat-welcome" : "chat-main"}>
        {messages.length === 0 ? (
          <div className="conversation">
            <div className="conversation-content">
              {welcome && (
                <section className="hero" aria-labelledby="welcome-title">
                  <BrandMark />
                  <h1 id="welcome-title">See what is outside the frame</h1>
                  <p className="lead">
                    The factory next door, the building site to come, your way
                    to work.
                  </p>
                </section>
              )}
              {intro}
              {failureList}
            </div>
          </div>
        ) : (
          <StickToBottom
            className="conversation conversation-stick"
            initial="instant"
            resize="instant"
          >
            <StickToBottom.Content className="conversation-content">
              <ConversationMessages messages={messages} />
              {/* What the agent does now, under the last message as in other
                  AI chats. The status below tells screen readers. */}
              {working && (
                <p className="working" aria-hidden="true">
                  <BrandMark />
                  {working}
                </p>
              )}
              {failureList}
              {quiet ? (
                status
              ) : (
                <div className="chat-status-row">
                  {status}
                  {quota}
                </div>
              )}
              {reported && (
                <p className="meta-note">
                  Reports describe facts. They do not recommend whether to buy
                  or rent.
                </p>
              )}
            </StickToBottom.Content>
            <ScrollToBottom />
          </StickToBottom>
        )}

        <div className="composer-area">
          {children}
          {actions}
        </div>
      </main>
    </div>
  );
}
