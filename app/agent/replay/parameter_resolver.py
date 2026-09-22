import re

from app.agent.schemas.capability import (
    CapabilityAction,
)


class ParameterResolutionError(ValueError):
    pass


class ParameterResolver:

    PARAMETER_PATTERN = re.compile(
        r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}"
    )

    def resolve_action(
        self,
        action: CapabilityAction,
        inputs: dict[str, str],
    ) -> CapabilityAction:

        resolved_value = self._resolve_text(
            action.value,
            inputs,
        )

        resolved_url = self._resolve_text(
            action.url,
            inputs,
        )

        return action.model_copy(
            update={
                "value": resolved_value,
                "url": resolved_url,
            }
        )

    def _resolve_text(
        self,
        value: str | None,
        inputs: dict[str, str],
    ) -> str | None:

        if value is None:
            return None

        def replace(match: re.Match) -> str:
            parameter_name = match.group(1)

            if parameter_name not in inputs:
                raise ParameterResolutionError(
                    f"Missing required replay input: "
                    f"'{parameter_name}'."
                )

            return inputs[parameter_name]

        return self.PARAMETER_PATTERN.sub(
            replace,
            value,
        )