import { SiteFooter } from "../../components/site-footer";
import { SiteHeader } from "../../components/site-header";
import { operatorDetails } from "../../server/public-info";

export const dynamic = "force-dynamic";
export const metadata = { title: "Impressum | Out of Frame" };

export default function Impressum() {
  const operator = operatorDetails(process.env);
  return (
    <>
      <SiteHeader />
      <main className="page-main">
        <h1>Impressum</h1>
        <p>Information under § 5 DDG.</p>
        <h2>Operator</h2>
        <address>
          {operator.name ?? "Operator name not configured."}
          {operator.address.length > 0 ? (
            operator.address.map((line) => (
              <span key={line}>
                <br />
                {line}
              </span>
            ))
          ) : (
            <>
              <br />
              Postal address not configured.
            </>
          )}
        </address>
        <h2 id="contact">Contact</h2>
        <p>
          {operator.email ? (
            <a href={`mailto:${encodeURIComponent(operator.email)}`}>
              {operator.email}
            </a>
          ) : (
            "Contact email not configured."
          )}
        </p>
        <p>
          Write to this address for questions, feedback, data protection
          requests or an arranged demo.
        </p>
      </main>
      <SiteFooter />
    </>
  );
}
