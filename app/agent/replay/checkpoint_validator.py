import re
from time import monotonic
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.agent.schemas.capability import CapabilityCheckpoint


class CheckpointValidator:
    def validate(
        self,
        checkpoint: CapabilityCheckpoint,
        current_url: str,
        inputs: dict[str, str],
        *,
        page=None,
    ) -> tuple[bool, str]:
        expected_url, required_texts = self._resolve_conditions(
            checkpoint, inputs
        )

        if page is not None:
            current_url = page.url

        if expected_url is not None:
            parsed = urlparse(current_url)
            actual_url = parsed.path

            if parsed.query:
                actual_url += f"?{parsed.query}"

            if actual_url != expected_url:
                return (
                    False,
                    "The expected application route was not reached.",
                )

        if required_texts and page is None:
            return (
                False,
                "A live page is required to verify checkpoint text.",
            )

        for text in required_texts:
            locator = page.get_by_text(text, exact=True)

            # Checkpoint markers must be unambiguous and visible.
            if locator.count() != 1:
                return (
                    False,
                    "Required checkpoint text is missing or ambiguous.",
                )

            if not locator.is_visible():
                return (
                    False,
                    "Required checkpoint text is not visible.",
                )

        return True, "Checkpoint passed."

    def wait_and_validate(
        self,
        checkpoint: CapabilityCheckpoint,
        page,
        inputs: dict[str, str],
        timeout_ms: int = 5000,
    ) -> tuple[bool, str]:
        expected_url, required_texts = self._resolve_conditions(
            checkpoint, inputs
        )

        deadline = monotonic() + max(0, timeout_ms) / 1000

        result = self.validate(
            checkpoint,
            page.url,
            inputs,
            page=page,
        )

        if result[0] or timeout_ms <= 0:
            return result

        def remaining_ms() -> float:
            remaining = (deadline - monotonic()) * 1000

            if remaining <= 0:
                raise PlaywrightTimeoutError(
                    "Checkpoint wait budget exhausted."
                )

            # Never pass zero: Playwright interprets zero as no timeout.
            return remaining

        try:
            if expected_url is not None:
                page.wait_for_function(
                    """expected => (
                        window.location.pathname +
                        window.location.search
                    ) === expected""",
                    arg=expected_url,
                    timeout=remaining_ms(),
                )

            for text in required_texts:
                page.get_by_text(text, exact=True).wait_for(
                    state="visible",
                    timeout=remaining_ms(),
                )

        except PlaywrightTimeoutError:
            # Recheck actual state, even when a wait timed out.
            pass

        return self.validate(
            checkpoint,
            page.url,
            inputs,
            page=page,
        )

    def _resolve_conditions(
        self,
        checkpoint: CapabilityCheckpoint,
        inputs: dict[str, str],
    ) -> tuple[str | None, list[str]]:
        expected_url = None

        if checkpoint.url_pattern is not None:
            expected_url = self._resolve_parameters(
                checkpoint.url_pattern,
                inputs,
            )

            if not expected_url.strip():
                raise ValueError(
                    "Checkpoint route must not be empty."
                )

        required_texts = [
            self._resolve_parameters(text, inputs)
            for text in checkpoint.required_text
        ]

        if any(not text.strip() for text in required_texts):
            raise ValueError(
                "Checkpoint text must not be empty."
            )

        if expected_url is None and not required_texts:
            raise ValueError(
                "Checkpoint has no verifiable conditions."
            )

        return expected_url, required_texts

    def _resolve_parameters(
        self,
        value: str,
        inputs: dict[str, str],
    ) -> str:
        def replace(match):
            name = match.group(1)

            if name not in inputs:
                raise ValueError(
                    "A checkpoint input is unavailable."
                )

            return inputs[name]

        # Resolve in one pass so input values are not treated as templates.
        return re.sub(
            r"\{\{([^{}]+)\}\}",
            replace,
            value,
        )