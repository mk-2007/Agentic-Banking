"""Shared building blocks for every contract in the domain layer."""

from pydantic import BaseModel, ConfigDict

# Values allowed inside free-form `data` / `arguments` / `output` dictionaries.
# Keeping them flat makes payloads easy to hash, log and validate.
FlatValue = str | int | float | bool | None
FlatDict = dict[str, FlatValue]


class Contract(BaseModel):
    """Immutable, strict base model.

    - ``frozen``: an instance never changes after creation; "updates" return a new copy.
    - ``extra="forbid"``: unknown fields are rejected, so typos and injected keys fail loudly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
