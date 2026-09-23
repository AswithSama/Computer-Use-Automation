"""HumanHandoffManager lifecycle tests.

Scope: control-transfer state machine (request -> human control -> resume),
rejection of invalid transitions, and the evidence journal it writes to disk.
Uses a mocked operator throughout — see test_terminal_operator.py for the
real TerminalOperator, and test_replay_handoff.py for this manager wired
into a real ReplayEngine/ReplayFlow.
"""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.agent.handoff.decision import (
    RecoveryDecision,
    RecoveryDisposition,
)
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.models import (
    ControlOwner,
    ExecutionPhase,
    IncidentClassification,
    InterventionOutcome,
    InterventionRequest,
    InterventionResolution,
    InterventionStatus,
)
from app.agent.handoff.operator import ACTION_SUMMARIES


# ---------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------


def _make_request():
    return InterventionRequest(
        run_id="run-123",
        phase=ExecutionPhase.REPLAY,
        reason="Unexpected dialog blocked replay.",
        browser_session_id="browser-123",
        current_step=3,
    )


def _handoff_decision():
    return RecoveryDecision(
        disposition=RecoveryDisposition.HUMAN_HANDOFF,
        reason="An authorized operator may inspect the live session.",
    )


def _make_manager(tmp_path, request, resolution):
    operator = Mock()
    operator.handle.return_value = InterventionOutcome(
        intervention_id=request.intervention_id,
        resolution=resolution,
        operator_id="test-operator",
        action_summary=ACTION_SUMMARIES["2"],
    )

    manager = HumanHandoffManager(
        operator=operator,
        evidence_dir=tmp_path,
    )

    return manager, operator


def _request_handoff(manager, request):
    return manager.request_intervention(
        request=request,
        decision=_handoff_decision(),
    )


# ---------------------------------------------------------
# Manager tests
# ---------------------------------------------------------


def test_manager_transfers_control_then_waits_for_verification(tmp_path):
    request = _make_request()
    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    expected_outcome = operator.handle.return_value

    def handle(active_request):
        state = manager.state

        assert state.status == InterventionStatus.HUMAN_ACTIVE
        assert state.control_owner == ControlOwner.HUMAN
        assert active_request.intervention_id == request.intervention_id
        assert active_request.browser_session_id == request.browser_session_id

        return expected_outcome

    operator.handle.side_effect = handle

    outcome = _request_handoff(manager, request)

    operator.handle.assert_called_once()
    assert outcome.resolution == InterventionResolution.RESOLVED
    assert manager.state.status == InterventionStatus.RESUMING
    assert manager.state.control_owner == ControlOwner.AUTOMATION
    assert manager.state.operator_id == "test-operator"


@pytest.mark.parametrize("state_verified", [True, False])
def test_resume_requires_explicit_verification(tmp_path, state_verified):
    request = _make_request()
    manager, _ = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    _request_handoff(manager, request)

    result = manager.complete_resume(
        intervention_id=request.intervention_id,
        state_verified=state_verified,
    )

    expected_status = (
        InterventionStatus.RESOLVED
        if state_verified
        else InterventionStatus.CANCELLED
    )

    assert result is state_verified
    assert manager.state.status == expected_status
    assert manager.state.control_owner == ControlOwner.AUTOMATION


@pytest.mark.parametrize(
    ("resolution", "expected_status"),
    [
        (
            InterventionResolution.CANCELLED,
            InterventionStatus.CANCELLED,
        ),
        (
            InterventionResolution.UNRESOLVED,
            InterventionStatus.CANCELLED,
        ),
        (
            InterventionResolution.TIMED_OUT,
            InterventionStatus.TIMED_OUT,
        ),
    ],
)
def test_nonresolved_outcomes_cannot_resume(
    tmp_path,
    resolution,
    expected_status,
):
    request = _make_request()
    manager, _ = _make_manager(tmp_path, request, resolution)

    outcome = _request_handoff(manager, request)

    assert outcome.may_attempt_resume is False
    assert manager.state.status == expected_status
    assert manager.state.control_owner == ControlOwner.AUTOMATION

    with pytest.raises(RuntimeError):
        manager.complete_resume(
            intervention_id=request.intervention_id,
            state_verified=True,
        )


def test_manager_rejects_a_nonhandoff_decision(tmp_path):
    request = _make_request()
    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    decision = RecoveryDecision(
        disposition=RecoveryDisposition.FAIL_WITH_EVIDENCE,
        reason="The capability artifact is invalid.",
    )

    with pytest.raises(ValueError):
        manager.request_intervention(
            request=request,
            decision=decision,
        )

    operator.handle.assert_not_called()
    assert manager.state is None


def test_manager_rejects_a_mismatched_operator_response(tmp_path):
    request = _make_request()
    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    operator.handle.return_value = InterventionOutcome(
        intervention_id=uuid4(),
        resolution=InterventionResolution.RESOLVED,
    )

    with pytest.raises(ValueError):
        _request_handoff(manager, request)

    assert manager.state.status == InterventionStatus.CANCELLED
    assert manager.state.control_owner == ControlOwner.AUTOMATION


