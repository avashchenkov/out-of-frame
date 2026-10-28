import recordings from "../data/recorded-examples.json";
import type { ChatMessage } from "./private-chat";

export type RecordedExample = {
  id: string;
  title: string;
  recorded_on: string;
  review_note?: string;
  messages: ChatMessage[];
  failures: string[];
};

export const recordedExamples = recordings as RecordedExample[];
