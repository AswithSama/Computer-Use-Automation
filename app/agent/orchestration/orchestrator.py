import logging
from collections.abc import Callable

from app.agent.orchestration.capability_selector import CapabilitySelector
from app.agent.registry.registry import CapabilityRegistry


logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        selector: CapabilitySelector,
        run_discovery: Callable,
        run_replay: Callable,
    ):
        self.registry = registry
        self.selector = selector
        self.run_discovery = run_discovery
        self.run_replay = run_replay

    @staticmethod
    def _is_savings_capability(artifact) -> bool:
        """Identify the verified savings table-output contract."""
        return any(
            output.binding.kind == "table"
            and output.binding.row_match.column == "Type"
            and output.binding.row_match.value == "Savings"
            and output.binding.value_column == "Current Balance"
            for output in artifact.outputs
        )

    def run(
        self,
        *,
        user_request: str,
        tenant_id: str,
        app_id: str,
    ):
        eligible = self.registry.list_eligible(
            tenant_id=tenant_id,
            app_id=app_id,
        )

        selection = self.selector.select(
            user_request=user_request,
            eligible=eligible,
        )

        if selection is None:
            logger.info(
                "No matching approved capability. Starting discovery."
            )
            return self.run_discovery(user_request)

        (selected_path, stored), inputs = selection

        logger.info(
            "Reusing approved capability: %s v%s",
            stored.artifact.capability_id,
            stored.version,
        )
        logger.debug(
            "Capability loaded from: %s",
            selected_path,
        )

        # Select the policy using the approved registry artifact,
        # not the LLM-generated capability name or user request.
        policy_profile_id = (
            "get_savings_balance"
            if self._is_savings_capability(stored.artifact)
            else "read_only_replay"
        )

        return self.run_replay(
            artifact=stored.artifact,
            business_outcome_rules=tuple(
                stored.business_outcome_rules
            ),
            inputs=inputs,
            policy_profile_id=policy_profile_id,
        )