from urllib.parse import urlparse

from app.agent.schemas.capability import CapabilityCheckpoint

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
class CheckpointValidator:

    def validate(
        self,
        checkpoint: CapabilityCheckpoint,
        current_url: str,
        inputs: dict[str, str],
    ) -> tuple[bool, str]:

        if checkpoint.url_pattern is not None:
            expected_url = self._resolve_parameters(
                checkpoint.url_pattern,
                inputs,
            )

            parsed_current_url = urlparse(current_url)

            actual_url = parsed_current_url.path

            if parsed_current_url.query:
                actual_url += f"?{parsed_current_url.query}"

            if actual_url != expected_url:
                return (
                    False,
                    (
                        f"Checkpoint failed. "
                        f"Expected URL '{expected_url}', "
                        f"but found '{actual_url}'."
                    ),
                )

        return (
            True,
            "Checkpoint passed.",
        )

    def _resolve_parameters(
        self,
        value: str,
        inputs: dict[str, str],
    ) -> str:

        resolved = value

        for name, input_value in inputs.items():
            resolved = resolved.replace(
                f"{{{{{name}}}}}",
                input_value,
            )

        return resolved

    
    def wait_and_validate(
        self,
        checkpoint: CapabilityCheckpoint,
        page,
        inputs: dict[str, str],
        timeout_ms: int = 5000,
    ) -> tuple[bool, str]:

        if checkpoint.url_pattern is None:
            return self.validate(checkpoint, page.url, inputs)

        expected_url = self._resolve_parameters(
            checkpoint.url_pattern,
            inputs,
        )

        try:
            page.wait_for_function(
                """expected => (
                    window.location.pathname +
                    window.location.search
                ) === expected""",
                arg=expected_url,
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError:
            pass

        # Check the actual URL again after waiting.
        return self.validate(
            checkpoint=checkpoint,
            current_url=page.url,
            inputs=inputs,
        )