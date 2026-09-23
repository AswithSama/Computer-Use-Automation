from unittest.mock import Mock

from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import (
    AllowlistConfig,
    PolicyProfile,
    TargetRule,
)
from app.agent.replay.models import (
    ReplayFailureCategory,
    ReplayStatus,
)
from app.agent.replay.replay_engine import ReplayEngine
from app.agent.schemas.capability import (
    CapabilityAction,
    CapabilityArtifact,
    CapabilityTarget,
)
from app.agent.schemas.discovery import ActionType

BASE_URL = "http://127.0.0.1:8000"


def make_artifact():
    return CapabilityArtifact(
        schema_version="1.0",
        capability_id="get_savings_balance",
        description="Retrieve the savings balance.",
        inputs=[],
        actions=[
            CapabilityAction(
                action=ActionType.CLICK,
                target=CapabilityTarget(
                    role="button",
                    name="View Savings",
                ),
            )
        ],
        checkpoints=[],
        outputs=[],
    )


def make_policy(
    *,
    blocked_routes=None,
    blocked_targets=None,
    confirmation_targets=None,
):
    return PolicyEngine(
        AllowlistConfig(
            policy_id="test-banking-policy",
            allowed_origins=[BASE_URL],
            allowed_routes=[
                "/",
                "/members",
                "/members/*",
            ],
            blocked_routes=blocked_routes or [],
            allowed_actions={
                ActionType.CLICK,
                ActionType.FILL,
            },
            blocked_targets=blocked_targets or [],
            confirmation_targets=confirmation_targets or [],
            profiles={
                "get_savings_balance": PolicyProfile(
                    allowed_routes=[
                        "/",
                        "/members",
                        "/members/*",
                    ],
                    allowed_actions={
                        ActionType.CLICK,
                        ActionType.FILL,
                    },
                )
            },
        )
    )


def make_page():
    page = Mock()
    page.url = f"{BASE_URL}/members/12345"

    locator = page.get_by_role.return_value
    locator.count.return_value = 1

    return page, locator


def make_engine(page, policy):
    engine = ReplayEngine(
        page=page,
        policy_engine=policy,
        policy_profile_id="get_savings_balance",
    )

    # Keep focused tests from writing evidence files.
    engine.evidence_recorder.record = Mock(return_value=[])

    return engine


def test_allowed_replay_action_executes():
    page, locator = make_page()

    engine = make_engine(
        page,
        make_policy(),
    )

    result = engine.replay(
        make_artifact(),
        {},
    )

    assert result.status == ReplayStatus.SUCCESS

    locator.click.assert_called_once()


def test_policy_blocked_target_never_reaches_executor():
    page, locator = make_page()

    policy = make_policy(
        blocked_targets=[
            TargetRule(
                action=ActionType.CLICK,
                role="button",
                name="View Savings",
            )
        ]
    )

    engine = make_engine(page, policy)

    result = engine.replay(
        make_artifact(),
        {},
    )

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.failure_category == ReplayFailureCategory.POLICY
    assert result.error_code == "policy_blocked"
    assert result.action_may_have_executed is False

    locator.click.assert_not_called()


def test_policy_change_can_block_previously_valid_artifact():
    page, locator = make_page()

    policy = make_policy(
        blocked_routes=[
            "/members/12345",
        ]
    )

    engine = make_engine(page, policy)

    result = engine.replay(
        make_artifact(),
        {},
    )

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.failure_category == ReplayFailureCategory.POLICY
    assert result.error_code == "policy_blocked"
    assert result.completed_steps == 0

    locator.click.assert_not_called()


def test_confirmation_required_does_not_execute_action():
    page, locator = make_page()

    policy = make_policy(
        confirmation_targets=[
            TargetRule(
                action=ActionType.CLICK,
                role="button",
                name="View Savings",
            )
        ]
    )

    engine = make_engine(page, policy)

    result = engine.replay(
        make_artifact(),
        {},
    )

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.failure_category == ReplayFailureCategory.POLICY
    assert result.error_code == "policy_confirmation_required"
    assert result.action_may_have_executed is False

    locator.click.assert_not_called()



def test_policy_denial_does_not_offer_human_handoff():
    page, locator = make_page()

    policy = make_policy(
        blocked_targets=[
            TargetRule(
                action=ActionType.CLICK,
                role="button",
                name="View Savings",
            )
        ]
    )

    on_intervention = Mock(return_value=True)

    engine = ReplayEngine(
        page=page,
        policy_engine=policy,
        policy_profile_id="get_savings_balance",
        on_intervention=on_intervention,
    )

    engine.evidence_recorder.record = Mock(return_value=[])

    result = engine.replay(
        make_artifact(),
        {},
    )

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.failure_category == ReplayFailureCategory.POLICY
    assert result.error_code == "policy_blocked"

    locator.click.assert_not_called()
    on_intervention.assert_not_called()