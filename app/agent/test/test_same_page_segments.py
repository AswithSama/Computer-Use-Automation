from app.agent.recording.path_segments import (
    SamePageSegmentDetector,
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


def state(
    url: str,
    observation: str,
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
    target_name: str,
) -> RecordedTransition:
    return RecordedTransition(
        step=step,
        before_state=before,
        action=BrowserAction(
            action=ActionType.CLICK,
            target_role="button",
            target_name=target_name,
            reason="Test exploration action.",
        ),
        after_state=after,
        outcome_reason="Test transition completed.",
    )


def test_detects_consecutive_same_page_state_changes():
    url = "http://127.0.0.1:8000/members/12345"

    a = state(url, "Option A not selected")
    b = state(url, "Option A selected")
    c = state(url, "Option B selected")
    d = state(url, "Option C selected")
    e = state(url, "Option D selected")

    path = [
        transition(1, a, b, "Option A"),
        transition(2, b, c, "Option B"),
        transition(3, c, d, "Option C"),
        transition(4, d, e, "Option D"),
    ]

    segments = SamePageSegmentDetector().detect(path)

    assert len(segments) == 1

    segment = segments[0]

    assert segment.start_index == 0
    assert segment.end_index == 3
    assert segment.transition_count == 4
    assert segment.url == url


def test_single_same_page_action_is_not_a_segment():
    url = "http://127.0.0.1:8000/members/12345"

    before = state(url, "Initial")
    after = state(url, "Changed")

    path = [
        transition(
            1,
            before,
            after,
            "Open details",
        )
    ]

    segments = SamePageSegmentDetector().detect(path)

    assert segments == []


def test_unchanged_state_breaks_candidate_segment():
    url = "http://127.0.0.1:8000/members/12345"

    a = state(url, "Initial")
    b = state(url, "Option A selected")

    # Same fingerprint before/after.
    unchanged = b

    c = state(url, "Option B selected")
    d = state(url, "Option C selected")

    path = [
        transition(1, a, b, "Option A"),

        transition(
            2,
            b,
            unchanged,
            "Required action",
        ),

        transition(3, unchanged, c, "Option B"),
        transition(4, c, d, "Option C"),
    ]

    segments = SamePageSegmentDetector().detect(path)

    assert len(segments) == 1

    assert segments[0].start_index == 2
    assert segments[0].end_index == 3


def test_navigation_breaks_same_page_segment():
    member_url = (
        "http://127.0.0.1:8000/members/12345"
    )

    account_url = (
        "http://127.0.0.1:8000/"
        "members/12345/accounts/a1"
    )

    a = state(member_url, "Initial")
    b = state(member_url, "Option A selected")
    c = state(member_url, "Option B selected")

    account = state(
        account_url,
        "Account detail",
    )

    path = [
        transition(1, a, b, "Option A"),
        transition(2, b, c, "Option B"),
        transition(3, c, account, "View Account"),
    ]

    segments = SamePageSegmentDetector().detect(path)

    assert len(segments) == 1
    assert segments[0].start_index == 0
    assert segments[0].end_index == 1


def test_separate_same_page_regions_are_detected_separately():
    member_url = (
        "http://127.0.0.1:8000/members/12345"
    )

    account_url = (
        "http://127.0.0.1:8000/accounts/a1"
    )

    a = state(member_url, "A")
    b = state(member_url, "B")
    c = state(member_url, "C")

    d = state(account_url, "D")
    e = state(account_url, "E")
    f = state(account_url, "F")

    path = [
        transition(1, a, b, "A"),
        transition(2, b, c, "B"),

        # Navigates to another page.
        transition(3, c, d, "Account"),

        transition(4, d, e, "X"),
        transition(5, e, f, "Y"),
    ]

    segments = SamePageSegmentDetector().detect(path)

    assert len(segments) == 2

    assert segments[0].start_index == 0
    assert segments[0].end_index == 1

    assert segments[1].start_index == 3
    assert segments[1].end_index == 4