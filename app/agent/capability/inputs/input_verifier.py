from dataclasses import dataclass

from app.agent.capability.context import CapabilityContext
from app.agent.capability.inputs.input_extraction import (
    InputCandidate,
    InputExtractionResult,
)
from app.agent.schemas.discovery import ActionType


@dataclass(frozen=True)
class RejectedInput:
    name: str
    reason: str


@dataclass(frozen=True)
class InputVerificationResult:
    valid: bool
    reason: str
    verified_extraction: InputExtractionResult
    rejected_inputs: tuple[RejectedInput, ...] = ()


class InputVerifier:

    def verify(
        self,
        extraction: InputExtractionResult,
        context: CapabilityContext,
    ) -> InputVerificationResult:

        seen_names: set[str] = set()

        verified_inputs: list[InputCandidate] = []
        rejected_inputs: list[RejectedInput] = []

        for candidate in extraction.inputs:
            result = self._verify_candidate(
                candidate=candidate,
                context=context,
                seen_names=seen_names,
            )

            if not result.valid:
                rejected_inputs.append(
                    RejectedInput(
                        name=candidate.name,
                        reason=result.reason,
                    )
                )
                continue

            verified_inputs.append(candidate)
            seen_names.add(candidate.name)

        verified_extraction = InputExtractionResult(
            inputs=verified_inputs,
        )

        eligible_source_steps = self._eligible_source_steps(
            context
        )

        # If discovery contained genuine user-supplied input evidence,
        # at least one valid extracted input must survive verification.
        #
        # This prevents us from silently compiling a supposedly
        # parameterized workflow when input extraction failed entirely.
        if eligible_source_steps and not verified_inputs:
            return InputVerificationResult(
                valid=False,
                reason=(
                    "Input evidence exists in the successful discovery "
                    "path, but no extracted input passed deterministic "
                    "verification."
                ),
                verified_extraction=verified_extraction,
                rejected_inputs=tuple(rejected_inputs),
            )

        if rejected_inputs:
            return InputVerificationResult(
                valid=True,
                reason=(
                    f"Verified {len(verified_inputs)} input(s); "
                    f"rejected {len(rejected_inputs)} unsupported "
                    "LLM proposal(s)."
                ),
                verified_extraction=verified_extraction,
                rejected_inputs=tuple(rejected_inputs),
            )

        return InputVerificationResult(
            valid=True,
            reason=(
                "All extracted inputs are grounded in discovery evidence."
            ),
            verified_extraction=verified_extraction,
        )

    def _verify_candidate(
        self,
        candidate: InputCandidate,
        context: CapabilityContext,
        seen_names: set[str],
    ) -> InputVerificationResult:

        # 1. Input names must be unique.
        if candidate.name in seen_names:
            return self._invalid(
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
            return self._invalid(
                reason=(
                    f"Source step {candidate.source_step} "
                    "does not exist in the successful interactions."
                ),
            )

        # 3. The current reusable-input implementation only accepts
        # values that were explicitly supplied through FILL actions.
        #
        # A CLICK target such as "Savings" or "Open Member" describes
        # navigation/semantics and must not become a runtime input.
        if source_interaction.action != ActionType.FILL:
            return self._invalid(
                reason=(
                    f"Source step {candidate.source_step} "
                    "is not an eligible input interaction."
                ),
            )

        # 4. The source action must contain an actual value.
        if source_interaction.value is None:
            return self._invalid(
                reason=(
                    f"Source step {candidate.source_step} "
                    "does not contain an input value."
                ),
            )

        # 5. The LLM's claimed value must exactly match the value
        # supplied during successful discovery.
        if source_interaction.value != candidate.observed_value:
            return self._invalid(
                reason=(
                    f"Observed value '{candidate.observed_value}' "
                    f"does not match source step "
                    f"{candidate.source_step} value "
                    f"'{source_interaction.value}'."
                ),
            )

        # 6. The value must also be grounded in the original
        # user request.
        if candidate.observed_value not in context.user_request:
            return self._invalid(
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
            verified_extraction=InputExtractionResult(
                inputs=[candidate],
            ),
        )

    def _eligible_source_steps(
        self,
        context: CapabilityContext,
    ) -> set[int]:

        return {
            interaction.step
            for interaction in context.interactions
            if (
                interaction.action == ActionType.FILL
                and interaction.value is not None
                and interaction.value in context.user_request
            )
        }

    @staticmethod
    def _invalid(
        *,
        reason: str,
    ) -> InputVerificationResult:

        return InputVerificationResult(
            valid=False,
            reason=reason,
            verified_extraction=InputExtractionResult(
                inputs=[],
            ),
        )