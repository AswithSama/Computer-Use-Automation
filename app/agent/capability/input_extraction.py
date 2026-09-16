from typing import Literal

from pydantic import BaseModel, ConfigDict


class InputCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal[
        "string",
        "integer",
        "number",
        "boolean",
        "date",
    ]
    required: bool

    source_step: int
    observed_value: str

    description: str


class InputExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: list[InputCandidate]