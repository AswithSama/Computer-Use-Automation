from unittest.mock import Mock

from app.agent.replay.executor import ReplayActionExecutor
from app.agent.replay.models import ReplayActionStatus
from app.agent.schemas.capability import (
    CapabilityAction,
    CapabilityTarget,
)
from app.agent.schemas.discovery import ActionType

BASE_URL = "http://127.0.0.1:8000"


def make_page():
    page = Mock()
    page.url = f"{BASE_URL}/members"

    return page


def test_navigate_executes_resolved_relative_url():
    page = make_page()

    executor = ReplayActionExecutor(page)

    action = CapabilityAction(
        action=ActionType.NAVIGATE,
        url="/members/67890",
    )

    result = executor.execute(action)

    assert result.success is True
    assert result.status == ReplayActionStatus.SUCCESS

    page.goto.assert_called_once_with(
        f"{BASE_URL}/members/67890",
        wait_until="domcontentloaded",
    )


def test_navigation_requires_url():
    page = make_page()

    executor = ReplayActionExecutor(page)

    action = CapabilityAction(
        action=ActionType.NAVIGATE,
    )

    result = executor.execute(action)

    assert result.success is False
    assert result.status == ReplayActionStatus.INVALID_ACTION
    assert result.action_may_have_executed is False

    page.goto.assert_not_called()


def test_wait_executes_without_target():
    page = make_page()

    executor = ReplayActionExecutor(page)

    action = CapabilityAction(
        action=ActionType.WAIT,
    )

    result = executor.execute(action)

    assert result.success is True
    assert result.status == ReplayActionStatus.SUCCESS

    page.wait_for_timeout.assert_called_once_with(1000)


def test_go_back_remains_unsupported_in_replay():
    page = make_page()

    executor = ReplayActionExecutor(page)

    action = CapabilityAction(
        action=ActionType.GO_BACK,
    )

    result = executor.execute(action)

    assert result.success is False
    assert result.status == ReplayActionStatus.INVALID_ACTION

    page.go_back.assert_not_called()


def test_click_still_uses_semantic_target():
    page = make_page()

    locator = page.get_by_role.return_value
    locator.count.return_value = 1

    executor = ReplayActionExecutor(page)

    action = CapabilityAction(
        action=ActionType.CLICK,
        target=CapabilityTarget(
            role="button",
            name="View Savings",
        ),
    )

    result = executor.execute(action)

    assert result.success is True
    assert result.status == ReplayActionStatus.SUCCESS

    page.get_by_role.assert_called_once_with(
        "button",
        name="View Savings",
        exact=False,
    )

    locator.click.assert_called_once()


def test_fill_still_requires_value():
    page = make_page()

    executor = ReplayActionExecutor(page)

    action = CapabilityAction(
        action=ActionType.FILL,
        target=CapabilityTarget(
            role="textbox",
            name="Member ID",
        ),
        value=None,
    )

    result = executor.execute(action)

    assert result.success is False
    assert result.status == ReplayActionStatus.INVALID_ACTION