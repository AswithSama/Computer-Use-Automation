from app.agent.orchestration.candidate_path_verifier import (
    CandidatePathVerifier,
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

BASE_URL = "http://127.0.0.1:8000/test"


class FakeLocator:
    def __init__(
        self,
        page,
        name: str,
    ):
        self.page = page
        self.name = name

    def count(self):
        return 1

    def get_attribute(self, _name):
        return None

    def click(self):
        # C is required before E can produce the successful state.
        if self.name == "C":
            self.page.c_selected = True

        elif self.name == "E":
            if self.page.c_selected:
                self.page.observation = "Goal reached"

        # A, B, and D intentionally have no required effect.

    def fill(self, _value):
        pass


class FakePage:
    def __init__(self):
        self.url = BASE_URL
        self.observation = "Initial"
        self.c_selected = False

    def get_by_role(
        self,
        _role,
        *,
        name,
        exact=False,
    ):
        return FakeLocator(
            self,
            name,
        )

    def wait_for_load_state(
        self,
        _state,
    ):
        pass

    def wait_for_timeout(
        self,
        _milliseconds,
    ):
        pass

    def goto(
        self,
        destination,
        *,
        wait_until,
    ):
        self.url = destination

    def go_back(
        self,
        *,
        wait_until,
    ):
        pass


class FakeBrowserSession:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def start(self):
        pass

    def open(self, url):
        self.page.url = url
        self.page.observation = "Initial"
        self.page.c_selected = False

    def observe(self):
        return self.page.observation

    def close(self):
        self.closed = True


def state(
    observation: str,
) -> RecordedState:

    return RecordedState(
        url=BASE_URL,
        observation=observation,
        fingerprint=build_state_fingerprint(
            url=BASE_URL,
            observation=observation,
        ),
    )


def transition(
    step: int,
    name: str,
) -> RecordedTransition:

    return RecordedTransition(
        step=step,
        before_state=state(
            f"Recorded before {name}"
        ),
        action=BrowserAction(
            action=ActionType.CLICK,
            target_role="button",
            target_name=name,
            reason="Test candidate-path verification.",
        ),
        after_state=state(
            f"Recorded after {name}"
        ),
        outcome_reason="Test action completed.",
    )


def make_verifier():
    return CandidatePathVerifier(
        browser_factory=FakeBrowserSession,
    )


def test_required_subset_reaches_original_final_state():
    verifier = make_verifier()

    candidate = [
        transition(3, "C"),
        transition(5, "E"),
    ]

    result = verifier.verify(
        transitions=candidate,
        initial_state=state("Initial"),
        expected_final_state=state("Goal reached"),
    )

    assert result is True


def test_missing_required_action_fails_verification():
    verifier = make_verifier()

    candidate = [
        transition(5, "E"),
    ]

    result = verifier.verify(
        transitions=candidate,
        initial_state=state("Initial"),
        expected_final_state=state("Goal reached"),
    )

    assert result is False


def test_unnecessary_actions_do_not_prevent_verification():
    verifier = make_verifier()

    candidate = [
        transition(1, "A"),
        transition(2, "B"),
        transition(3, "C"),
        transition(4, "D"),
        transition(5, "E"),
    ]

    result = verifier.verify(
        transitions=candidate,
        initial_state=state("Initial"),
        expected_final_state=state("Goal reached"),
    )

    assert result is True


def test_wrong_expected_final_state_fails():
    verifier = make_verifier()

    candidate = [
        transition(3, "C"),
        transition(5, "E"),
    ]

    result = verifier.verify(
        transitions=candidate,
        initial_state=state("Initial"),
        expected_final_state=state(
            "Some other outcome"
        ),
    )

    assert result is False


def test_each_verification_uses_fresh_browser():
    sessions = []

    def browser_factory():
        browser = FakeBrowserSession()
        sessions.append(browser)
        return browser

    verifier = CandidatePathVerifier(
        browser_factory=browser_factory,
    )

    candidate = [
        transition(3, "C"),
        transition(5, "E"),
    ]

    for _ in range(2):
        assert verifier.verify(
            transitions=candidate,
            initial_state=state("Initial"),
            expected_final_state=state("Goal reached"),
        )

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]

    assert sessions[0].closed is True
    assert sessions[1].closed is True

def test_verified_shortened_path_has_fresh_transition_states():
    verifier = make_verifier()

    verified = verifier.verify_and_record(
        transitions=[
            transition(3, "C"),
            transition(5, "E"),
        ],
        initial_state=state("Initial"),
        expected_final_state=state("Goal reached"),
    )

    assert verified is not None

    assert [
        item.step
        for item in verified.transitions
    ] == [3, 5]

    first, second = verified.transitions

    # The shortened path begins in the real trial's initial state.
    assert first.before_state.fingerprint == state(
        "Initial"
    ).fingerprint

    # The next action starts from the actual state left by C,
    # rather than the state recorded in the original A-B-C-D-E run.
    assert (
        second.before_state.fingerprint
        == first.after_state.fingerprint
    )

    assert verified.final_state.fingerprint == state(
        "Goal reached"
    ).fingerprint