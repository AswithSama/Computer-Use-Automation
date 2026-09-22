import json
from unittest.mock import Mock
from uuid import uuid4
from pathlib import Path
import pytest

from types import SimpleNamespace

import app.agent.orchestration.replay_flow as replay_flow_module
from app.agent.replay.models import (
    ReplayActionResult,
    ReplayActionStatus,
    ReplayStatus,
)
from app.agent.replay.replay_engine import ReplayEngine
from app.agent.schemas.capability import (
    CapabilityAction,
    CapabilityArtifact,
    CapabilityCheckpoint,
    CapabilityInput,
    CapabilityTarget,
)
from app.agent.schemas.discovery import ActionType
from app.agent.handoff.decision import (
    RecoveryDecision,
    RecoveryDisposition,
)
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.models import (
    ControlOwner,
    ExecutionPhase,
    HandoffState,
    InterventionOutcome,
    InterventionRequest,
    InterventionResolution,
    InterventionStatus,
    IncidentClassification
)
from app.agent.handoff.operator import (
    ACTION_SUMMARIES,
    TerminalOperator,
)


# ---------------------------------------------------------
# Existing model tests
# ---------------------------------------------------------


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


# ---------------------------------------------------------
# Terminal operator tests
# ---------------------------------------------------------


@pytest.mark.parametrize(
    ("choice", "expected_resolution"),
    [
        ("d", InterventionResolution.RESOLVED),
        ("u", InterventionResolution.UNRESOLVED),
    ],
)
def test_terminal_operator_collects_declared_action(
    monkeypatch,
    choice,
    expected_resolution,
):
    request = _make_request()
    operator = TerminalOperator(operator_id="test-operator")

    answers = iter([choice, "2", "2"])
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: next(answers),
    )

    outcome = operator.handle(request)

    assert outcome.intervention_id == request.intervention_id
    assert outcome.resolution == expected_resolution
    assert outcome.operator_id == "test-operator"
    assert outcome.action_summary == ACTION_SUMMARIES["2"]
    assert outcome.incident_classification == IncidentClassification.RECOVERABLE_CONDITION


@pytest.mark.parametrize(
    "answers",
    [
        ["c"],
        ["d", "c"],
    ],
)
def test_terminal_operator_supports_cancellation(monkeypatch, answers):
    operator = TerminalOperator(operator_id="test-operator")

    responses = iter(answers)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: next(responses),
    )

    outcome = operator.handle(_make_request())

    assert outcome.resolution == InterventionResolution.CANCELLED
    assert outcome.may_attempt_resume is False


@pytest.mark.parametrize("error_type", [EOFError, KeyboardInterrupt])
def test_terminal_interruption_cancels_handoff(monkeypatch, error_type):
    operator = TerminalOperator(operator_id="test-operator")

    def interrupted_input(prompt):
        raise error_type()

    monkeypatch.setattr("builtins.input", interrupted_input)

    outcome = operator.handle(_make_request())

    assert outcome.resolution == InterventionResolution.CANCELLED


def test_terminal_operator_reprompts_for_invalid_choices(monkeypatch):
    operator = TerminalOperator(operator_id="test-operator")

    answers = iter([
    "invalid",  # Invalid resolution
    "d",        # Resolved
    "invalid",  # Invalid action summary
    "2",        # Dismissed a blocking dialog
    "invalid",  # Invalid incident classification
    "2",        # Recoverable condition
    ])
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: next(answers),
    )

    outcome = operator.handle(_make_request())

    assert outcome.resolution == InterventionResolution.RESOLVED
    assert outcome.action_summary == ACTION_SUMMARIES["2"]
    assert outcome.incident_classification== IncidentClassification.RECOVERABLE_CONDITION


def test_terminal_operator_requires_nonempty_operator_id():
    with pytest.raises(ValueError):
        TerminalOperator(operator_id="   ")


# ---------------------------------------------------------
# Replay integration tests
#
# Use the real ReplayFlow, ReplayEngine, and HandoffManager.
# Browser actions, checkpoint checks, and outcome detection
# are faked to isolate orchestration behavior.
# ---------------------------------------------------------


