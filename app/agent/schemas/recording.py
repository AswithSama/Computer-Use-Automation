from pydantic import BaseModel, ConfigDict

from app.agent.schemas.discovery import (
    BrowserAction,
    DiscoveredOutput,
)
from typing import Literal

class RecordedState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    observation: str
    fingerprint: str


class RecordedTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    before_state: RecordedState
    action: BrowserAction
    after_state: RecordedState
    outcome_reason: str


class TableRowMatchBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    value: str


class VerifiedTableOutputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["table"]
    row_match: TableRowMatchBinding
    value_column: str


class DiscoveredOutputLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_name: str
    output_type: str
    observed_value: str
    binding: VerifiedTableOutputBinding

class DiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str
    finish_reason: str

    outputs: list[DiscoveredOutput]

    output_locations: list[DiscoveredOutputLocation]

    execution_trace: list[RecordedTransition]
    candidate_path: list[RecordedTransition]

    final_state: RecordedState