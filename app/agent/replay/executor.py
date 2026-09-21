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

        try:
            if action.action == ActionType.CLICK:
                return self._click(action)

            if action.action == ActionType.FILL:
                return self._fill(action)

            return ReplayActionResult(
                success=False,
                status=ReplayActionStatus.EXECUTION_ERROR,
                reason=(
                    f"Replay does not support action "
                    f"'{action.action.value}' yet."
                ),
            )

        except PlaywrightTimeoutError as exc:
            return ReplayActionResult(
                success=False,
                status=ReplayActionStatus.TIMEOUT,
                reason=str(exc),
            )

        except Exception as exc:
            return ReplayActionResult(
                success=False,
                status=ReplayActionStatus.EXECUTION_ERROR,
                reason=str(exc),
            )

    def _get_locator(
        self,
        action: CapabilityAction,
    ):
        if action.target is None:
            return None, ReplayActionResult(
                success=False,
                status=ReplayActionStatus.TARGET_NOT_FOUND,
                reason="Interactive replay action has no target.",
            )

        locator = self.page.get_by_role(
            action.target.role,
            name=action.target.name,
            exact=False,
        )

        count = locator.count()

        if count == 0:
            return None, ReplayActionResult(
                success=False,
                status=ReplayActionStatus.TARGET_NOT_FOUND,
                reason=(
                    f"No element found for "
                    f"role={action.target.role}, "
                    f"name={action.target.name}."
                ),
            )

        if count > 1:
            return None, ReplayActionResult(
                success=False,
                status=ReplayActionStatus.TARGET_NOT_FOUND,
                reason=(
                    f"Ambiguous target: found {count} elements for "
                    f"role={action.target.role}, "
                    f"name={action.target.name}."
                ),
            )

        return locator, None

    def _click(
        self,
        action: CapabilityAction,
    ) -> ReplayActionResult:

        locator, error = self._get_locator(action)

        if error is not None:
            return error

        locator.click()

        return ReplayActionResult(
            success=True,
            status=ReplayActionStatus.SUCCESS,
            reason=(
                f"Clicked {action.target.role} "
                f"'{action.target.name}'."
            ),
        )

    def _fill(
        self,
        action: CapabilityAction,
    ) -> ReplayActionResult:

        if action.value is None:
            return ReplayActionResult(
                success=False,
                status=ReplayActionStatus.EXECUTION_ERROR,
                reason="Fill action requires a value.",
            )

        locator, error = self._get_locator(action)

        if error is not None:
            return error

        locator.fill(action.value)

        return ReplayActionResult(
            success=True,
            status=ReplayActionStatus.SUCCESS,
            reason=(
                f"Filled {action.target.role} "
                f"'{action.target.name}'."
            ),
        )