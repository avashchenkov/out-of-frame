import Link from "next/link";
import { SiteFooter } from "../../components/site-footer";
import { SiteHeader } from "../../components/site-header";
import { recordedExamples } from "../../lib/recorded-examples";

export const metadata = { title: "Recorded examples | Out of Frame" };

export default function Examples() {
  return (
    <>
      <SiteHeader />
      <main className="examples-main">
        <p className="eyebrow">Recorded examples</p>
        <h1>Five Berlin addresses, beyond the listing.</h1>
        <p className="example-note">
          Prepared requests with fictional travel plans and AI-generated
          reports. Research dates are shown below; these are saved results, not
          live checks. Viewing them does not use your private chat allowance.
        </p>
        <ul className="example-list">
          {recordedExamples.map((example) => (
            <li key={example.id}>
              <h2>
                <Link href={`/examples/${example.id}`}>{example.title}</Link>
              </h2>
              <p>
                Research:{" "}
                <time dateTime={example.recorded_on}>
                  {example.recorded_on}
                </time>
              </p>
              <Link href={`/examples/${example.id}`}>
                View request and report →
              </Link>
            </li>
          ))}
        </ul>
      </main>
      <SiteFooter />
    </>
  );
}
