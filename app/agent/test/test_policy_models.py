import pytest
from pydantic import ValidationError

from app.agent.policy.models import (
    AllowlistConfig,
    PolicyDecision,
    PolicyProfile,
    PolicyResult,
    TargetRule,
)
from app.agent.schemas.discovery import ActionType


def test_allowlist_configuration_is_typed():
    config = AllowlistConfig(
        policy_id="demo-banking",
        allowed_origins=[
            "http://127.0.0.1:8000",
        ],
        allowed_routes=[
            "/members/*",
            "/accounts/*",
        ],
        allowed_actions={
            ActionType.CLICK,
            ActionType.FILL,
        },
        profiles={
            "savings_balance": PolicyProfile(
                allowed_routes=[
                    "/members/*",
                ],
                allowed_actions={
                    ActionType.CLICK,
                    ActionType.FILL,
                },
            ),
        },
    )

    assert config.policy_id == "demo-banking"

    assert ActionType.CLICK in config.allowed_actions

    assert (
        ActionType.FILL
        in config.profiles["savings_balance"].allowed_actions
    )


def test_unknown_action_type_is_rejected():
    with pytest.raises(ValidationError):
        AllowlistConfig(
            policy_id="demo-banking",
            allowed_origins=[
                "http://127.0.0.1:8000",
            ],
            allowed_routes=["/members/*"],
            allowed_actions={"execute_script"},
        )


def test_unknown_policy_fields_are_rejected():
    with pytest.raises(ValidationError):
        AllowlistConfig(
            policy_id="demo-banking",
            allowed_origins=[
                "http://127.0.0.1:8000",
            ],
            allowed_routes=["/members/*"],
            allowed_actions={ActionType.CLICK},
            allow_everything=True,
        )


def test_target_rule_preserves_action_and_target():
    rule = TargetRule(
        action=ActionType.CLICK,
        role="button",
        name="Confirm Transfer",
        route_pattern="/transfers/*",
    )

    assert rule.action == ActionType.CLICK
    assert rule.name == "Confirm Transfer"


def test_policy_result_has_three_supported_decisions():
    assert {decision.value for decision in PolicyDecision} == {
        "allowed",
        "blocked",
        "needs_confirmation",
    }

    result = PolicyResult(
        decision=PolicyDecision.BLOCKED,
        code="route_not_allowed",
        reason="The requested route is outside the permitted scope.",
    )

    assert result.decision == PolicyDecision.BLOCKED
    assert result.code == "route_not_allowed"