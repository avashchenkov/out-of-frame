"""Settings of the agent. Each one can be changed with an environment variable, such as in .env."""

import os
from importlib.metadata import version

# The agent's model, in every call but the prompt injection check, and how much it thinks before
# it answers: at the default effort, medium on Haiku 5.5, its findings applied a rule one way in
# one trial and another way in the next; at the extra-high effort it at times gave no finding,
# and its report ran out of output tokens. An effort of "default" leaves it to the API.
MODEL = os.environ.get("OUT_OF_FRAME_MODEL", "claude-haiku-5-5")
EFFORT = os.environ.get("OUT_OF_FRAME_EFFORT", "high")
# The output tokens of one answer, its thinking included: langchain's fallback of 4096, for a
# model that it has no profile of, such as Haiku 5.5, can go on the thinking alone, as it did for
# a report about some 15 objects.
MAX_TOKENS = int(os.environ.get("OUT_OF_FRAME_MAX_TOKENS", "16000"))

# The prompt injection check's own model, effort and output tokens: a classifier apart from the
# agent's reasoning, which runs on every snippet and page.
INJECTION_MODEL = os.environ.get("OUT_OF_FRAME_INJECTION_MODEL", "claude-haiku-5-5")
INJECTION_EFFORT = os.environ.get("OUT_OF_FRAME_INJECTION_EFFORT", "default")
# 4096, as the check had before it got its own settings, and passed its suites with.
INJECTION_MAX_TOKENS = int(os.environ.get("OUT_OF_FRAME_INJECTION_MAX_TOKENS", "4096"))

# Tool calls in one investigation, Tavily searches and page reads together.
TOOL_CAP = int(os.environ.get("OUT_OF_FRAME_TOOL_CAP", "3"))

# Results of one web search.
SEARCH_RESULTS = int(os.environ.get("OUT_OF_FRAME_SEARCH_RESULTS", "5"))

# A longer page is cut, so that a prompt stays short: about 10k tokens a page, and Haiku 5.5
# costs five times as much for a prompt over 100k tokens.
PAGE_CHARS = int(os.environ.get("OUT_OF_FRAME_PAGE_CHARS", "40000"))

# Tries of one web search or page read that fails for a while, such as on a timeout.
WEB_ATTEMPTS = int(os.environ.get("OUT_OF_FRAME_WEB_ATTEMPTS", "3"))

# Tries of one prompt injection check whose answer is cut off or does not parse. A page is never
# shown to the model unchecked, so after the last one the run stops.
CHECK_ATTEMPTS = int(os.environ.get("OUT_OF_FRAME_CHECK_ATTEMPTS", "2"))

# The public Nominatim instance. Its usage policy asks each app to name itself in the User-Agent.
NOMINATIM_URL = os.environ.get(
    "OUT_OF_FRAME_NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"
)
USER_AGENT = os.environ.get(
    "OUT_OF_FRAME_USER_AGENT",
    f"out-of-frame/{version('out-of-frame')} (github.com/avashchenkov/out-of-frame)",
)

# The public Overpass instance, which code asks for the map objects around the property.
OVERPASS_URL = os.environ.get(
    "OUT_OF_FRAME_OVERPASS_URL", "https://overpass-api.de/api/interpreter"
)

# The map objects kept per category, nearest first. Every unclear one of them is investigated,
# so this is also the cap of investigations per category, see docs/architecture.md#one-run.
MAP_OBJECTS_PER_CATEGORY = int(os.environ.get("OUT_OF_FRAME_MAP_OBJECTS_PER_CATEGORY", "5"))

# Investigations that run at once, so that a run does not hit the model's rate limit. At least
# 2: a stream with its subgraphs, as in evals/judge.py, takes one of them, and with only one
# the run would wait for ever.
INVESTIGATIONS_AT_ONCE = int(os.environ.get("OUT_OF_FRAME_INVESTIGATIONS_AT_ONCE", "3"))

# The public Berlin B-Plan WFS, which code asks for the development plans around the property.
BPLAN_WFS_URL = os.environ.get(
    "OUT_OF_FRAME_BPLAN_WFS_URL", "https://gdi.berlin.de/services/wfs/bplan"
)

# The plans kept, nearest first. Every one of them is investigated, so this is also the cap of
# plan investigations, see docs/architecture.md#one-run.
PLANS = int(os.environ.get("OUT_OF_FRAME_PLANS", "5"))

# The public Transitous instance, which code asks for the journeys there and back. Its usage
# policy asks each app to name itself and its version in the User-Agent.
TRANSITOUS_URL = os.environ.get(
    "OUT_OF_FRAME_TRANSITOUS_URL", "https://api.transitous.org/api/v5/plan"
)

# Tries of one call to Nominatim, Overpass, the B-Plan WFS or Transitous that fails for a while,
# such as on a timeout.
SOURCE_ATTEMPTS = int(os.environ.get("OUT_OF_FRAME_SOURCE_ATTEMPTS", "3"))

# Drafts of one report that cites an ID it was not given or leaves out an object, before the
# run stops.
REPORT_ATTEMPTS = int(os.environ.get("OUT_OF_FRAME_REPORT_ATTEMPTS", "2"))

# Private browser demo. Provider spending caps are configured separately at launch.
DEMO_DAILY_CHATS = int(os.environ.get("OUT_OF_FRAME_DEMO_DAILY_CHATS", "5"))
DEMO_IDENTITY_CHATS = int(os.environ.get("OUT_OF_FRAME_DEMO_IDENTITY_CHATS", "2"))
DEMO_LIFETIME_DAYS = int(os.environ.get("OUT_OF_FRAME_DEMO_LIFETIME_DAYS", "30"))
DEMO_SUBMISSIONS = int(os.environ.get("OUT_OF_FRAME_DEMO_SUBMISSIONS", "7"))
DEMO_MESSAGE_CHARS = int(os.environ.get("OUT_OF_FRAME_DEMO_MESSAGE_CHARS", "2000"))
DEMO_CLEANUP_SECONDS = float(os.environ.get("OUT_OF_FRAME_DEMO_CLEANUP_SECONDS", "60"))
DEMO_CANCEL_SECONDS = float(os.environ.get("OUT_OF_FRAME_DEMO_CANCEL_SECONDS", "15"))
DEMO_PROXY_SECRET = os.environ.get("OUT_OF_FRAME_DEMO_PROXY_SECRET", "")
