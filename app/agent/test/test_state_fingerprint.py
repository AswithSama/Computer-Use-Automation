from app.agent.discovery.browser import BrowserSession
from app.agent.discovery.models import ActionType, BrowserAction
from app.agent.recording.models import RecordedState, RecordedTransition
from app.agent.recording.state_fingerprint import build_state_fingerprint
from app.agent.recording.trajectory_recorder import TrajectoryRecorder


def capture_state(browser: BrowserSession) -> RecordedState:
    """
    Capture the current real browser state.
    """
    url = browser.page.url
    observation = browser.observe()

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
    before_state: RecordedState,
    after_state: RecordedState,
    action_name: str,
) -> RecordedTransition:
    """
    Create a transition using real captured browser states.
    """
    action = BrowserAction(
        action=ActionType.NAVIGATE,
        url=after_state.url,
        reason=action_name,
    )

    return RecordedTransition(
        step=step,
        before_state=before_state,
        action=action,
        after_state=after_state,
        outcome_reason="Real browser navigation succeeded.",
    )


def test_real_browser_backtracking():
    browser = BrowserSession(headless=False)
    recorder = TrajectoryRecorder()

    try:
        browser.start()

        # ==================================================
        # STATE B
        # Start on the Members page.
        # ==================================================

        browser.open("http://127.0.0.1:8000/members")

        members_first = capture_state(browser)

        recorder.initialize(members_first)

        print("\nFIRST MEMBERS STATE")
        print("URL:", members_first.url)
        print("Fingerprint:", members_first.fingerprint)

        # ==================================================
        # B -> C
        # Leave Members and go to Dashboard.
        # ==================================================

        browser.open("http://127.0.0.1:8000/")

        dashboard = capture_state(browser)

        recorder.record_transition(
            make_transition(
                step=1,
                before_state=members_first,
                after_state=dashboard,
                action_name="Members to Dashboard",
            )
        )

        print("\nDASHBOARD STATE")
        print("URL:", dashboard.url)
        print("Fingerprint:", dashboard.fingerprint)

        # ==================================================
        # C -> B
        # Return to Members.
        # ==================================================

        browser.open("http://127.0.0.1:8000/members")

        members_second = capture_state(browser)

        recorder.record_transition(
            make_transition(
                step=2,
                before_state=dashboard,
                after_state=members_second,
                action_name="Dashboard to Members",
            )
        )

        print("\nSECOND MEMBERS STATE")
        print("URL:", members_second.url)
        print("Fingerprint:", members_second.fingerprint)

        # ==================================================
        # Verify fingerprint recognition.
        # ==================================================

        fingerprints_match = (
            members_first.fingerprint
            == members_second.fingerprint
        )

        print("\nMEMBERS FINGERPRINTS MATCH:")
        print(fingerprints_match)

        assert fingerprints_match

        # ==================================================
        # Verify trajectory recording.
        # ==================================================

        execution_trace = recorder.get_execution_trace()
        candidate_path = recorder.get_candidate_path()

        print("\nEXECUTION TRACE:")

        for transition in execution_trace:
            print(
                f"Step {transition.step}: "
                f"{transition.action.reason}"
            )

        print("\nCANDIDATE PATH:")

        if not candidate_path:
            print("(empty)")
        else:
            for transition in candidate_path:
                print(
                    f"Step {transition.step}: "
                    f"{transition.action.reason}"
                )

        # Both actions really happened, so evidence must keep both.
        assert len(execution_trace) == 2

        # Actual execution:
        #
        # Members -> Dashboard -> Members
        #
        # Since we returned to the exact state where we started,
        # the whole detour should disappear from the candidate path.
        assert len(candidate_path) == 0

    finally:
        browser.close()


if __name__ == "__main__":
    test_real_browser_backtracking()

    print("\nReal browser fingerprint + backtracking test passed.")