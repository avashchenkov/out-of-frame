"use client";

import { useEffect, useState } from "react";
import { Thread } from "./thread";
import { ChatReadError, readPrivateChat } from "../lib/private-chat";
import type { PrivateChat as Chat } from "../lib/private-chat";

export function PrivateChat() {
  const [chat, setChat] = useState<Chat | null>(null);
  const [notice, setNotice] = useState("Loading your private chat…");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let request: AbortController | undefined;
    let refreshTimer: ReturnType<typeof setTimeout>;
    let expiryTimer: ReturnType<typeof setTimeout>;
    let disposed = false;

    async function refresh() {
      clearTimeout(refreshTimer);
      request?.abort();
      const connection = new AbortController();
      request = connection;
      try {
        const snapshot = await readPrivateChat(connection.signal);
        if (connection.signal.aborted || disposed) return;
        clearTimeout(expiryTimer);
        setChat(snapshot);
        setNotice(snapshot.status);
        if (snapshot.active) refreshTimer = setTimeout(refresh, 3000);
        if (snapshot.expiresAt) {
          expiryTimer = setTimeout(
            () => {
              if (Date.parse(snapshot.expiresAt!) <= Date.now()) {
                setChat(null);
                setNotice("This chat is no longer available in this browser.");
              }
              void refresh();
            },
            Math.min(
              Date.parse(snapshot.expiresAt) - Date.now(),
              2_147_483_647,
            ),
          );
        }
      } catch (error) {
        if (connection.signal.aborted || disposed) return;
        clearTimeout(expiryTimer);
        setChat(null);
        setNotice(
          error instanceof ChatReadError
            ? error.message
            : "The chat could not be loaded. Please try again.",
        );
      }
    }

    function visible() {
      if (document.visibilityState === "visible") void refresh();
    }
    void refresh();
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true;
      request?.abort();
      clearTimeout(refreshTimer);
      clearTimeout(expiryTimer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [reload]);

  return (
    <Thread
      messages={chat?.messages ?? []}
      notice={notice}
      failures={chat?.failures ?? []}
      submissionsRemaining={chat?.submissionsRemaining}
      onReload={() => {
        setChat(null);
        setNotice("Loading your private chat…");
        setReload((value) => value + 1);
      }}
    />
  );
}
