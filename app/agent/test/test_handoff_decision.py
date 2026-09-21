from app.agent.handoff.decision import (
    ConditionKind,
    ConditionSource,
    RecoveryDecisionContext,
    RecoveryDisposition,
    decide_recovery,
)


def _decide(
    *,
    kind: ConditionKind,
    source: ConditionSource,
    session_usable: bool = False,
    intervention_allowed: bool = False,
) -> RecoveryDisposition:
    decision = decide_recovery(
        RecoveryDecisionContext(
            condition_kind=kind,
            source=source,
            live_session_usable=session_usable,
            human_intervention_allowed=intervention_allowed,
        )
    )
    return decision.disposition


def test_known_business_outcome_is_returned():
    assert _decide(
        kind=ConditionKind.BUSINESS_OUTCOME,
        source=ConditionSource.TARGET_APPLICATION,
    ) == RecoveryDisposition.RETURN_OUTCOME


def test_known_recoverable_condition_stays_automatic():
    assert _decide(
        kind=ConditionKind.RECOVERABLE_CONDITION,
        source=ConditionSource.TARGET_APPLICATION,
    ) == RecoveryDisposition.RECOVER_AUTOMATICALLY


def test_internal_runtime_failure_fails_with_evidence():
    assert _decide(
        kind=ConditionKind.FAILURE,
        source=ConditionSource.AUTOMATION_RUNTIME,
        session_usable=True,
        intervention_allowed=True,
    ) == RecoveryDisposition.FAIL_WITH_EVIDENCE


def test_invalid_artifact_does_not_open_browser_handoff():
    assert _decide(
        kind=ConditionKind.FAILURE,
        source=ConditionSource.CAPABILITY_ARTIFACT,
        session_usable=True,
        intervention_allowed=True,
    ) == RecoveryDisposition.FAIL_WITH_EVIDENCE


def test_policy_violation_cannot_be_bypassed_by_handoff():
    assert _decide(
        kind=ConditionKind.FAILURE,
        source=ConditionSource.POLICY,
        session_usable=True,
        intervention_allowed=True,
    ) == RecoveryDisposition.FAIL_WITH_EVIDENCE


def test_unresolved_application_failure_requests_handoff():
    assert _decide(
        kind=ConditionKind.FAILURE,
        source=ConditionSource.TARGET_APPLICATION,
        session_usable=True,
        intervention_allowed=True,
    ) == RecoveryDisposition.HUMAN_HANDOFF


def test_risky_action_requests_handoff_before_execution():
    assert _decide(
        kind=ConditionKind.RISKY_ACTION,
        source=ConditionSource.TARGET_APPLICATION,
        session_usable=True,
        intervention_allowed=True,
    ) == RecoveryDisposition.HUMAN_HANDOFF


def test_unusable_session_fails_instead_of_handoff():
    assert _decide(
        kind=ConditionKind.FAILURE,
        source=ConditionSource.TARGET_APPLICATION,
        session_usable=False,
        intervention_allowed=True,
    ) == RecoveryDisposition.FAIL_WITH_EVIDENCE


def test_disallowed_intervention_fails_instead_of_handoff():
    assert _decide(
        kind=ConditionKind.FAILURE,
        source=ConditionSource.TARGET_APPLICATION,
        session_usable=True,
        intervention_allowed=False,
    ) == RecoveryDisposition.FAIL_WITH_EVIDENCE


def test_unknown_source_fails_conservatively():
    assert _decide(
        kind=ConditionKind.FAILURE,
        source=ConditionSource.UNKNOWN,
        session_usable=True,
        intervention_allowed=True,
    ) == RecoveryDisposition.FAIL_WITH_EVIDENCE
