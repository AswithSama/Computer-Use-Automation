from pydantic import BaseModel, ConfigDict

from app.agent.schemas.discovery import ActionType, DiscoveredOutput
from app.agent.schemas.recording import DiscoveryResult


class CapabilityActionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    action: ActionType

    target_role: str | None = None
    target_name: str | None = None

    value: str | None = None
    url: str | None = None

    reason: str


class CapabilityCompletionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str
    reason: str
    outputs: list[DiscoveredOutput]
    final_url: str
    final_observation: str


class CapabilityContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_request: str

    interactions: list[CapabilityActionContext]

    completion: CapabilityCompletionContext


RELEVANT_INTERACTION_ACTIONS = {
    ActionType.CLICK,
    ActionType.FILL,
    ActionType.NAVIGATE,
    ActionType.WAIT,
}


class CapabilityContextBuilder:

    def build(
        self,
        user_request: str,
        discovery_result: DiscoveryResult,
    ) -> CapabilityContext:

        interactions: list[CapabilityActionContext] = []

        for transition in discovery_result.candidate_path:
            action = transition.action

            if action.action not in RELEVANT_INTERACTION_ACTIONS:
                continue

            interactions.append(
                CapabilityActionContext(
                    step=transition.step,
                    action=action.action,
                    target_role=action.target_role,
                    target_name=action.target_name,
                    value=action.value,
                    url=action.url,
                    reason=action.reason,
                )
            )

        completion = CapabilityCompletionContext(
            result=discovery_result.result,
            reason=discovery_result.finish_reason,
            outputs=discovery_result.outputs,
            final_url=discovery_result.final_state.url,
            final_observation=discovery_result.final_state.observation,
        )

        return CapabilityContext(
            user_request=user_request,
            interactions=interactions,
            completion=completion,
        )
