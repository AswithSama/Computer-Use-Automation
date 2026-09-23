
from dataclasses import dataclass, replace

import pytest

import app.agent.orchestration.path_optimization as optimization
from app.agent.orchestration.candidate_path_verifier import (
    VerifiedCandidatePath,
)
from app.agent.recording.state_fingerprint import (
    build_state_fingerprint,
)
from app.agent.schemas.discovery import ActionType, BrowserAction
from app.agent.schemas.recording import (
    RecordedState,
    RecordedTransition,
)

URL = "http://127.0.0.1:8000/demo"


def state(observation: str, url: str = URL) -> RecordedState:
    return RecordedState(
        url=url,
        observation=observation,
        fingerprint=build_state_fingerprint(
            url=url,
            observation=observation,
        ),
    )


def make_transition(
    step: int,
    name: str,
    before: RecordedState,
    after: RecordedState,
    action_type: ActionType = ActionType.CLICK,
) -> RecordedTransition:
    return RecordedTransition(
        step=step,
        before_state=before,
        action=BrowserAction(
            action=action_type,
            target_role=(
                "textbox"
                if action_type == ActionType.FILL
                else "button"
            ),
            target_name=name,
            value=(
                "synthetic-input"
                if action_type == ActionType.FILL
                else None
            ),
            reason="Synthetic integration-test action.",
        ),
        after_state=after,
        outcome_reason="Synthetic action completed.",
    )


def make_same_page_path(
    names: tuple[str, ...] = ("A", "B", "C", "D", "E"),
    action_types: tuple[ActionType, ...] | None = None,
) -> list[RecordedTransition]:
    if action_types is None:
        action_types = (ActionType.CLICK,) * len(names)

    assert len(names) == len(action_types)

    return [
        make_transition(
            step=index + 1,
            name=name,
            before=state(f"Screen {index}"),
            after=state(f"Screen {index + 1}"),
            action_type=action_types[index],
        )
        for index, name in enumerate(names)
    ]


@dataclass
class FakeDiscoveryResult:
    candidate_path: list[RecordedTransition]
    execution_trace: list[RecordedTransition]
    final_state: RecordedState
    human_assisted: bool = False
    intervention_count: int = 0

    def model_copy(self, *, update):
        # Reproduce the Pydantic model_copy behavior needed by
        # the optimization helper, without constructing a full
        # discovery result containing unrelated output data.
        return replace(self, **update)


def make_result(
    path: list[RecordedTransition] | None = None,
    *,
    human_assisted: bool = False,
    intervention_count: int = 0,
) -> FakeDiscoveryResult:
    if path is None:
        path = make_same_page_path()

    return FakeDiscoveryResult(
        candidate_path=path,
        execution_trace=list(path),
        final_state=path[-1].after_state,
        human_assisted=human_assisted,
        intervention_count=intervention_count,
    )


class FakeVerifier:
    """
    Simulates deterministic verification.

    A candidate succeeds only when it includes every name in
    required_names. This allows us to test the integration
    without opening a browser.
    """

    required_names = ("C", "E")
    baseline_fails = False
    verify_calls = []
    record_calls = 0

    def __init__(self, **kwargs):
        self.options = kwargs

    @staticmethod
    def names(transitions):
        return tuple(
            transition.action.target_name
            for transition in transitions
        )

    def verify(
        self,
        *,
        transitions,
        initial_state,
        expected_final_state,
    ):
        names = self.names(transitions)
        type(self).verify_calls.append(names)

        if type(self).baseline_fails:
            return False

        return all(
            name in names
            for name in type(self).required_names
        )

    def verify_and_record(
        self,
        *,
        transitions,
        initial_state,
        expected_final_state,
    ):
        type(self).record_calls += 1

        names = self.names(transitions)

        if not all(
            name in names
            for name in type(self).required_names
        ):
            return None

        # Simulate a fresh-browser replay: build new, adjacent
        # before/after states rather than returning the old ones.
        replayed = []
        previous_state = initial_state

        for index, transition in enumerate(transitions):
            is_last = index == len(transitions) - 1

            next_state = (
                expected_final_state
                if is_last
                else state(
                    f"Freshly replayed {transition.action.target_name}"
                )
            )

            replayed.append(
                transition.model_copy(
                    update={
                        "before_state": previous_state,
                        "after_state": next_state,
                    }
                )
            )

            previous_state = next_state

        return VerifiedCandidatePath(
            transitions=replayed,
            final_state=expected_final_state,
        )


@pytest.fixture(autouse=True)
def reset_fake_verifier():
    FakeVerifier.required_names = ("C", "E")
    FakeVerifier.baseline_fails = False
    FakeVerifier.verify_calls = []
    FakeVerifier.record_calls = 0


def install_fake_verifier(monkeypatch):
    monkeypatch.setattr(
        optimization,
        "CandidatePathVerifier",
        FakeVerifier,
    )


