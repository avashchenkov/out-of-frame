"""The chat model that every model call is built on."""

from langchain_anthropic import ChatAnthropic

from out_of_frame.config import EFFORT, MAX_TOKENS, MODEL


def build_chat_model(
    model: str = MODEL, effort: str = EFFORT, max_tokens: int = MAX_TOKENS
) -> ChatAnthropic:
    """The model at the given effort, or at the API's default for "default", with the given
    output tokens for its thinking and its answer."""
    output_config = None if effort == "default" else {"effort": effort}
    return ChatAnthropic(model=model, output_config=output_config, max_tokens_to_sample=max_tokens)
