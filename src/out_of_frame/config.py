"""Settings of the agent. Each one can be changed with an environment variable, such as in .env."""

import os

# One model for every call in the MVP; the evals show if it is not enough.
MODEL = os.environ.get("OUT_OF_FRAME_MODEL", "claude-haiku-5-5")
