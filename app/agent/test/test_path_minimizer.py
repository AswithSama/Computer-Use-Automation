from app.agent.recording.path_minimizer import (
    PathMinimizer,
)
from app.agent.recording.path_segments import (
    SamePageSegment,
)
from app.agent.recording.state_fingerprint import (
    build_state_fingerprint,
)
from app.agent.schemas.discovery import (
    ActionType,
    BrowserAction,
)
from app.agent.schemas.recording import (
    RecordedState,
    RecordedTransition,
)

URL = "http://127.0.0.1:8000/members/12345"


def state(
    observation: str,
    *,
    url: str = URL,
) -> RecordedState:

    return RecordedState(
        url=url,
        observation=observation,
        fingerprint=build_state_fingerprint(
            url=url,
            observation=observation,
        ),
    )


def transition(
    step: int,
    before: RecordedState,
    after: RecordedState,
    name: str,
) -> RecordedTransition:

    return RecordedTransition(
        step=step,
        before_state=before,
        action=BrowserAction(
            action=ActionType.CLICK,
            target_role="button",
            target_name=name,
            reason="Test action.",
        ),
        after_state=after,
        outcome_reason="Action completed.",
    )


def make_path():
    s0 = state("Initial")
    s1 = state("A selected")
    s2 = state("B selected")
    s3 = state("C selected")
    s4 = state("D selected")

    final = state(
        "Account page",
        url="http://127.0.0.1:8000/accounts/1",
    )

    return [
        transition(1, s0, s1, "A"),
        transition(2, s1, s2, "B"),
        transition(3, s2, s3, "C"),
        transition(4, s3, s4, "D"),
        transition(5, s4, final, "View Account"),
    ]


def action_names(path):
    return [
        transition.action.target_name
        for transition in path
    ]


def test_removes_actions_only_when_verifier_accepts():
    path = make_path()

    segment = SamePageSegment(
        start_index=0,
        end_index=3,
        url=URL,
    )

    def verify(candidate):
        names = action_names(candidate)

        # In this synthetic scenario only D is necessary
        # from the same-page exploratory sequence.
        return (
            "D" in names
            and "View Account" in names
        )

    result = PathMinimizer().minimize(
        transitions=path,
        segment=segment,
        verify=verify,
    )

    assert action_names(result.transitions) == [
        "D",
        "View Account",
    ]

    assert result.attempted_removals == 4
    assert result.accepted_removals == 3


def test_preserves_multiple_required_actions():
    path = make_path()

    segment = SamePageSegment(
        start_index=0,
        end_index=3,
        url=URL,
    )

    def verify(candidate):
        names = action_names(candidate)

        return (
            "B" in names
            and "D" in names
            and "View Account" in names
        )

    result = PathMinimizer().minimize(
        transitions=path,
        segment=segment,
        verify=verify,
    )

    assert action_names(result.transitions) == [
        "B",
        "D",
        "View Account",
    ]


def test_never_removes_actions_outside_segment():
    path = make_path()

    segment = SamePageSegment(
        start_index=1,
        end_index=2,
        url=URL,
    )

    result = PathMinimizer().minimize(
        transitions=path,
        segment=segment,
        verify=lambda candidate: True,
    )

    assert action_names(result.transitions) == [
        "A",
        "D",
        "View Account",
    ]


def test_verifier_exception_preserves_action():
    path = make_path()

    segment = SamePageSegment(
        start_index=0,
        end_index=3,
        url=URL,
    )

    def verify(_candidate):
        raise RuntimeError(
            "Verification environment unavailable."
        )

    result = PathMinimizer().minimize(
        transitions=path,
        segment=segment,
        verify=verify,
    )

    assert result.transitions == path
    assert result.accepted_removals == 0


def test_original_candidate_path_is_not_mutated():
    path = make_path()
    original = list(path)

    segment = SamePageSegment(
        start_index=0,
        end_index=3,
        url=URL,
    )

    PathMinimizer().minimize(
        transitions=path,
        segment=segment,
        verify=lambda candidate: True,
    )

    assert path == original


def test_invalid_segment_is_rejected():
    path = make_path()

    segment = SamePageSegment(
        start_index=0,
        end_index=20,
        url=URL,
    )

    try:
        PathMinimizer().minimize(
            transitions=path,
            segment=segment,
            verify=lambda candidate: True,
        )

        assert False, "Expected ValueError"

    except ValueError:
        pass