def test_verified_cluster_reduces_abcde_to_ce(monkeypatch):
    install_fake_verifier(monkeypatch)

    original = make_result()
    original_trace = original.execution_trace
    original_path = original.candidate_path

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
    )

    assert [
        transition.action.target_name
        for transition in optimized.candidate_path
    ] == ["C", "E"]

    assert [
        transition.step
        for transition in optimized.candidate_path
    ] == [3, 5]

    # The original discovery result remains unchanged.
    assert optimized is not original
    assert original.candidate_path is original_path
    assert len(original.candidate_path) == 5

    # Full execution history is never shortened.
    assert optimized.execution_trace is original_trace
    assert len(optimized.execution_trace) == 5

    # Baseline and removal trials were checked; the accepted
    # sequence was replayed once more to capture fresh evidence.
    assert FakeVerifier.verify_calls[0] == (
        "A", "B", "C", "D", "E"
    )
    assert FakeVerifier.record_calls == 1


def test_shortened_path_uses_fresh_adjacent_states(monkeypatch):
    install_fake_verifier(monkeypatch)

    original = make_result()

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
    )

    first, second = optimized.candidate_path

    assert (
        first.before_state.fingerprint
        == original.candidate_path[0].before_state.fingerprint
    )

    assert (
        first.after_state.fingerprint
        == second.before_state.fingerprint
    )

    assert (
        second.after_state.fingerprint
        == original.final_state.fingerprint
    )

    # E's original before-state came after A, B, C and D.
    # The verified before-state now comes directly after C.
    assert (
        second.before_state.fingerprint
        != original.candidate_path[4].before_state.fingerprint
    )


def test_no_cluster_does_not_create_a_verifier(monkeypatch):
    class UnexpectedVerifier:
        def __init__(self, **kwargs):
            raise AssertionError(
                "A browser verifier must not be created "
                "when there is no same-page cluster."
            )

    monkeypatch.setattr(
        optimization,
        "CandidatePathVerifier",
        UnexpectedVerifier,
    )

    path = [
        make_transition(
            1,
            "A",
            state("Initial", URL),
            state("First page", f"{URL}/first"),
        ),
        make_transition(
            2,
            "B",
            state("First page", f"{URL}/first"),
            state("Second page", f"{URL}/second"),
        ),
    ]

    original = make_result(path)

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
    )

    assert optimized is original


@pytest.mark.parametrize(
    ("human_assisted", "intervention_count"),
    [
        (True, 0),
        (False, 1),
    ],
)
def test_human_assisted_run_is_never_minimized(
    monkeypatch,
    human_assisted,
    intervention_count,
):
    class UnexpectedVerifier:
        def __init__(self, **kwargs):
            raise AssertionError(
                "Human-assisted discovery must not be minimized."
            )

    monkeypatch.setattr(
        optimization,
        "CandidatePathVerifier",
        UnexpectedVerifier,
    )

    original = make_result(
        human_assisted=human_assisted,
        intervention_count=intervention_count,
    )

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
    )

    assert optimized is original


def test_failed_baseline_keeps_original_path(monkeypatch):
    install_fake_verifier(monkeypatch)
    FakeVerifier.baseline_fails = True

    original = make_result()

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
    )

    assert optimized is original
    assert FakeVerifier.record_calls == 0


def test_incompatible_shortened_sequence_is_rejected(monkeypatch):
    install_fake_verifier(monkeypatch)

    original = make_result()

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
        required_action_sequence=(
            ActionType.CLICK,
            ActionType.CLICK,
            ActionType.CLICK,
            ActionType.CLICK,
        ),
    )

    # The verifier can reduce A-B-C-D-E to C-E, but that
    # result does not satisfy this caller's four-action contract.
    assert optimized is original
    assert FakeVerifier.record_calls == 0


def test_compatible_four_action_reduction_is_accepted(monkeypatch):
    install_fake_verifier(monkeypatch)

    FakeVerifier.required_names = ("B", "C", "D", "E")

    path = make_same_page_path(
        action_types=(
            ActionType.CLICK,  # A: unnecessary exploratory click
            ActionType.CLICK,  # B: search
            ActionType.FILL,   # C: member ID
            ActionType.CLICK,  # D: submit
            ActionType.CLICK,  # E: savings
        )
    )

    original = make_result(path)

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
        required_action_sequence=(
            ActionType.CLICK,
            ActionType.FILL,
            ActionType.CLICK,
            ActionType.CLICK,
        ),
    )

    assert [
        transition.action.target_name
        for transition in optimized.candidate_path
    ] == ["B", "C", "D", "E"]

    assert [
        transition.action.action
        for transition in optimized.candidate_path
    ] == [
        ActionType.CLICK,
        ActionType.FILL,
        ActionType.CLICK,
        ActionType.CLICK,
    ]

    assert len(optimized.execution_trace) == 5
    assert FakeVerifier.record_calls == 1


def test_existing_canonical_path_skips_minimization(monkeypatch):
    class UnexpectedVerifier:
        def __init__(self, **kwargs):
            raise AssertionError(
                "An already canonical savings path "
                "should not start a minimization trial."
            )

    monkeypatch.setattr(
        optimization,
        "CandidatePathVerifier",
        UnexpectedVerifier,
    )

    canonical_actions = (
        ActionType.CLICK,
        ActionType.FILL,
        ActionType.CLICK,
        ActionType.CLICK,
    )

    path = make_same_page_path(
        names=("Search", "Member ID", "Submit", "Savings"),
        action_types=canonical_actions,
    )

    original = make_result(path)

    optimized = optimization.minimize_discovery_result(
        original,
        policy_engine=object(),
        required_action_sequence=canonical_actions,
    )

    assert optimized is original