from urllib.parse import urljoin, urlparse

from app.agent.discovery.models import ActionType, BrowserAction


class ActionExecutor:
    def __init__(self, page, allowed_host: str):
        self.page = page
        self.allowed_host = allowed_host

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

        locator.click()

        self.page.wait_for_load_state(
            "domcontentloaded"
        )

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

        parsed = urlparse(destination)

        if parsed.hostname != self.allowed_host:
            raise ValueError(
                f"Navigation blocked: {parsed.hostname} "
                f"is not an allowed host."
            )

        self.page.goto(
            destination,
            wait_until="domcontentloaded",
        )