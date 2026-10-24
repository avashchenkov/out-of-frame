import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { reportMarkdownComponents } from "../../../demo/frontend/src/lib/report-markdown.ts";

const require = createRequire(
  new URL("../../../demo/frontend/package.json", import.meta.url),
);
const { createElement } = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const Markdown = require("react-markdown").default;
const remarkGfm = require("remark-gfm").default;

function render(markdown: string): string {
  return renderToStaticMarkup(
    createElement(Markdown, {
      children: markdown,
      skipHtml: true,
      remarkPlugins: [remarkGfm],
      components: reportMarkdownComponents(markdown),
    }),
  );
}

test("plain URLs, emails and escaped user links stay text", () => {
  const html = render(
    "https://example.com www.example.com person@example.com <https://example.com> " +
      "\\[Prize\\]\\(https://example.com\\)",
  );
  assert.doesNotMatch(html, /<a\b/);
  assert.match(html, /https:\/\/example.com/);
  assert.match(html, /\[Prize\]\(https:\/\/example.com/);
});

test("explicit source and reference links keep their targets and safe attributes", () => {
  const html = render(
    "© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)\n\n" +
      "[Transitous and its sources][transit]\n\n" +
      "[transit]: https://transitous.org/sources/",
  );
  assert.match(html, /href="https:\/\/www.openstreetmap.org\/copyright"/);
  assert.match(html, /href="https:\/\/transitous.org\/sources\/"/);
  assert.equal((html.match(/rel="noopener noreferrer"/g) ?? []).length, 2);
});

test("HTML, images and unsafe protocols cannot load remote content or execute", () => {
  const html = render(
    '<script>alert(1)</script>\n\n<img src="https://example.com/pixel">\n\n' +
      "![image text](https://example.com/pixel) [unsafe](javascript:alert%281%29)",
  );
  assert.doesNotMatch(html, /<script|<img|src=|href="javascript:/);
  assert.match(html, /image text/);
});

test("five exports contain only visible dated requests and complete reports", () => {
  const examples = JSON.parse(
    readFileSync(
      new URL(
        "../../../demo/frontend/src/data/recorded-examples.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  assert.equal(examples.length, 5);
  assert.equal(
    new Set(examples.map((example: { id: string }) => example.id)).size,
    5,
  );
  for (const example of examples) {
    assert.deepEqual(Object.keys(example).sort(), [
      "failures",
      "id",
      "messages",
      "recorded_on",
      "title",
    ]);
    assert.match(example.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.match(example.recorded_on, /^2026-10-2[12]$/);
    assert.deepEqual(example.failures, []);
    assert.equal(example.messages.length, 2);
    assert.deepEqual(
      example.messages.map((message: { type: string }) => message.type),
      ["human", "ai"],
    );
    for (const message of example.messages) {
      assert.deepEqual(Object.keys(message).sort(), ["content", "id", "type"]);
      assert.equal(typeof message.content, "string");
      assert.ok(message.content.length);
    }
    assert.equal(example.messages[1].id, "final-report");
    const report = example.messages[1].content;
    assert.match(report, /A language model wrote this report/);
    assert.match(report, /## Licences/);
    const html = render(report);
    assert.match(html, /href="https:\/\/www.openstreetmap.org\/copyright"/);
    assert.doesNotMatch(html, /<script|<img/);
    if (report.includes("## Journeys")) {
      assert.match(html, /href="https:\/\/transitous.org\/sources\/"/);
    }
  }
});
