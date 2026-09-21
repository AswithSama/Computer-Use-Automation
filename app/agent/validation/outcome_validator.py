from dataclasses import dataclass

from app.agent.schemas.discovery import ActionType, BrowserAction


@dataclass
class OutcomeValidationResult:
    success: bool
    reason: str


class OutcomeValidator:
    def validate(
        self,
        action: BrowserAction,
        before_url: str,
        after_url: str,
        before_observation: str,
        after_observation: str,
    ) -> OutcomeValidationResult:

        # FILL does not necessarily change the URL or ARIA snapshot
        # in a meaningful way, so successful Playwright execution
        # is enough for now.
        if action.action == ActionType.FILL:
            return OutcomeValidationResult(
                success=True,
                reason="Fill action executed successfully.",
            )

        # WAIT is allowed to leave the page unchanged.
        if action.action == ActionType.WAIT:
            return OutcomeValidationResult(
                success=True,
                reason="Wait action completed.",
            )

        # Navigation should normally change the URL.
        if action.action == ActionType.NAVIGATE:
            if before_url == after_url:
                return OutcomeValidationResult(
                    success=False,
                    reason="Navigation did not change the URL.",
                )

            return OutcomeValidationResult(
                success=True,
                reason="Navigation changed the URL.",
            )

        # Clicks should normally produce some observable change.
        if action.action == ActionType.CLICK:
            if before_url == after_url and before_observation == after_observation:
                return OutcomeValidationResult(
                    success=False,
                    reason="Click produced no observable page or URL change.",
                )

            return OutcomeValidationResult(
                success=True,
                reason="Click produced an observable change.",
            )

        # Going back should normally change the page.
        if action.action == ActionType.GO_BACK:
            if before_url == after_url and before_observation == after_observation:
                return OutcomeValidationResult(
                    success=False,
                    reason="Going back produced no observable change.",
                )

            return OutcomeValidationResult(
                success=True,
                reason="Browser state changed after going back.",
            )

        return OutcomeValidationResult(
            success=True,
            reason="No post-action validation required.",
        )