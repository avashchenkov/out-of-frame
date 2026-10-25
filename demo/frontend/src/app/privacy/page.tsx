import Link from "next/link";
import { SiteFooter } from "../../components/site-footer";
import { SiteHeader } from "../../components/site-header";
import { operatorDetails, publicLimits } from "../../server/public-info";

export const dynamic = "force-dynamic";
export const metadata = { title: "Privacy notice | Out of Frame" };

const UPDATED = "2026-10-25";

export default async function Privacy() {
  const operator = operatorDetails(process.env);
  const limits = await publicLimits(process.env);
  const lifetime = limits
    ? `${limits.lifetime_days} days`
    : "the period shown before your first message";
  return (
    <>
      <SiteHeader />
      <main className="page-main">
        <h1>Privacy notice</h1>
        <p>
          Last updated: <time dateTime={UPDATED}>{UPDATED}</time>.
        </p>

        <h2>Controller</h2>
        <address>
          {operator.name ?? "Operator name not configured."}
          {operator.address.map((line) => (
            <span key={line}>
              <br />
              {line}
            </span>
          ))}
          <br />
          {operator.email ? (
            <a href={`mailto:${encodeURIComponent(operator.email)}`}>
              {operator.email}
            </a>
          ) : (
            "Contact email not configured."
          )}
        </address>

        <h2>What we process and why</h2>
        <h3>Your private chat</h3>
        <p>
          When you start a private chat, we process your messages, the addresses
          and journey times in them, the agent&apos;s questions and the report.
          We need this to provide the report you request under the{" "}
          <Link href="/terms">service terms</Link> and to let you return to it.
          Legal basis: Article 6(1)(b) GDPR.
        </p>
        <h3>Usage limits</h3>
        <p>
          For each browser cookie we keep a random ID, its expiry, the number of
          chats and submissions and a reference to the current chat. We also
          count new chats per day across all visitors. These records contain no
          messages or addresses. They keep the free service available to many
          visitors and its costs limited. Legal basis: our legitimate interest,
          Article 6(1)(f) GDPR.
        </p>
        <h3>Security logs</h3>
        <p>
          Our server records your IP address, the time, the requested path and
          the response status for each request. We use this to detect misuse and
          errors. Legal basis: our legitimate interest in a secure service,
          Article 6(1)(f) GDPR.
        </p>
        <h3>What we do not do</h3>
        <p>
          We use no analytics, tracking pixels or third-party fonts. We do not
          use your chat for recorded examples, evaluations or improvement of the
          agent. The recorded examples and these pages set no cookie.
        </p>

        <h2>Cookie</h2>
        <p>
          The essential cookie <code>oof_identity</code> holds a signed random
          ID. We set it when we accept your first message. It gives this browser
          access to its chat and applies the chat limit. It expires {lifetime}{" "}
          after your first message and is not renewed. It is strictly necessary
          for the service you request, so it needs no consent (section 25(2)
          TDDDG).
        </p>

        <h2>Recipients</h2>
        <p>
          The agent sends only the data each service needs. We do not forward
          your cookie or IP address to the data sources.
        </p>
        <table>
          <thead>
            <tr>
              <th scope="col">Recipient</th>
              <th scope="col">Data</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{operator.hostingProvider ?? "Our hosting provider"}</td>
              <td>
                IP address, cookie, HTTP requests and the stored chat, as the
                host of our server
              </td>
            </tr>
            <tr>
              <td>Anthropic (language model)</td>
              <td>
                Your messages, selected research results and source excerpts, to
                research and write the report
              </td>
            </tr>
            <tr>
              <td>Nominatim (OpenStreetMap Foundation)</td>
              <td>The property and destination addresses</td>
            </tr>
            <tr>
              <td>Overpass API</td>
              <td>Coordinates, search radii and map object IDs</td>
            </tr>
            <tr>
              <td>Berlin B-Plan WFS (State of Berlin)</td>
              <td>A map area and the names of planning layers</td>
            </tr>
            <tr>
              <td>Transitous</td>
              <td>
                Start and destination coordinates, journey dates and times
              </td>
            </tr>
            <tr>
              <td>Tavily (web search)</td>
              <td>
                Search queries about map objects or plans and web pages to read,
                not your chat
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          Anthropic is based in the United States and processes this data on our
          behalf under its{" "}
          <a
            href="https://www.anthropic.com/legal/data-processing-addendum"
            target="_blank"
            rel="noopener noreferrer"
          >
            Data Processing Addendum
          </a>
          . Its API offers no processing limited to the EU, so the data can be
          processed in the United States or other countries outside the European
          Economic Area. The transfer is protected by the EU Standard
          Contractual Clauses in that addendum (Article 46(2)(c) GDPR).
        </p>
        <p>
          Tavily is also based in the United States. It receives only searches
          about map objects and plans near the address and the web pages to
          read, never your messages, cookie or IP address, so we do not expect
          these requests to identify you. Tavily uses them under its own{" "}
          <a
            href="https://www.tavily.com/privacy"
            target="_blank"
            rel="noopener noreferrer"
          >
            privacy policy
          </a>{" "}
          and terms, which allow it to improve its services and AI models with
          them.
        </p>

        <h2>Retention</h2>
        <ul>
          <li>
            Your current chat and report: on our server for up to {lifetime}{" "}
            after your first message. A second chat gets only the remaining
            time. New chat and Delete chat remove the current chat earlier.
          </li>
          <li>Usage limit records: until the cookie expires.</li>
          <li>Security logs: up to 24 hours.</li>
          <li>
            Providers keep their own copies for their own periods. Deletion on
            our server does not delete them. See, for example,{" "}
            <a
              href="https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data"
              target="_blank"
              rel="noopener noreferrer"
            >
              Anthropic&apos;s API retention
            </a>
            .
          </li>
        </ul>
        <p>
          Clearing cookies loses access to your chat. It does not delete it
          earlier; it is still removed by the original deadline.
        </p>

        <h2>Your rights</h2>
        <p>
          You have the right to access, correct and delete your data, to
          restrict its processing and to receive it in a portable format. You
          can object to processing based on our legitimate interest. Write to
          the contact address above; we normally answer within one month. A chat
          is linked only to a random ID, so we may ask for details that identify
          it, such as the time of your first message.
        </p>
        <p>
          You can also complain to a data protection supervisory authority, for
          example in the EU country where you live or work.
        </p>
        <p>
          Providing data is not required. Without it you can still read the{" "}
          <Link href="/examples">recorded examples</Link>.
        </p>
      </main>
      <SiteFooter />
    </>
  );
}
