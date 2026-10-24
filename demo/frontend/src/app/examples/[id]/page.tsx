import Link from "next/link";
import { notFound } from "next/navigation";
import { SiteFooter } from "../../../components/site-footer";
import { SiteHeader } from "../../../components/site-header";
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
    <>
      <SiteHeader />
      <main className="examples-main">
        <Link href="/examples">← All examples</Link>
        <p className="eyebrow">Recorded example</p>
        <h1>{example.title}</h1>
        <p className="example-note">
          Research:{" "}
          <time dateTime={example.recorded_on}>{example.recorded_on}</time>. The
          report was regenerated from these saved findings, without new
          research. This prepared example cannot be continued.{" "}
          <Link href="/">Try a private chat</Link>.
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
      <SiteFooter />
    </>
  );
}
