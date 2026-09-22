from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import (
    AllowlistConfig,
    PolicyDecision,
    PolicyProfile,
    TargetRule,
)
from app.agent.schemas.discovery import ActionType


def make_engine():
    config = AllowlistConfig(
        policy_id="demo-banking",
        allowed_origins=[
            "http://127.0.0.1:8000",
        ],
        allowed_routes=[
            "/members",
            "/members/*",
            "/accounts/*",
            "/transfers/*",
        ],
        blocked_routes=[
            "/members/admin/*",
        ],
        allowed_actions={
            ActionType.CLICK,
            ActionType.FILL,
            ActionType.NAVIGATE,
            ActionType.WAIT,
        },
        blocked_actions={
            ActionType.GO_BACK,
        },
        blocked_targets=[
            TargetRule(
                action=ActionType.CLICK,
                role="button",
                name="Delete Account",
            ),
        ],
        confirmation_targets=[
            TargetRule(
                action=ActionType.CLICK,
                role="button",
                name="Confirm Transfer",
                route_pattern="/transfers/*",
            ),
        ],
        profiles={
            "savings_balance": PolicyProfile(
                allowed_routes=[
                    "/members",
                    "/members/*",
                    "/accounts/*",
                ],
                allowed_actions={
                    ActionType.CLICK,
                    ActionType.FILL,
                    ActionType.NAVIGATE,
                    ActionType.WAIT,
                },
            ),
            "transfer_review": PolicyProfile(
                allowed_routes=[
                    "/members/*",
                    "/transfers/*",
                ],
                allowed_actions={
                    ActionType.CLICK,
                    ActionType.FILL,
                    ActionType.NAVIGATE,
                },
            ),
        },
    )

    return PolicyEngine(config)


def test_allowed_action():
    engine = make_engine()

    result = engine.check(
        action=ActionType.CLICK,
        current_url="http://127.0.0.1:8000/members/123",
        profile_id="savings_balance",
        target_role="button",
        target_name="View Savings",
    )

    assert result.decision == PolicyDecision.ALLOWED


def test_blocked_external_domain():
    engine = make_engine()

    result = engine.check(
        action=ActionType.NAVIGATE,
        current_url="http://127.0.0.1:8000/members",
        profile_id="savings_balance",
        destination_url="https://example.com/account",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "origin_not_allowed"


def test_blocked_route():
    engine = make_engine()

    result = engine.check(
        action=ActionType.NAVIGATE,
        current_url="http://127.0.0.1:8000/members",
        profile_id="savings_balance",
        destination_url="/members/admin/users",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "route_blocked"


def test_blocked_action_type():
    engine = make_engine()

    result = engine.check(
        action=ActionType.GO_BACK,
        current_url="http://127.0.0.1:8000/members",
        profile_id="savings_balance",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "action_blocked"


def test_blocked_target():
    engine = make_engine()

    result = engine.check(
        action=ActionType.CLICK,
        current_url="http://127.0.0.1:8000/members/123",
        profile_id="savings_balance",
        target_role="button",
        target_name="Delete Account",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "target_blocked"


def test_risky_action_requires_confirmation():
    engine = make_engine()

    result = engine.check(
        action=ActionType.CLICK,
        current_url="http://127.0.0.1:8000/transfers/review",
        profile_id="transfer_review",
        target_role="button",
        target_name="Confirm Transfer",
    )

    assert (
        result.decision
        == PolicyDecision.NEEDS_CONFIRMATION
    )

    assert result.code == "confirmation_required"


def test_profile_cannot_expand_global_permissions():
    engine = make_engine()

    result = engine.check(
        action=ActionType.NAVIGATE,
        current_url="http://127.0.0.1:8000/members",
        profile_id="savings_balance",
        destination_url="/transfers/review",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "route_not_allowed"


def test_missing_profile_is_blocked():
    engine = make_engine()

    result = engine.check(
        action=ActionType.CLICK,
        current_url="http://127.0.0.1:8000/members",
        target_role="button",
        target_name="Search",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "profile_not_allowed"


def test_policy_can_check_browser_scope_independently():
    engine = make_engine()

    result = engine.check_scope(
        current_url="https://example.com/account",
        profile_id="savings_balance",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "origin_not_allowed"