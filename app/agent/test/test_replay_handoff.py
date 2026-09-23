"""Replay-time handoff integration tests.

Scope: the real ReplayFlow, ReplayEngine, and HumanHandoffManager wired
together. Browser actions, checkpoint checks, and outcome detection are
faked so the orchestration/control-transfer behavior is what's under test —
this is the strongest evidence for "resume on the same live session" rather
than a fresh one, and for timeout/cancellation never being silently retried.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.agent.orchestration.replay_flow as replay_flow_module
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.models import (
    ControlOwner,
    ExecutionPhase,
    InterventionOutcome,
    InterventionResolution,
    InterventionStatus,
)
from app.agent.handoff.operator import ACTION_SUMMARIES
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