@pytest.fixture
def replay_handoff_case(tmp_path, monkeypatch):
    target_url = "https://bank.example.test/start"
    expected_url = "https://bank.example.test/members/123"

    artifact = CapabilityArtifact(
        schema_version="1.0",
        capability_id="test-read-only-member-lookup",
        description="Synthetic read-only workflow for handoff tests.",
        inputs=[
            CapabilityInput(
                name="member_id",
                type="string",
                required=True,
                description="Synthetic member identifier.",
            ),
        ],
        actions=[
            CapabilityAction(
                action=ActionType.CLICK,
                target=CapabilityTarget(
                    role="button",
                    name="Open member",
                ),
            ),
            CapabilityAction(
                action=ActionType.CLICK,
                target=CapabilityTarget(
                    role="button",
                    name="View savings",
                ),
            ),
        ],
        checkpoints=[
            CapabilityCheckpoint(
                after_action=1,
                url_pattern="/members/{{member_id}}",
                required_text=["Member {{member_id}}"],
            ),
        ],
        # Output extraction is outside these orchestration tests.
        outputs=[],
    )

    page = Mock()
    page.url = target_url
    page.is_closed.return_value = False
    page.checkpoint_text_visible = False

    browser = Mock()
    browser.page = page
    def capture_handoff_screenshot(*, evidence_dir, intervention_id):
        # Screenshot must be captured while the original browser
        # is still open, before control passes to the operator.
        assert page.is_closed() is False

        screenshot_dir = Path(evidence_dir) / "screenshots"
        screenshot_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        screenshot_path = screenshot_dir / f"{intervention_id}.png"

        screenshot_path.write_bytes(
            b"synthetic-screenshot-data"
        )

        return str(screenshot_path)


    browser.capture_handoff_screenshot.side_effect = (
        capture_handoff_screenshot
    )

    def open_browser(url):
        page.url = url

    def close_browser():
        page.is_closed.return_value = True

    browser.open.side_effect = open_browser
    browser.close.side_effect = close_browser

    browser_factory = Mock(return_value=browser)
    monkeypatch.setattr(
        replay_flow_module,
        "BrowserSession",
        browser_factory,
    )

    operator = Mock()
    manager = HumanHandoffManager(
        operator=operator,
        evidence_dir=tmp_path / "handoff",
    )

    engines = []

    def create_engine(*args, **kwargs):
        engine = ReplayEngine(*args, **kwargs)

        engine.executor = Mock()
        engine.executor.execute.return_value = ReplayActionResult(
            success=True,
            status=ReplayActionStatus.SUCCESS,
            reason="Synthetic action completed.",
            action_may_have_executed=True,
        )

        engine.business_outcome_detector = Mock()
        engine.business_outcome_detector.detect.return_value = None

        engine.evidence_recorder = Mock()
        engine.evidence_recorder.record.return_value = []

        engine.checkpoint_validator = Mock()

        # Simulate a checkpoint that remains blocked after bounded recovery.
        engine.checkpoint_validator.wait_and_validate.return_value = (
            False,
            "Synthetic checkpoint is blocked.",
        )

        def validate_checkpoint(**kwargs):
            assert kwargs["page"] is page
            assert kwargs["inputs"] == {"member_id": "123"}

            verified = (
                not page.is_closed()
                and page.url == expected_url
                and page.checkpoint_text_visible
            )

            return verified, "Synthetic checkpoint verification."

        engine.checkpoint_validator.validate.side_effect = (
            validate_checkpoint
        )

        engines.append(engine)
        return engine

    monkeypatch.setattr(
        replay_flow_module,
        "ReplayEngine",
        create_engine,
    )

    flow = replay_flow_module.ReplayFlow(
        target_url=target_url,
        handoff_manager=manager,
        checkpoint_resume_capability_ids=frozenset({
            artifact.capability_id,
        }),
    )

    return SimpleNamespace(
        artifact=artifact,
        inputs={"member_id": "123"},
        page=page,
        browser=browser,
        browser_factory=browser_factory,
        operator=operator,
        manager=manager,
        engines=engines,
        flow=flow,
        expected_url=expected_url,
    )


