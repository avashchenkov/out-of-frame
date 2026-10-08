"""The base class of the agent's data classes, such as MapObject and Finding."""

from pydantic import BaseModel, ConfigDict


class Record(BaseModel):
    """Immutable, and an unknown field fails, so that a typo in a YAML file fails at once."""

    model_config = ConfigDict(extra="forbid", frozen=True)
