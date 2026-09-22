from app.agent.policy.config import load_demo_banking_config
from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import PolicyDecision
from app.agent.schemas.discovery import ActionType


BASE_URL = "http://127.0.0.1:8000"


def make_engine() -> PolicyEngine:
    return PolicyEngine(load_demo_banking_config())


def test_savings_balance_routes_are_permitted():
    engine = make_engine()

    permitted_urls = [
        f"{BASE_URL}/",
        f"{BASE_URL}/members",
        f"{BASE_URL}/members?member_id=12345",
        f"{BASE_URL}/members/12345",
        f"{BASE_URL}/members/12345/accounts/account-1",
    ]

    for url in permitted_urls:
        result = engine.check_scope(
            current_url=url,
            profile_id="get_savings_balance",
        )

        assert result.decision == PolicyDecision.ALLOWED, url


def test_operations_route_is_blocked():
    engine = make_engine()

    result = engine.check_scope(
        current_url=f"{BASE_URL}/operations",
        profile_id="read_only_discovery",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "route_blocked"


def test_savings_profile_cannot_access_accounts_placeholder():
    engine = make_engine()

    global_result = engine.check_scope(
        current_url=f"{BASE_URL}/accounts",
        profile_id="read_only_discovery",
    )

    savings_result = engine.check_scope(
        current_url=f"{BASE_URL}/accounts",
        profile_id="get_savings_balance",
    )

    assert global_result.decision == PolicyDecision.ALLOWED

    assert savings_result.decision == PolicyDecision.BLOCKED
    assert savings_result.code == "route_not_allowed"


def test_other_origin_is_blocked():
    engine = make_engine()

    result = engine.check_scope(
        current_url="http://127.0.0.1:9000/members",
        profile_id="read_only_discovery",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "origin_not_allowed"


def test_go_back_is_explicitly_blocked():
    engine = make_engine()

    result = engine.check(
        action=ActionType.GO_BACK,
        current_url=f"{BASE_URL}/members",
        profile_id="read_only_discovery",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "action_blocked"


def test_savings_profile_permits_recorded_action_types():
    engine = make_engine()

    for action_type in (ActionType.CLICK, ActionType.FILL):
        result = engine.check(
            action=action_type,
            current_url=f"{BASE_URL}/members",
            profile_id="get_savings_balance",
        )

        assert result.decision == PolicyDecision.ALLOWED


def test_unknown_profile_is_blocked():
    engine = make_engine()

    result = engine.check_scope(
        current_url=f"{BASE_URL}/members",
        profile_id="unapproved_capability",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "profile_not_allowed"