"""Settings for the demo server, separate from the reusable agent."""

import os

# Private browser demo. Provider spending caps are configured separately at launch.
DEMO_DAILY_CHATS = int(os.environ.get("OUT_OF_FRAME_DEMO_DAILY_CHATS", "5"))
DEMO_IDENTITY_CHATS = int(os.environ.get("OUT_OF_FRAME_DEMO_IDENTITY_CHATS", "2"))
DEMO_LIFETIME_DAYS = int(os.environ.get("OUT_OF_FRAME_DEMO_LIFETIME_DAYS", "30"))
DEMO_SUBMISSIONS = int(os.environ.get("OUT_OF_FRAME_DEMO_SUBMISSIONS", "7"))
DEMO_MESSAGE_CHARS = int(os.environ.get("OUT_OF_FRAME_DEMO_MESSAGE_CHARS", "2000"))
DEMO_CLEANUP_SECONDS = float(os.environ.get("OUT_OF_FRAME_DEMO_CLEANUP_SECONDS", "60"))
DEMO_CANCEL_SECONDS = float(os.environ.get("OUT_OF_FRAME_DEMO_CANCEL_SECONDS", "15"))
DEMO_PROXY_SECRET = os.environ.get("OUT_OF_FRAME_DEMO_PROXY_SECRET", "")
