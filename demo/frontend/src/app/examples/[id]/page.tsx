import Link from "next/link";
import { notFound } from "next/navigation";
import { ConversationMessages } from "../../../components/thread/messages";
import { recordedExamples } from "../../../lib/recorded-examples";
import { reviewNote } from "../../../lib/review-note";

export const dynamicParams = false;

export function generateStaticParams() {
  return recordedExamples.map(({ id }) => ({ id }));
}

export default async function Example({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const example = recordedExamples.find((item) => item.id === id);
  if (!example) notFound();

  return (
    <main className="examples-main">
      <Link href="/examples" className="back-link">
        ← All examples
      </Link>
      <h1>{example.title}</h1>
      <p className="example-note">
        Recorded example from{" "}
        <time dateTime={example.recorded_on}>
          {new Date(`${example.recorded_on}T12:00:00Z`).toLocaleDateString(
            "en-GB",
            { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" },
          )}
        </time>
        . <Link href="/">Try a live chat</Link>
      </p>
      {reviewNote(example.review_note)}
      <ConversationMessages messages={example.messages} />
      {example.failures.length > 0 && (
        <aside aria-label="Unavailable sources">
          {example.failures.map((failure) => (
            <p key={failure}>{failure}</p>
          ))}
        </aside>
      )}
    </main>
  );
}
