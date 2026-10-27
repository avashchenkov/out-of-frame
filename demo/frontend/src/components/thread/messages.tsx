import { BrandMark } from "../brand-mark";
import { MarkdownText } from "./markdown-text";
import type { ChatMessage } from "../../lib/private-chat";

export function ConversationMessages({
  messages,
}: {
  messages: ChatMessage[];
}) {
  return (
    <section aria-label="Conversation" className="messages">
      {messages.map((message) => (
        <article
          key={message.id}
          className={`message message-${message.type}`}
          aria-label={
            message.type === "human" ? "User request" : "Out of Frame"
          }
        >
          {message.type === "human" ? (
            <p className="human-text">{message.content}</p>
          ) : (
            <>
              <p className="message-author" aria-hidden="true">
                <BrandMark />
                Out of Frame
              </p>
              <MarkdownText>{message.content}</MarkdownText>
            </>
          )}
        </article>
      ))}
    </section>
  );
}
