from dataclasses import dataclass

from app.agent.capability.inputs.input_extraction import (
    InputCandidate,
    InputExtractionResult,
)
from app.agent.capability.models import CapabilityContext


@dataclass
class InputVerificationResult:
    valid: bool
    reason: str


class InputVerifier:

    def verify(
        self,
        extraction: InputExtractionResult,
        context: CapabilityContext,
    ) -> InputVerificationResult:

        seen_names: set[str] = set()

        for candidate in extraction.inputs:
            result = self._verify_candidate(
                candidate=candidate,
                context=context,
                seen_names=seen_names,
            )

            if not result.valid:
                return result

            seen_names.add(candidate.name)

        return InputVerificationResult(
            valid=True,
            reason="All extracted inputs are grounded in discovery evidence.",
        )

    def _verify_candidate(
        self,
        candidate: InputCandidate,
        context: CapabilityContext,
        seen_names: set[str],
    ) -> InputVerificationResult:

        # 1. Input names should be unique.
        if candidate.name in seen_names:
            return InputVerificationResult(
                valid=False,
                reason=(
                    f"Duplicate input name: {candidate.name}"
                ),
            )

        # 2. The claimed source step must actually exist.
        source_interaction = next(
            (
                interaction
                for interaction in context.interactions
                if interaction.step == candidate.source_step
            ),
            None,
        )

        if source_interaction is None:
            return InputVerificationResult(
                valid=False,
                reason=(
                    f"Source step {candidate.source_step} "
                    "does not exist in the successful interactions."
                ),
            )

        # 3. For the current FILL implementation, the action
        # must contain an actual value.
        if source_interaction.value is None:
            return InputVerificationResult(
                valid=False,
                reason=(
                    f"Source step {candidate.source_step} "
                    "does not contain an input value."
                ),
            )

        # 4. The LLM's claimed value must exactly match
        # the value used during successful discovery.
        if source_interaction.value != candidate.observed_value:
            return InputVerificationResult(
                valid=False,
                reason=(
                    f"Observed value '{candidate.observed_value}' "
                    f"does not match source step "
                    f"{candidate.source_step} value "
                    f"'{source_interaction.value}'."
                ),
            )

        # 5. The value must be grounded in the original request.
        if candidate.observed_value not in context.user_request:
            return InputVerificationResult(
                valid=False,
                reason=(
                    f"Observed value '{candidate.observed_value}' "
                    "is not grounded in the original user request."
                ),
            )

        return InputVerificationResult(
            valid=True,
            reason=(
                f"Input '{candidate.name}' is grounded in "
                f"successful step {candidate.source_step}."
            ),
        )