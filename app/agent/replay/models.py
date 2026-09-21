from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ReplayActionStatus(str, Enum):
    SUCCESS = "success"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_NOT_INTERACTABLE = "target_not_interactable"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"


class ReplayActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    status: ReplayActionStatus
    reason: str


class ReplayStatus(str, Enum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    RECOVERABLE_FAILURE = "recoverable_failure"
    HARD_FAILURE = "hard_failure"


class ReplayFailureCategory(str, Enum):
    INPUT = "input"
    ARTIFACT = "artifact"
    TARGETING = "targeting"
    TIMEOUT = "timeout"
    EXECUTION = "execution"
    CHECKPOINT = "checkpoint"
    OUTPUT = "output"
    UNKNOWN = "unknown"

class ReplayRecoveryAction(str, Enum):
    REQUEST_INPUT = "request_input"
    WAIT_AND_RECHECK = "wait_and_recheck"
    HUMAN_HANDOFF = "human_handoff"

class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReplayStatus
    reason: str

    # Broad category of a detected failure.
    # Leave unset for success or a normal business outcome.
    failure_category: ReplayFailureCategory | None = None

    # Current extraction returns text values from the UI.
    # Populate only after the full replay succeeds.
    outputs: dict[str, str] = Field(default_factory=dict)

    # Number of actions whose execution and checkpoints passed.
    completed_steps: int = Field(default=0, ge=0)

    # One-based action index, when the failure belongs to an action.
    # Leave unset for input validation or final output extraction.
    failed_step: int | None = Field(default=None, ge=1)

    # Specific machine-readable failure or business-outcome identifier.
    error_code: str | None = None

    # Sanitized diagnostic context.
    expected: str | None = None
    observed: str | None = None

    # References to redacted logs, screenshots, or snapshots.
    evidence_refs: list[str] = Field(default_factory=list)
    recovery_action: ReplayRecoveryAction | None = None

    @property
    def success(self) -> bool:
        return self.status == ReplayStatus.SUCCESS

