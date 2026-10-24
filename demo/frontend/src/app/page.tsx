import { PrivateChat } from "../components/private-chat";
import { contactEmail } from "../server/public-info";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <PrivateChat
      liveEnabled={process.env.OUT_OF_FRAME_DEMO_LIVE_ENABLED === "true"}
      contactEmail={contactEmail(process.env)}
    />
  );
}