def _run_replay_handoff_case(case):
    return case.flow(
        artifact=case.artifact,
        business_outcome_rules=(),
        inputs=case.inputs,
    )


def _integration_operator_outcome(
    request,
    resolution=InterventionResolution.RESOLVED,
):
    return InterventionOutcome(
        intervention_id=request.intervention_id,
        resolution=resolution,
        operator_id="integration-test-operator",
        action_summary=ACTION_SUMMARIES["3"],
    )


def test_replay_handoff_preserves_browser_and_does_not_repeat_action(
    replay_handoff_case,
):
    case = replay_handoff_case

    def handle(request):
        engine = case.engines[0]

        assert request.phase == ExecutionPhase.REPLAY
        assert request.current_step == 1
        assert request.capability_id == case.artifact.capability_id

        assert case.manager.state.status == InterventionStatus.HUMAN_ACTIVE
        assert case.manager.state.control_owner == ControlOwner.HUMAN

        # The original browser remains open and the next action has not run.
        assert engine.page is case.page
        assert engine.executor.execute.call_count == 1
        case.browser.close.assert_not_called()
        assert case.page.is_closed() is False

        # Simulate the operator restoring the expected application state.
        case.page.url = case.expected_url
        case.page.checkpoint_text_visible = True

        return _integration_operator_outcome(request)

    case.operator.handle.side_effect = handle

    result = _run_replay_handoff_case(case)
    engine = case.engines[0]

    assert result.status == ReplayStatus.SUCCESS
    assert result.human_assisted is True
    assert result.intervention_count == 1
    assert result.completed_steps == 2

    executed_names = [
        call.args[0].target.name
        for call in engine.executor.execute.call_args_list
    ]

    assert executed_names == [
        "Open member",
        "View savings",
    ]

    engine.checkpoint_validator.validate.assert_called_once()
    case.operator.handle.assert_called_once()

    assert case.manager.state.status == InterventionStatus.RESOLVED
    assert case.manager.state.control_owner == ControlOwner.AUTOMATION

    case.browser_factory.assert_called_once_with(headless=False)
    case.browser.start.assert_called_once()
    case.browser.open.assert_called_once()
    case.browser.close.assert_called_once()
    assert case.page.is_closed() is True

    intervention_id = case.manager.state.request.intervention_id
    journal = case.manager.evidence_dir / f"{intervention_id}.jsonl"

    assert journal.is_file()
    assert str(journal) in result.evidence_refs
    assert case.browser.capture_handoff_screenshot.call_count == 1

    assert case.manager.state.request.screenshot_ref in (
        result.evidence_refs
    )

    records = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]

    assert [record["event"] for record in records] == [
        "intervention_requested",
        "human_control_started",
        "human_control_returned",
        "resume_verified",
    ]


@pytest.mark.parametrize(
    "resolution",
    [
        InterventionResolution.CANCELLED,
        InterventionResolution.UNRESOLVED,
    ],
)
def test_replay_cancelled_or_unresolved_handoff_stops_execution(
    replay_handoff_case,
    resolution,
):
    case = replay_handoff_case

    def handle(request):
        case.browser.close.assert_not_called()

        return _integration_operator_outcome(
            request,
            resolution=resolution,
        )

    case.operator.handle.side_effect = handle

    result = _run_replay_handoff_case(case)
    engine = case.engines[0]

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.failed_step == 1
    assert result.completed_steps == 0
    assert result.human_assisted is False

    engine.executor.execute.assert_called_once()
    engine.checkpoint_validator.validate.assert_not_called()

    assert case.manager.state.status == InterventionStatus.CANCELLED
    case.browser.close.assert_called_once()


