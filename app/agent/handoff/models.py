"""Serializable contracts for a human intervention.

These models deliberately contain identifiers and sanitized context only.
Live Playwright objects remain owned by ``BrowserSession`` and must never be
stored in an intervention record.
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExecutionPhase(str, Enum):
    DISCOVERY = "discovery"
    REPLAY = "replay"


class ControlOwner(str, Enum):
    AUTOMATION = "automation"
    HUMAN = "human"


class InterventionStatus(str, Enum):
    REQUESTED = "requested"
    HUMAN_ACTIVE = "human_active"
    RESUMING = "resuming"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class InterventionResolution(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InterventionRequest(BaseModel):
    """Context needed to route one intervention to an operator."""

    model_config = ConfigDict(extra="forbid")

    intervention_id: UUID = Field(default_factory=uuid4)
    run_id: str = Field(min_length=1)
    phase: ExecutionPhase
    reason: str = Field(min_length=1)
    browser_session_id: str = Field(min_length=1)

    current_step: int | None = Field(default=None, ge=1)
    capability_id: str | None = None
    goal_summary: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    risky_action: bool = False
    requested_at: datetime = Field(default_factory=_utc_now)


class HandoffState(BaseModel):
    """Current ownership and lifecycle state for an intervention."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    request: InterventionRequest
    status: InterventionStatus = InterventionStatus.REQUESTED
    control_owner: ControlOwner = ControlOwner.AUTOMATION
    operator_id: str | None = None


class InterventionOutcome(BaseModel):
    """Operator response returned to the suspended automation."""

    model_config = ConfigDict(extra="forbid")

    intervention_id: UUID
    resolution: InterventionResolution
    operator_id: str | None = None
    action_summary: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=_utc_now)

    @property
    def may_attempt_resume(self) -> bool:
        return self.resolution == InterventionResolution.RESOLVED
