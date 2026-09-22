from types import SimpleNamespace

import pytest

from app.agent.capability.compiler import CapabilityCompiler
from app.agent.replay.parameter_resolver import (
    ParameterResolutionError,
    ParameterResolver,
)
from app.agent.schemas.capability import CapabilityAction
from app.agent.schemas.discovery import ActionType


def test_compiler_parameterizes_navigation_url():
    context = SimpleNamespace(
        interactions=[
            SimpleNamespace(
                step=2,
                action=ActionType.NAVIGATE,
                target_role=None,
                target_name=None,
                value=None,
                url="/members/12345",
            )
        ]
    )

    extracted_inputs = SimpleNamespace(
        inputs=[
            SimpleNamespace(
                source_step=1,
                name="member_id",
                observed_value="12345",
            )
        ]
    )

    actions = CapabilityCompiler().compile_actions(
        context=context,
        extracted_inputs=extracted_inputs,
    )

    assert len(actions) == 1
    assert actions[0].action == ActionType.NAVIGATE
    assert actions[0].url == "/members/{{member_id}}"


def test_compiler_rejects_go_back():
    context = SimpleNamespace(
        interactions=[
            SimpleNamespace(
                step=1,
                action=ActionType.GO_BACK,
                target_role=None,
                target_name=None,
                value=None,
                url=None,
            )
        ]
    )

    extracted_inputs = SimpleNamespace(inputs=[])

    with pytest.raises(ValueError):
        CapabilityCompiler().compile_actions(
            context=context,
            extracted_inputs=extracted_inputs,
        )


def test_resolver_resolves_parameter_inside_url():
    action = CapabilityAction(
        action=ActionType.NAVIGATE,
        url="/members/{{member_id}}/accounts",
    )

    resolved = ParameterResolver().resolve_action(
        action=action,
        inputs={
            "member_id": "67890",
        },
    )

    assert (
        resolved.url
        == "/members/67890/accounts"
    )


def test_resolver_preserves_fill_parameter_behavior():
    action = CapabilityAction(
        action=ActionType.FILL,
        value="{{member_id}}",
    )

    resolved = ParameterResolver().resolve_action(
        action=action,
        inputs={
            "member_id": "67890",
        },
    )

    assert resolved.value == "67890"


def test_missing_navigation_parameter_fails():
    action = CapabilityAction(
        action=ActionType.NAVIGATE,
        url="/members/{{member_id}}",
    )

    with pytest.raises(ParameterResolutionError):
        ParameterResolver().resolve_action(
            action=action,
            inputs={},
        )