import Link from "next/link";
import { recordedExamples } from "../../lib/recorded-examples";

export const metadata = { title: "Recorded examples | Out of Frame" };

// "21–22 October 2026": one line for all examples instead of a date on each.
function recordedPeriod(dates: string[]) {
  const sorted = [...dates].sort();
  const format = (date: string, parts: Intl.DateTimeFormatOptions) =>
    new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
      ...parts,
      timeZone: "UTC",
    });
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const full = { day: "numeric", month: "long", year: "numeric" } as const;
  if (first === last) return format(first, full);
  if (first.slice(0, 7) === last.slice(0, 7))
    return `${format(first, { day: "numeric" })}–${format(last, full)}`;
  return `${format(first, full)} – ${format(last, full)}`;
}

export default function Examples() {
  return (
    <main className="examples-main">
      <h1>Recorded examples</h1>
      <p className="example-note">
        AI reports for five Berlin addresses, recorded on{" "}
        {recordedPeriod(recordedExamples.map((item) => item.recorded_on))}.
      </p>
      <ul className="example-list">
        {recordedExamples.map((example) => (
          <li key={example.id}>
            <Link href={`/examples/${example.id}`} className="example-card">
              {example.title}
              <span aria-hidden="true">→</span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
