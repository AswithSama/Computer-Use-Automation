"""Load trusted, application-specific allowlist configuration."""

from pathlib import Path

from app.agent.policy.models import AllowlistConfig


_DEMO_BANKING_POLICY_PATH = (
    Path(__file__).resolve().parent / "demo_banking.json"
)


def load_demo_banking_config() -> AllowlistConfig:
    """
    Load and validate the local demo application's policy.

    An invalid or missing policy raises an exception rather than
    silently allowing browser execution.
    """
    return AllowlistConfig.model_validate_json(
        _DEMO_BANKING_POLICY_PATH.read_text(encoding="utf-8")
    )