def test_operator_exception_cancels_intervention(tmp_path):
    request = _make_request()
    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    operator.handle.side_effect = RuntimeError("Operator interface failed.")

    with pytest.raises(RuntimeError, match="Operator interface failed"):
        _request_handoff(manager, request)

    assert manager.state.status == InterventionStatus.CANCELLED
    assert manager.state.control_owner == ControlOwner.AUTOMATION


def test_manager_rejects_nested_handoff_during_human_control(tmp_path):
    request = _make_request()
    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    expected_outcome = operator.handle.return_value

    def handle(active_request):
        with pytest.raises(RuntimeError, match="already active"):
            _request_handoff(manager, _make_request())

        assert manager.state.control_owner == ControlOwner.HUMAN
        return expected_outcome

    operator.handle.side_effect = handle

    _request_handoff(manager, request)

    operator.handle.assert_called_once()
    assert manager.state.status == InterventionStatus.RESUMING


def test_manager_rejects_new_handoff_while_verification_is_pending(tmp_path):
    request = _make_request()
    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    _request_handoff(manager, request)

    with pytest.raises(RuntimeError, match="already active"):
        _request_handoff(manager, _make_request())

    operator.handle.assert_called_once()
    assert manager.state.status == InterventionStatus.RESUMING


def test_resume_rejects_wrong_intervention_id(tmp_path):
    request = _make_request()
    manager, _ = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    _request_handoff(manager, request)

    with pytest.raises(ValueError):
        manager.complete_resume(
            intervention_id=uuid4(),
            state_verified=True,
        )

    assert manager.state.status == InterventionStatus.RESUMING


def test_resume_cannot_complete_twice(tmp_path):
    request = _make_request()
    manager, _ = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    _request_handoff(manager, request)

    manager.complete_resume(
        intervention_id=request.intervention_id,
        state_verified=True,
    )

    with pytest.raises(RuntimeError):
        manager.complete_resume(
            intervention_id=request.intervention_id,
            state_verified=True,
        )


def test_state_property_returns_an_independent_copy(tmp_path):
    request = _make_request()
    manager, _ = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    _request_handoff(manager, request)

    snapshot = manager.state
    snapshot.status = InterventionStatus.CANCELLED
    snapshot.request.reason = "Changed outside the manager."

    assert manager.state.status == InterventionStatus.RESUMING
    assert manager.state.request.reason == request.reason


def test_manager_records_lifecycle_and_declared_action(tmp_path):
    request = _make_request()
    manager, _ = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )
    request.screenshot_ref = str(tmp_path / "screenshots" / f"{request.intervention_id}.png")

    operator = manager.operator
    operator.handle.return_value = InterventionOutcome(
        intervention_id=request.intervention_id,
        resolution=InterventionResolution.RESOLVED,
        operator_id="test-operator",
        action_summary=ACTION_SUMMARIES["2"],
        incident_classification=IncidentClassification.RECOVERABLE_CONDITION,
    )

    _request_handoff(manager, request)

    manager.complete_resume(
        intervention_id=request.intervention_id,
        state_verified=True,
    )

    path = tmp_path / f"{request.intervention_id}.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]

    assert [record["event"] for record in records] == [
        "intervention_requested",
        "human_control_started",
        "human_control_returned",
        "resume_verified",
    ]

    assert records[1]["control_owner"] == "human"
    assert records[2]["status"] == "resuming"
    assert records[2]["operator_reported_action"] == ACTION_SUMMARIES["2"]
    assert records[3]["status"] == "resolved"
    assert records[0]["screenshot_ref"] == request.screenshot_ref

    assert records[2]["incident_classification"]== "recoverable_condition"

    assert records[2]["review_status"] == "pending_review"


def test_evidence_excludes_unrestricted_context_and_comments(tmp_path):
    request = _make_request()
    request.reason = "PRIVATE_REASON_SENTINEL"
    request.goal_summary = "PRIVATE_GOAL_SENTINEL"

    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    operator.handle.return_value = InterventionOutcome(
        intervention_id=request.intervention_id,
        resolution=InterventionResolution.RESOLVED,
        action_summary="PRIVATE_COMMENT_SENTINEL",
    )

    _request_handoff(manager, request)

    path = tmp_path / f"{request.intervention_id}.jsonl"
    content = path.read_text(encoding="utf-8")

    assert "PRIVATE_REASON_SENTINEL" not in content
    assert "PRIVATE_GOAL_SENTINEL" not in content
    assert "PRIVATE_COMMENT_SENTINEL" not in content


def test_evidence_failure_prevents_operator_takeover(tmp_path):
    request = _make_request()
    manager, operator = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    manager._record = Mock(side_effect=OSError("Evidence unavailable."))

    with pytest.raises(OSError):
        _request_handoff(manager, request)

    operator.handle.assert_not_called()
    assert manager.state.status == InterventionStatus.CANCELLED
    assert manager.state.control_owner == ControlOwner.AUTOMATION


def test_evidence_failure_during_verification_prevents_resume(tmp_path):
    request = _make_request()
    manager, _ = _make_manager(
        tmp_path,
        request,
        InterventionResolution.RESOLVED,
    )

    _request_handoff(manager, request)

    manager._record = Mock(side_effect=OSError("Evidence unavailable."))

    with pytest.raises(OSError):
        manager.complete_resume(
            intervention_id=request.intervention_id,
            state_verified=True,
        )

    assert manager.state.status == InterventionStatus.CANCELLED
