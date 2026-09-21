import re

from app.agent.schemas.capability import (
    CapabilityAction,
)


class ParameterResolutionError(ValueError):
    pass


class ParameterResolver:

    PARAMETER_PATTERN = re.compile(
        r"^\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}$"
    )

    def resolve_action(
        self,
        action: CapabilityAction,
        inputs: dict[str, str],
    ) -> CapabilityAction:

        resolved_value = self._resolve_value(
            action.value,
            inputs,
        )

        return action.model_copy(
            update={
                "value": resolved_value,
            }
        )

    def _resolve_value(
        self,
        value: str | None,
        inputs: dict[str, str],
    ) -> str | None:

        if value is None:
            return None

        match = self.PARAMETER_PATTERN.fullmatch(value)

        if match is None:
            return value

        parameter_name = match.group(1)

        if parameter_name not in inputs:
            raise ParameterResolutionError(
                f"Missing required replay input: "
                f"'{parameter_name}'."
            )

        return inputs[parameter_name]