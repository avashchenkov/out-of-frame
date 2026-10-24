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
            <MarkdownText>{message.content}</MarkdownText>
          )}
        </article>
      ))}
    </section>
  );
}
