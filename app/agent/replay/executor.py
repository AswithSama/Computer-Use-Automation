from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.agent.schemas.capability import CapabilityAction
from app.agent.schemas.discovery import ActionType
from app.agent.replay.models import (
    ReplayActionResult,
    ReplayActionStatus,
)


class ReplayActionExecutor:
    def __init__(self, page):
        self.page = page

    def execute(
        self,
        action: CapabilityAction,
    ) -> ReplayActionResult:
        action_may_have_executed = False

        try:
            if action.action not in {
                ActionType.CLICK,
                ActionType.FILL,
            }:
                return self._invalid_action(
                    "The artifact contains an unsupported replay action."
                )

            if action.target is None:
                return self._invalid_action(
                    "The artifact action is missing its target definition."
                )

            if (
                not action.target.role.strip()
                or not action.target.name.strip()
            ):
                return self._invalid_action(
                    "The artifact target requires a nonempty role and name."
                )

            if (
                action.action == ActionType.FILL
                and action.value is None
            ):
                return self._invalid_action(
                    "The artifact fill action is missing its value."
                )

            # Preserve the current matching behavior.
            locator = self.page.get_by_role(
                action.target.role,
                name=action.target.name,
                exact=False,
            )

            count = locator.count()

            if count != 1:
                return ReplayActionResult(
                    success=False,
                    status=ReplayActionStatus.TARGET_NOT_FOUND,
                    reason=(
                        "The target is missing or matches multiple elements."
                    ),
                    action_may_have_executed=False,
                )

            # Once click/fill is invoked, an exception does not establish
            # whether the action took effect.
            action_may_have_executed = True

            if action.action == ActionType.CLICK:
                locator.click()
            else:
                locator.fill(action.value)

            return ReplayActionResult(
                success=True,
                status=ReplayActionStatus.SUCCESS,
                reason="The replay action completed.",
                action_may_have_executed=True,
            )

        except PlaywrightTimeoutError:
            return ReplayActionResult(
                success=False,
                status=ReplayActionStatus.TIMEOUT,
                reason="Action execution timed out.",
                action_may_have_executed=action_may_have_executed,
            )

        except Exception:
            return ReplayActionResult(
                success=False,
                status=ReplayActionStatus.EXECUTION_ERROR,
                reason="An action execution error occurred.",
                action_may_have_executed=action_may_have_executed,
            )

    @staticmethod
    def _invalid_action(reason: str) -> ReplayActionResult:
        return ReplayActionResult(
            success=False,
            status=ReplayActionStatus.INVALID_ACTION,
            reason=reason,
            action_may_have_executed=False,
        )