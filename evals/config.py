"""Settings used only by evaluation tools."""

import os

# The model of the evals' LLM judges, which grade the agent's output; the agent never uses it.
JUDGE_MODEL = os.environ.get("OUT_OF_FRAME_JUDGE_MODEL", "claude-haiku-5-5")
# How much the judges think before they answer: their misses were lapses of attention.
JUDGE_EFFORT = os.environ.get("OUT_OF_FRAME_JUDGE_EFFORT", "xhigh")
# The output tokens of one judge's answer, with room for that thinking.
JUDGE_MAX_TOKENS = int(os.environ.get("OUT_OF_FRAME_JUDGE_MAX_TOKENS", "16000"))
