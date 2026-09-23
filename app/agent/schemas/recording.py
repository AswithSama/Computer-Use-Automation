from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.schemas.discovery import (
    BrowserAction,
    DiscoveredOutput,
)


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

    # Successfully validated automation actions, not manual actions.
    execution_trace: list[RecordedTransition]

    # Empty for assisted runs because manual activity may have broken
    # the continuity of the autonomous path.
    candidate_path: list[RecordedTransition]

    final_state: RecordedState

    human_assisted: bool = False
    intervention_count: int = Field(default=0, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)