from pydantic import BaseModel, ConfigDict

from app.agent.discovery.models import BrowserAction


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


class DiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str
    finish_reason: str

    execution_trace: list[RecordedTransition]

    candidate_path: list[RecordedTransition]

    final_state: RecordedState