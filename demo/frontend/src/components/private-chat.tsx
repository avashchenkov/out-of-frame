"use client";

import { useEffect, useState } from "react";
import { Thread } from "./thread";
import type { PrivateChat as Chat } from "../lib/private-chat";
import { watchPrivateChat } from "../lib/watch-private-chat";

export function PrivateChat() {
  const [chat, setChat] = useState<Chat | null>(null);
  const [notice, setNotice] = useState("Loading your private chat…");
  const [reload, setReload] = useState(0);

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
