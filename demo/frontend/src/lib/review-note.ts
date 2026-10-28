import { createElement } from "react";

export function reviewNote(note: string | undefined) {
  return note ? createElement("p", { className: "review-note" }, note) : null;
}
