from app.agent.schemas.discovery import ActionType, BrowserAction
from app.agent.schemas.recording import RecordedState, RecordedTransition
from app.agent.recording.trajectory_recorder import TrajectoryRecorder

def make_state(name: str) -> RecordedState:
    return RecordedState(
        url=f"http://test/{name}",
        observation=f"State {name}",
        fingerprint=name,
    )


def make_transition(
    step: int,
    before_state: RecordedState,
    after_state: RecordedState,
    action_name: str,
) -> RecordedTransition:
    action = BrowserAction(
        action=ActionType.CLICK,
        target_ref=f"ref-{step}",
        target_role="button",
        target_name=action_name,
        reason=f"Move from {before_state.fingerprint} to {after_state.fingerprint}",
    )

    return RecordedTransition(
        step=step,
        before_state=before_state,
        action=action,
        after_state=after_state,
        outcome_reason="Test transition succeeded.",
    )


def test_backtracking_cleanup():
    recorder = TrajectoryRecorder()

    state_a = make_state("A")
    state_b = make_state("B")
    state_c = make_state("C")
    state_d = make_state("D")

    recorder.initialize(state_a)

    # A -> B
    recorder.record_transition(
        make_transition(
            step=1,
            before_state=state_a,
            after_state=state_b,
            action_name="Go to B",
        )
    )

    # B -> C
    recorder.record_transition(
        make_transition(
            step=2,
            before_state=state_b,
            after_state=state_c,
            action_name="Go to C",
        )
    )

    # C -> B
    # This should cause the recorder to remove the B -> C detour
    # from the candidate path.
    recorder.record_transition(
        make_transition(
            step=3,
            before_state=state_c,
            after_state=state_b,
            action_name="Return to B",
        )
    )

    # B -> D
    recorder.record_transition(
        make_transition(
            step=4,
            before_state=state_b,
            after_state=state_d,
            action_name="Go to D",
        )
    )

    execution_trace = recorder.get_execution_trace()
    candidate_path = recorder.get_candidate_path()

    # The evidence trace must preserve everything.
    assert len(execution_trace) == 4

    assert [
        transition.action.target_name
        for transition in execution_trace
    ] == [
        "Go to B",
        "Go to C",
        "Return to B",
        "Go to D",
    ]

    # The candidate path should remove the detour:
    #
    # A -> B -> C -> B -> D
    #
    # becomes:
    #
    # A -> B -> D
    assert len(candidate_path) == 2

    assert [
        transition.action.target_name
        for transition in candidate_path
    ] == [
        "Go to B",
        "Go to D",
    ]
def test_same_state_transition_is_preserved():
    recorder = TrajectoryRecorder()

    state_a = make_state("A")
    state_b = make_state("B")

    recorder.initialize(state_a)

    # A -> B
    recorder.record_transition(
        make_transition(
            step=1,
            before_state=state_a,
            after_state=state_b,
            action_name="Go to B",
        )
    )

    # B -> B
    #
    # Simulates an action such as FILL that succeeds but does not
    # produce a different observable browser-state fingerprint.
    recorder.record_transition(
        make_transition(
            step=2,
            before_state=state_b,
            after_state=state_b,
            action_name="Fill Member ID",
        )
    )

    candidate_path = recorder.get_candidate_path()

    assert len(candidate_path) == 2

    assert [
        transition.action.target_name
        for transition in candidate_path
    ] == [
        "Go to B",
        "Fill Member ID",
    ]


if __name__ == "__main__":
    test_backtracking_cleanup()
    test_same_state_transition_is_preserved()

    print("All trajectory recorder tests passed.")