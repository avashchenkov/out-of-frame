import { createElement } from "react";
import type { Components } from "react-markdown";

export function reportMarkdownComponents(markdown: string): Components {
  return {
    a: ({ href, children, node }) => {
      const offset = node?.position?.start.offset;
      // Only explicit Markdown links are clickable. GFM can link plain address text.
      if (offset === undefined || markdown[offset] !== "[") return children;
      return createElement(
        "a",
        { href, target: "_blank", rel: "noopener noreferrer" },
        children,
      );
    },
    img: ({ alt }) => createElement("span", null, alt),
  };
}
