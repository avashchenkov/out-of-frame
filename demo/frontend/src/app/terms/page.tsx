import Link from "next/link";
import { operatorDetails, publicLimits } from "../../server/public-info";

export const dynamic = "force-dynamic";
export const metadata = { title: "Service terms | Out of Frame" };

export default async function Terms() {
  const operator = operatorDetails(process.env);
  const limits = await publicLimits(process.env);
  return (
    <main className="page-main">
      <h1>Service terms</h1>
      <p>
        Out of Frame is a free demo of an AI agent, operated by{" "}
        {operator.name ?? "the operator"} (see the{" "}
        <Link href="/impressum">Impressum</Link>). When you select Start chat
        and send a message, you request the service described here.
      </p>
      <h2>The service</h2>
      <p>
        The agent checks one Berlin address for nearby sites, planned
        construction and your regular journeys. It writes a report with links to
        its sources. A language model writes the report, and it can be wrong:
        check the facts against the sources. The report describes facts. It does
        not advise you whether to buy or rent.
      </p>
      <p>
        Your chat is private to the browser that started it. You can return to
        it until it is deleted, as described in the{" "}
        <Link href="/privacy">Privacy notice</Link>.
      </p>
      <h2>Limits</h2>
      {limits ? (
        <ul>
          <li>Up to {limits.identity_chats} chats per browser cookie.</li>
          <li>
            Up to {limits.submissions} messages per chat, including the first
            message and your answers. A retry also counts as a message.
          </li>
          <li>Up to {limits.message_chars} characters per message.</li>
          <li>
            Access to the current chat for up to {limits.lifetime_days} days
            after your first message.
          </li>
        </ul>
      ) : (
        <p>
          The service limits chats per browser, messages per chat, message
          length and access time. The page shows the current values before your
          first message.
        </p>
      )}
      <h2>Availability</h2>
      <p>
        The service is free and has no guaranteed availability. It can be
        paused, limited or ended at any time, for example when a provider budget
        is used up. A chat can stop before its report is ready.
      </p>
      <h2>Your input</h2>
      <p>
        The demo is for users aged 18 or over. The pages are in English; the
        agent answers in the language you write in. Use public places and
        fictional travel plans. Do not enter names or sensitive personal
        details. Do not try to bypass the limits or misuse the service.
      </p>
      <h2>Deletion</h2>
      <p>
        New chat and Delete chat remove the current chat and report. Clearing
        cookies loses access but does not delete the chat earlier. See the{" "}
        <Link href="/privacy">Privacy notice</Link> for retention periods.
      </p>
    </main>
  );
}
