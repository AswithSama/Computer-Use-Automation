from dotenv import load_dotenv

from app.agent.llm.selection_llm import ask_selection_llm
from app.agent.orchestration.capability_selector import CapabilitySelector
from app.agent.orchestration.discovery_flow import DiscoveryFlow
from app.agent.orchestration.orchestrator import Orchestrator
from app.agent.orchestration.replay_flow import ReplayFlow
from app.agent.registry.registry import CapabilityRegistry
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.operator import TerminalOperator

load_dotenv()


# Local demo configuration.
TARGET_URL = "http://127.0.0.1:8000"
TENANT_ID = "demo_tenant"
APP_ID = "demo_banking_app"


def main():
    user_request = input(
        "What do you want to do? "
    ).strip()

    if not user_request:
        print("A user request is required.")
        return None

    registry = CapabilityRegistry()

    selector = CapabilitySelector(
        ask_llm=ask_selection_llm,
    )
    handoff_manager = HumanHandoffManager(
        operator=TerminalOperator(
            operator_id="local-operator"
        )
    )
    orchestrator = Orchestrator(
        registry=registry,
        selector=selector,
        run_discovery=DiscoveryFlow(
            target_url=TARGET_URL,
            tenant_id=TENANT_ID,
            app_id=APP_ID,
            registry=registry,
            ask_llm=ask_selection_llm,
            handoff_manager=handoff_manager,
        ),
        run_replay = ReplayFlow(
        target_url=TARGET_URL,
        checkpoint_resume_capability_ids=frozenset({
            "get_savings_balance",
        }),
        handoff_manager=handoff_manager,
    )
    )

    return orchestrator.run(
        user_request=user_request,
        tenant_id=TENANT_ID,
        app_id=APP_ID,
    )


if __name__ == "__main__":
    main()
