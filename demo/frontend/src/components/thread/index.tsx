"use client";

import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import { SiteFooter } from "../site-footer";
import { SiteHeader } from "../site-header";
import { ConversationMessages } from "./messages";
import type { ChatMessage } from "../../lib/private-chat";
import type { ReactNode } from "react";

function ScrollToBottom() {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();
  if (isAtBottom) return null;

  return (
    <button className="scroll-to-bottom" onClick={() => scrollToBottom()}>
      Scroll to bottom
    </button>
  );
}

export function Thread({
  messages,
  notice,
  failures,
  submissionsRemaining,
  onReload,
  busy,
  children,
}: {
  messages: ChatMessage[];
  notice: string;
  failures: string[];
  submissionsRemaining?: number;
  onReload: () => void;
  busy: boolean;
  children: ReactNode;
}) {
  return (
    <div className="chat-shell">
      <SiteHeader />

      <main className="chat-main">
        <StickToBottom
          className="conversation"
          initial="instant"
          resize="instant"
        >
          <StickToBottom.Content className="conversation-content">
            {messages.length === 0 ? (
              <section className="welcome" aria-labelledby="welcome-title">
                <p className="eyebrow">Beyond the listing</p>
                <h1 id="welcome-title">See what is outside the frame.</h1>
                <p>
                  Check a Berlin address for nearby sites, planned construction
                  and your regular journeys. Get a report with links to its
                  sources.
                </p>
              </section>
            ) : (
              <ConversationMessages messages={messages} />
            )}
            {failures.length > 0 && (
              <aside aria-label="Unavailable sources">
                {failures.map((failure) => (
                  <p key={failure}>{failure}</p>
                ))}
              </aside>
            )}
          </StickToBottom.Content>
          <ScrollToBottom />
        </StickToBottom>

        <div className="composer-area">
          <p id="chat-availability" role="status">
            {notice}
          </p>
          <button type="button" disabled={busy} onClick={onReload}>
            Reload chat
          </button>
          {submissionsRemaining !== undefined && (
            <p className="report-note">
              Submissions remaining: {submissionsRemaining}
            </p>
          )}
          {children}
          <p className="report-note">
            Reports describe facts. They do not recommend whether to buy or
            rent.
          </p>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
