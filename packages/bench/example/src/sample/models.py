"""The sample package's models."""

from typing import ClassVar

from pydantic import BaseModel, Field

LIMIT = 5


class Answer(BaseModel):
    """What the sample returns."""

    kind: ClassVar[str] = "answer"
    limit: int = LIMIT
    """How many to return."""
    tags: list[str] = Field(default_factory=list)
    """Labels on the answer."""

    @property
    def total(self) -> int:
        return self.limit
