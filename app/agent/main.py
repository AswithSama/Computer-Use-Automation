import logging
import os

from dotenv import load_dotenv

from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.operator import TerminalOperator
from app.agent.llm.selection_llm import ask_selection_llm
from app.agent.orchestration.capability_selector import CapabilitySelector
from app.agent.orchestration.discovery_flow import DiscoveryFlow
from app.agent.orchestration.orchestrator import Orchestrator
from app.agent.orchestration.replay_flow import ReplayFlow
from app.agent.policy.config import load_demo_banking_config
from app.agent.policy.engine import PolicyEngine
from app.agent.registry.registry import CapabilityRegistry

load_dotenv()


# Local demo configuration.
TARGET_URL = "http://127.0.0.1:8000"
TENANT_ID = "demo_tenant"
APP_ID = "demo_banking_app"


class AgentLogFormatter(logging.Formatter):
    """Hide the INFO label while keeping non-INFO severity visible."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()

        if record.levelno == logging.INFO:
            return message

        return f"{record.levelname} | {message}"

def configure_logging() -> None:
    """Configure concise operational logs for app.agent only."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    app_logger = logging.getLogger("app.agent")
    app_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(AgentLogFormatter())

    app_logger.addHandler(handler)
    app_logger.setLevel(level)
    app_logger.propagate = False


def main():
    configure_logging()
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
    policy_engine = PolicyEngine(load_demo_banking_config())

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
            policy_engine=policy_engine,
        ),
        run_replay = ReplayFlow(
        target_url=TARGET_URL,
        checkpoint_resume_capability_ids=frozenset({
            "get_savings_balance",
        }),
        handoff_manager=handoff_manager,
        policy_engine=policy_engine,
    )
    )

    return orchestrator.run(
        user_request=user_request,
        tenant_id=TENANT_ID,
        app_id=APP_ID,
    )


if __name__ == "__main__":
    main()
