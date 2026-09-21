from app.agent.capability.models import (
    CapabilityActionContext,
    CapabilityCompletionContext,
    CapabilityContext,
)
from app.agent.schemas.discovery import ActionType
from app.agent.schemas.recording import DiscoveryResult


RELEVANT_INTERACTION_ACTIONS = {
    ActionType.CLICK,
    ActionType.FILL,
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