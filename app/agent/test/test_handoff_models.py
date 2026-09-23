"""Model-shape tests for the handoff schema.

Scope: InterventionRequest / HandoffState / InterventionOutcome as data —
serialization, default state, and the resolution -> resume-eligibility rule.
No manager, operator, or replay wiring here; see test_handoff_manager.py,
test_terminal_operator.py, and test_replay_handoff.py for those.
"""

from app.agent.handoff.models import (
    ControlOwner,
    ExecutionPhase,
    HandoffState,
    InterventionOutcome,
    InterventionRequest,
    InterventionResolution,
    InterventionStatus,
)


def _make_request():
    return InterventionRequest(
        run_id="run-123",
        phase=ExecutionPhase.REPLAY,
        reason="Unexpected dialog blocked replay.",
        browser_session_id="browser-123",
        current_step=3,
    )


def test_intervention_request_is_serializable_without_browser_objects():
    request = InterventionRequest(
        run_id="run-123",
        phase=ExecutionPhase.REPLAY,
        reason="Unexpected dialog blocked the recorded action.",
        browser_session_id="browser-123",
        current_step=3,
        capability_id="retrieve-savings-balance",
        evidence_refs=["evidence/run-123/failure.json"],
    )

    payload = request.model_dump(mode="json")

    assert payload["run_id"] == "run-123"
    assert payload["phase"] == "replay"
    assert payload["current_step"] == 3
    assert "page" not in payload
    assert "browser" not in payload


def test_handoff_state_starts_under_automation_control():
    request = InterventionRequest(
        run_id="run-123",
        phase=ExecutionPhase.DISCOVERY,
        reason="The discovery agent is stuck.",
        browser_session_id="browser-123",
    )

    state = HandoffState(request=request)

    assert state.status == InterventionStatus.REQUESTED
    assert state.control_owner == ControlOwner.AUTOMATION


def test_only_resolved_outcome_may_attempt_resume():
    request = _make_request()

    for resolution in InterventionResolution:
        outcome = InterventionOutcome(
            intervention_id=request.intervention_id,
            resolution=resolution,
        )

        assert outcome.may_attempt_resume is (
            resolution == InterventionResolution.RESOLVED
        )
