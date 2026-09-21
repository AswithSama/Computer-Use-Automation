"""Deterministic policy for recovery, escalation, and terminal failure."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ConditionKind(str, Enum):
    BUSINESS_OUTCOME = "business_outcome"
    RECOVERABLE_CONDITION = "recoverable_condition"
    FAILURE = "failure"
    RISKY_ACTION = "risky_action"


class ConditionSource(str, Enum):
    TARGET_APPLICATION = "target_application"
    AUTOMATION_RUNTIME = "automation_runtime"
    CAPABILITY_ARTIFACT = "capability_artifact"
    INPUT_CONTRACT = "input_contract"
    POLICY = "policy"
    UNKNOWN = "unknown"


class RecoveryDisposition(str, Enum):
    RETURN_OUTCOME = "return_outcome"
    RECOVER_AUTOMATICALLY = "recover_automatically"
    HUMAN_HANDOFF = "human_handoff"
    FAIL_WITH_EVIDENCE = "fail_with_evidence"


class RecoveryDecisionContext(BaseModel):
    """Facts needed by policy; no browser object or sensitive page data."""

    model_config = ConfigDict(extra="forbid")

    condition_kind: ConditionKind
    source: ConditionSource
    live_session_usable: bool = False
    human_intervention_allowed: bool = False


class RecoveryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition: RecoveryDisposition
    reason: str

    @property
    def requires_handoff(self) -> bool:
        return self.disposition == RecoveryDisposition.HUMAN_HANDOFF


_NON_INTERVENABLE_SOURCES = {
    ConditionSource.AUTOMATION_RUNTIME,
    ConditionSource.CAPABILITY_ARTIFACT,
    ConditionSource.INPUT_CONTRACT,
    ConditionSource.POLICY,
    ConditionSource.UNKNOWN,
}


def decide_recovery(context: RecoveryDecisionContext) -> RecoveryDecision:
    """Choose the next control-path action using conservative rules.

    Classification and response are intentionally separate. A condition can
    be a hard execution failure and still be eligible for handoff when it is
    application-level, the same live session is usable, and policy permits an
    authorized human to intervene.
    """

    if context.condition_kind == ConditionKind.BUSINESS_OUTCOME:
        return RecoveryDecision(
            disposition=RecoveryDisposition.RETURN_OUTCOME,
            reason="Return the known business outcome to the caller.",
        )

    if context.condition_kind == ConditionKind.RECOVERABLE_CONDITION:
        return RecoveryDecision(
            disposition=RecoveryDisposition.RECOVER_AUTOMATICALLY,
            reason="Apply the predefined bounded recovery strategy.",
        )

    if context.source in _NON_INTERVENABLE_SOURCES:
        return RecoveryDecision(
            disposition=RecoveryDisposition.FAIL_WITH_EVIDENCE,
            reason=(
                "The condition cannot be corrected by operating the live "
                "target-application session."
            ),
        )

    if not context.live_session_usable:
        return RecoveryDecision(
            disposition=RecoveryDisposition.FAIL_WITH_EVIDENCE,
            reason="The live application session is not usable for handoff.",
        )

    if not context.human_intervention_allowed:
        return RecoveryDecision(
            disposition=RecoveryDisposition.FAIL_WITH_EVIDENCE,
            reason="Policy does not permit human intervention for this condition.",
        )

    return RecoveryDecision(
        disposition=RecoveryDisposition.HUMAN_HANDOFF,
        reason=(
            "Automation cannot safely proceed, and an authorized human may "
            "intervene in the same live application session."
        ),
    )
