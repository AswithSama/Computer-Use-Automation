"""Typed contracts for application and capability allowlist policies."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.agent.schemas.discovery import ActionType


class PolicyDecision(str, Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    NEEDS_CONFIRMATION = "needs_confirmation"


class TargetRule(BaseModel):
    """
    A rule for a specific interactive control.

    The policy engine will match action type, role, name,
    and optionally the route where the control appears.
    """

    model_config = ConfigDict(extra="forbid")

    action: ActionType
    role: str = Field(min_length=1)
    name: str = Field(min_length=1)
    route_pattern: str | None = None


class PolicyProfile(BaseModel):
    """
    Permissions for a specific workflow or capability.

    A profile may restrict global permissions but cannot
    expand them.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_routes: list[str] = Field(min_length=1)
    allowed_actions: set[ActionType] = Field(min_length=1)

    blocked_routes: list[str] = Field(default_factory=list)
    blocked_actions: set[ActionType] = Field(default_factory=set)

    blocked_targets: list[TargetRule] = Field(default_factory=list)
    confirmation_targets: list[TargetRule] = Field(
        default_factory=list
    )


class AllowlistConfig(BaseModel):
    """
    Trusted policy configuration for one application.

    Global rules apply to every workflow. A selected profile
    adds restrictions for a particular operation or capability.
    """

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1)

    allowed_origins: list[str] = Field(min_length=1)

    allowed_routes: list[str] = Field(min_length=1)
    blocked_routes: list[str] = Field(default_factory=list)

    allowed_actions: set[ActionType] = Field(min_length=1)
    blocked_actions: set[ActionType] = Field(default_factory=set)

    blocked_targets: list[TargetRule] = Field(default_factory=list)
    confirmation_targets: list[TargetRule] = Field(
        default_factory=list
    )

    profiles: dict[str, PolicyProfile] = Field(
        default_factory=dict
    )


class PolicyResult(BaseModel):
    """The outcome of one deterministic authorization check."""

    model_config = ConfigDict(extra="forbid")

    decision: PolicyDecision
    code: str
    reason: str


class PolicyViolation(RuntimeError):
    """Raised when an attempted browser operation violates policy."""

    def __init__(self, result: PolicyResult):
        self.result = result
        super().__init__(result.reason)