def test_replay_operator_finished_does_not_bypass_verification(
    replay_handoff_case,
):
    case = replay_handoff_case

    def handle(request):
        # The operator says "finished" but leaves the checkpoint blocked.
        return _integration_operator_outcome(request)

    case.operator.handle.side_effect = handle

    result = _run_replay_handoff_case(case)
    engine = case.engines[0]

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.completed_steps == 0
    assert result.human_assisted is False

    engine.executor.execute.assert_called_once()
    engine.checkpoint_validator.validate.assert_called_once()

    assert case.manager.state.status == InterventionStatus.CANCELLED
    case.browser.close.assert_called_once()


def test_replay_timeout_is_never_automatically_retried_or_skipped(
    replay_handoff_case,
):
    case = replay_handoff_case

    def handle(request):
        engine = case.engines[0]

        assert engine.executor.execute.call_count == 1
        case.browser.close.assert_not_called()

        # Even an apparently restored page and "finished" response cannot
        # authorize continuation after an uncertain action in this version.
        case.page.url = case.expected_url
        case.page.checkpoint_text_visible = True

        return _integration_operator_outcome(request)

    case.operator.handle.side_effect = handle

    engine_factory = replay_flow_module.ReplayEngine

    def create_timing_out_engine(*args, **kwargs):
        engine = engine_factory(*args, **kwargs)

        engine.executor.execute.return_value = ReplayActionResult(
            success=False,
            status=ReplayActionStatus.TIMEOUT,
            reason="Synthetic timeout after action dispatch.",
            action_may_have_executed=True,
        )

        return engine

    # Limit this replacement to this test.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            replay_flow_module,
            "ReplayEngine",
            create_timing_out_engine,
        )

        result = _run_replay_handoff_case(case)

    engine = case.engines[0]

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.error_code == "timeout"
    assert result.action_may_have_executed is True
    assert result.completed_steps == 0

    engine.executor.execute.assert_called_once()
    engine.checkpoint_validator.wait_and_validate.assert_not_called()
    engine.checkpoint_validator.validate.assert_not_called()

    case.operator.handle.assert_called_once()
    assert case.manager.state.status == InterventionStatus.CANCELLED
    case.browser.close.assert_called_once()


def test_replay_capability_without_opt_in_cannot_resume(
    replay_handoff_case,
):
    case = replay_handoff_case
    case.flow.checkpoint_resume_capability_ids = frozenset()

    def handle(request):
        case.page.url = case.expected_url
        case.page.checkpoint_text_visible = True

        return _integration_operator_outcome(request)

    case.operator.handle.side_effect = handle

    result = _run_replay_handoff_case(case)
    engine = case.engines[0]

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.human_assisted is False

    engine.executor.execute.assert_called_once()
    engine.checkpoint_validator.validate.assert_not_called()

    assert case.manager.state.status == InterventionStatus.CANCELLED
    case.browser.close.assert_called_once()


def test_replay_operator_exception_stops_and_closes_browser(
    replay_handoff_case,
):
    case = replay_handoff_case
    case.operator.handle.side_effect = RuntimeError(
        "PRIVATE_EXCEPTION_SENTINEL"
    )

    result = _run_replay_handoff_case(case)
    engine = case.engines[0]

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.error_code == "handoff_error"
    assert "PRIVATE_EXCEPTION_SENTINEL" not in result.model_dump_json()

    engine.executor.execute.assert_called_once()

    assert case.manager.state.status == InterventionStatus.CANCELLED
    assert case.manager.state.control_owner == ControlOwner.AUTOMATION
    case.browser.close.assert_called_once()


def test_terminal_operator_hard_failure_cannot_resume(
    monkeypatch,
):
    operator = TerminalOperator(
        operator_id="test-operator",
    )

    answers = iter([
        "d",  # Operator initially reports intervention resolved
        "1",  # Inspected the application
        "3",  # Classifies the incident as a hard failure
    ])

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: next(answers),
    )

    outcome = operator.handle(_make_request())

    assert (
        outcome.incident_classification
        == IncidentClassification.HARD_FAILURE
    )

    assert (
        outcome.resolution
        == InterventionResolution.UNRESOLVED
    )

    assert outcome.may_attempt_resume is False