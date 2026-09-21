from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agent.schemas.discovery import ActionType


class CapabilityInput(BaseModel):
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
    description: str


# Layer 3:
# Defines how an output can be extracted deterministically
# from the page during replay.


class TableRowMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    value: str


class TableOutputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["table"]

    # Identifies the semantic row.
    # Example:
    # Type = Savings
    row_match: TableRowMatch

    # Identifies the column containing the output.
    # Example:
    # Current Balance
    value_column: str


class CapabilityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal[
        "string",
        "integer",
        "number",
        "boolean",
        "date",
        "currency",
    ]

    binding: TableOutputBinding


class CapabilityTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    name: str


class CapabilityAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionType
    target: CapabilityTarget | None = None
    value: str | None = None
    url: str | None = None


# Layer 2:
# Defines what application state should exist
# after a meaningful replay action.
class CapabilityCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_action: int
    url_pattern: str | None = None
    required_text: list[str]


class CapabilityArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    capability_id: str
    description: str

    inputs: list[CapabilityInput]
    actions: list[CapabilityAction]

    checkpoints: list[CapabilityCheckpoint]

    outputs: list[CapabilityOutput]