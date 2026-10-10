"""Settings of the agent. Each one can be changed with an environment variable, such as in .env."""

import os

# One model for every call in the MVP; the evals show if it is not enough.
MODEL = os.environ.get("OUT_OF_FRAME_MODEL", "claude-haiku-5-5")

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
    "OUT_OF_FRAME_USER_AGENT", "out-of-frame (github.com/avashchenkov/out-of-frame)"
)

# Tries of one call to Nominatim or Overpass that fails for a while, such as on a timeout.
SOURCE_ATTEMPTS = int(os.environ.get("OUT_OF_FRAME_SOURCE_ATTEMPTS", "3"))
