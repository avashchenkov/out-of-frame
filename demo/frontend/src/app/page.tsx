import { PrivateChat } from "../components/private-chat";

export const dynamic = "force-dynamic";

export default function Home() {
  const email = process.env.OUT_OF_FRAME_DEMO_CONTACT_EMAIL ?? "";
  const contactEmail = /^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(email)
    ? email
    : undefined;
  return (
    <PrivateChat
      liveEnabled={process.env.OUT_OF_FRAME_DEMO_LIVE_ENABLED === "true"}
      contactEmail={contactEmail}
    />
  );
}
