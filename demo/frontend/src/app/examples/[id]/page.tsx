import Link from "next/link";
import { notFound } from "next/navigation";
import { ConversationMessages } from "../../../components/thread/messages";
import { recordedExamples } from "../../../lib/recorded-examples";

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
      <p className="eyebrow">Recorded example</p>
      <h1>{example.title}</h1>
      <p className="example-note">
        Research:{" "}
        <time dateTime={example.recorded_on}>{example.recorded_on}</time>. The
        report was regenerated from these saved findings, without new research.
        This prepared example cannot be continued.{" "}
        <Link href="/">Try a live chat</Link>.
      </p>
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
