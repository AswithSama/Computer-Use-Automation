from unittest.mock import Mock

import pytest

from app.agent.discovery.executor import ActionExecutor
from app.agent.policy.config import load_demo_banking_config
from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import PolicyViolation
from app.agent.policy.models import PolicyDecision
from app.agent.schemas.discovery import ActionType, BrowserAction


BASE_URL = "http://127.0.0.1:8000"


def make_executor(href: str):
    page = Mock()
    page.url = f"{BASE_URL}/"

    locator = page.get_by_role.return_value
    locator.count.return_value = 1
    locator.get_attribute.return_value = href

    decisions = []

    executor = ActionExecutor(
        page=page,
        allowed_host="127.0.0.1",
        policy_engine=PolicyEngine(
            load_demo_banking_config()
        ),
        policy_profile_id="read_only_discovery",
        on_policy_decision=decisions.append,
    )

    action = BrowserAction(
        action=ActionType.CLICK,
        target_role="link",
        target_name="Test link",
        reason="Test link-destination enforcement.",
    )

    return executor, action, locator, decisions


def test_blocked_route_is_not_clicked():
    executor, action, locator, decisions = make_executor(
        "/operations"
    )

    with pytest.raises(PolicyViolation) as exc_info:
        executor.execute(action)

    assert exc_info.value.result.code == "route_blocked"
    assert decisions[-1].decision == PolicyDecision.BLOCKED

    locator.click.assert_not_called()


def test_external_link_is_not_clicked():
    executor, action, locator, decisions = make_executor(
        "https://example.com/"
    )

    with pytest.raises(PolicyViolation) as exc_info:
        executor.execute(action)

    assert exc_info.value.result.code == "origin_not_allowed"
    assert decisions[-1].decision == PolicyDecision.BLOCKED

    locator.click.assert_not_called()


def test_allowed_link_is_clicked():
    executor, action, locator, decisions = make_executor(
        "/members"
    )

    executor.execute(action)

    assert decisions[-1].decision == PolicyDecision.ALLOWED
    locator.click.assert_called_once()


def test_savings_profile_cannot_click_accounts_link():
    executor, action, locator, decisions = make_executor(
        "/accounts"
    )

    executor.policy_profile_id = "get_savings_balance"

    with pytest.raises(PolicyViolation) as exc_info:
        executor.execute(action)

    assert exc_info.value.result.code == "route_not_allowed"
    assert decisions[-1].decision == PolicyDecision.BLOCKED

    locator.click.assert_not_called()

def make_navigation_executor():
    page = Mock()
    page.url = f"{BASE_URL}/"

    decisions = []

    executor = ActionExecutor(
        page=page,
        allowed_host="127.0.0.1",
        policy_engine=PolicyEngine(
            load_demo_banking_config()
        ),
        policy_profile_id="read_only_discovery",
        on_policy_decision=decisions.append,
    )

    return executor, page, decisions


def navigation_action(url: str) -> BrowserAction:
    return BrowserAction(
        action=ActionType.NAVIGATE,
        url=url,
        reason="Test direct-navigation policy enforcement.",
    )


def test_direct_navigation_to_blocked_route_never_calls_goto():
    executor, page, decisions = make_navigation_executor()

    with pytest.raises(PolicyViolation) as exc_info:
        executor.execute(
            navigation_action("/operations")
        )

    assert exc_info.value.result.code == "route_blocked"
    assert decisions[-1].decision == PolicyDecision.BLOCKED

    page.goto.assert_not_called()


def test_direct_navigation_to_external_origin_never_calls_goto():
    executor, page, decisions = make_navigation_executor()

    with pytest.raises(PolicyViolation) as exc_info:
        executor.execute(
            navigation_action("https://example.com/members")
        )

    assert exc_info.value.result.code == "origin_not_allowed"
    assert decisions[-1].decision == PolicyDecision.BLOCKED

    page.goto.assert_not_called()


def test_direct_navigation_to_other_port_is_blocked():
    executor, page, decisions = make_navigation_executor()

    with pytest.raises(PolicyViolation) as exc_info:
        executor.execute(
            navigation_action(
                "http://127.0.0.1:9000/members"
            )
        )

    assert exc_info.value.result.code == "origin_not_allowed"
    assert decisions[-1].decision == PolicyDecision.BLOCKED

    page.goto.assert_not_called()


def test_direct_navigation_to_allowed_route_calls_goto():
    executor, page, decisions = make_navigation_executor()

    executor.execute(
        navigation_action("/members")
    )

    assert decisions[-1].decision == PolicyDecision.ALLOWED

    page.goto.assert_called_once_with(
        f"{BASE_URL}/members",
        wait_until="domcontentloaded",
    )


def test_direct_navigation_respects_capability_profile():
    executor, page, decisions = make_navigation_executor()

    executor.policy_profile_id = "get_savings_balance"

    with pytest.raises(PolicyViolation) as exc_info:
        executor.execute(
            navigation_action("/accounts")
        )

    assert exc_info.value.result.code == "route_not_allowed"
    assert decisions[-1].decision == PolicyDecision.BLOCKED

    page.goto.assert_not_called()