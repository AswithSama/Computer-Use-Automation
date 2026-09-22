from urllib.parse import urljoin, urlparse

from app.agent.schemas.discovery import ActionType, BrowserAction
from collections.abc import Callable

from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import (
    PolicyDecision,
    PolicyResult,
    PolicyViolation,
)

class ActionExecutor:
    def __init__(
        self,
        page,
        allowed_host: str,
        *,
        policy_engine: PolicyEngine | None = None,
        policy_profile_id: str = "read_only_discovery",
        on_policy_decision: Callable[[PolicyResult], None] | None = None,
    ):
        self.page = page
        self.allowed_host = allowed_host
        self.policy_engine = policy_engine
        self.policy_profile_id = policy_profile_id
        self.on_policy_decision = on_policy_decision

    def execute(self, action: BrowserAction):
        if action.action == ActionType.CLICK:
            self._click(action)

        elif action.action == ActionType.FILL:
            self._fill(action)

        elif action.action == ActionType.GO_BACK:
            self.page.go_back(
                wait_until="domcontentloaded"
            )

        elif action.action == ActionType.NAVIGATE:
            self._navigate(action)

        elif action.action == ActionType.WAIT:
            self.page.wait_for_timeout(1000)

        else:
            raise ValueError(
                f"Executor cannot execute action: {action.action}"
            )

    def _get_locator(self, action: BrowserAction):
        if not action.target_role or not action.target_name:
            raise ValueError(
                "Interactive action requires target_role and target_name."
            )

        locator = self.page.get_by_role(
            action.target_role,
            name=action.target_name,
            exact=False,
        )

        count = locator.count()

        if count == 0:
            raise ValueError(
                f"No element found for "
                f"role={action.target_role}, "
                f"name={action.target_name}"
            )

        if count > 1:
            raise ValueError(
                f"Ambiguous locator: found {count} elements for "
                f"role={action.target_role}, "
                f"name={action.target_name}"
            )

        return locator

    def _click(self, action: BrowserAction):
        locator = self._get_locator(action)

        if self.policy_engine is not None:
            href = locator.get_attribute("href")

            if href is None:
                # A link without an inspectable destination cannot be
                # authorized for navigation.
                if (action.target_role or "").strip().casefold() == "link":
                    result = PolicyResult(
                        decision=PolicyDecision.BLOCKED,
                        code="link_destination_unverified",
                        reason="The link destination could not be verified.",
                    )

                    if self.on_policy_decision is not None:
                        self.on_policy_decision(result)

                    raise PolicyViolation(result)

            else:
                destination = urljoin(self.page.url, href)

                result = self.policy_engine.check_scope(
                    current_url=destination,
                    profile_id=self.policy_profile_id,
                )

                if self.on_policy_decision is not None:
                    self.on_policy_decision(result)

                if result.decision != PolicyDecision.ALLOWED:
                    raise PolicyViolation(result)

        locator.click()

        self.page.wait_for_load_state("domcontentloaded")

    def _fill(self, action: BrowserAction):
        if action.value is None:
            raise ValueError(
                "Fill action requires a value."
            )

        locator = self._get_locator(action)

        locator.fill(action.value)

    def _navigate(self, action: BrowserAction):
        if not action.url:
            raise ValueError(
                "Navigate action requires a URL."
            )

        destination = urljoin(
            self.page.url,
            action.url,
        )

        # Apply the shared policy immediately before page.goto().
        if self.policy_engine is not None:
            result = self.policy_engine.check_scope(
                current_url=destination,
                profile_id=self.policy_profile_id,
            )

            if self.on_policy_decision is not None:
                self.on_policy_decision(result)

            if result.decision != PolicyDecision.ALLOWED:
                raise PolicyViolation(result)

        # Retain the existing hostname restriction while integrating
        # the shared policy. Existing callers without a policy engine
        # continue to receive the original behavior.
        parsed = urlparse(destination)

        if parsed.hostname != self.allowed_host:
            raise ValueError(
                f"Navigation blocked: {parsed.hostname} "
                "is not an allowed host."
            )

        self.page.goto(
            destination,
            wait_until="domcontentloaded",
        )