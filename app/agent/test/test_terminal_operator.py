"""TerminalOperator tests.

Scope: the CLI operator surface a human uses to resolve an intervention —
input parsing, reprompting on bad input, cancellation, and interruption
handling. Uses monkeypatched builtins.input; no manager or replay wiring.
"""

import pytest

from app.agent.handoff.models import (
    ExecutionPhase,
    IncidentClassification,
    InterventionRequest,
    InterventionResolution,
)
from app.agent.handoff.operator import (
    ACTION_SUMMARIES,
    TerminalOperator,
)


def _make_request():
    return InterventionRequest(
        run_id="run-123",
        phase=ExecutionPhase.REPLAY,
        reason="Unexpected dialog blocked replay.",
        browser_session_id="browser-123",
        current_step=3,
    )


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
