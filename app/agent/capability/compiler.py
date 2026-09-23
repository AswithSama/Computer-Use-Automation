from urllib.parse import urlparse

from app.agent.capability.checkpoint_detector import (
    CheckpointCandidate,
    CheckpointEvidenceType,
)
from app.agent.capability.context import CapabilityContext
from app.agent.capability.inputs.input_extraction import (
    InputExtractionResult,
)
from app.agent.schemas.capability import (
    CapabilityAction,
    CapabilityArtifact,
    CapabilityCheckpoint,
    CapabilityInput,
    CapabilityOutput,
    CapabilityTarget,
    TableOutputBinding,
    TableRowMatch,
)
from app.agent.schemas.discovery import ActionType
from app.agent.schemas.recording import (
    DiscoveredOutputLocation,
)


class CapabilityCompiler:

    # Only actions that deterministic replay currently intends
    # to support may be compiled into a reusable capability.
    REPLAYABLE_ACTIONS = frozenset({
        ActionType.CLICK,
        ActionType.FILL,
        ActionType.NAVIGATE,
        ActionType.WAIT,
    })

    def compile(
        self,
        capability_id: str,
        description: str,
        context: CapabilityContext,
        extracted_inputs: InputExtractionResult,
        checkpoint_candidates: list[CheckpointCandidate],
        output_locations: list[DiscoveredOutputLocation],
    ) -> CapabilityArtifact:

        inputs = self.compile_inputs(
            extracted_inputs=extracted_inputs,
        )

        actions = self.compile_actions(
            context=context,
            extracted_inputs=extracted_inputs,
        )

        checkpoints = self.compile_checkpoints(
            context=context,
            checkpoint_candidates=checkpoint_candidates,
            extracted_inputs=extracted_inputs,
        )

        outputs = self.compile_outputs(
            context=context,
            output_locations=output_locations,
            extracted_inputs=extracted_inputs,
        )

        return CapabilityArtifact(
            schema_version="1.0",
            capability_id=capability_id,
            description=description,
            inputs=inputs,
            actions=actions,
            checkpoints=checkpoints,
            outputs=outputs,
        )

    def compile_inputs(
        self,
        extracted_inputs: InputExtractionResult,
    ) -> list[CapabilityInput]:

        return [
            CapabilityInput(
                name=candidate.name,
                type=candidate.type,
                required=True,
                description=candidate.description,
            )
            for candidate in extracted_inputs.inputs
        ]

    def compile_actions(
        self,
        context: CapabilityContext,
        extracted_inputs: InputExtractionResult,
    ) -> list[CapabilityAction]:

        input_by_step = {
            candidate.source_step: candidate
            for candidate in extracted_inputs.inputs
        }

        compiled_actions: list[CapabilityAction] = []

        for interaction in context.interactions:

            # Do not create a reusable capability containing an action
            # that deterministic replay does not support.
            if interaction.action not in self.REPLAYABLE_ACTIONS:
                raise ValueError(
                    f"Discovery action '{interaction.action.value}' "
                    "cannot be compiled into deterministic replay."
                )

            input_candidate = input_by_step.get(
                interaction.step
            )

            # -----------------------------------------------------
            # Parameterize action value.
            # -----------------------------------------------------

            value = interaction.value

            if input_candidate is not None:
                value = f"{{{{{input_candidate.name}}}}}"

            # -----------------------------------------------------
            # Parameterize navigation URL.
            #
            # Example:
            # /members/12345
            #
            # becomes:
            # /members/{{member_id}}
            # -----------------------------------------------------

            url = interaction.url

            if url is not None:
                for candidate in extracted_inputs.inputs:
                    if candidate.observed_value:
                        url = url.replace(
                            candidate.observed_value,
                            f"{{{{{candidate.name}}}}}",
                        )

            # -----------------------------------------------------
            # Compile semantic target.
            # -----------------------------------------------------

            target = None

            if (
                interaction.target_role is not None
                and interaction.target_name is not None
            ):
                target = CapabilityTarget(
                    role=interaction.target_role,
                    name=interaction.target_name,
                )

            compiled_actions.append(
                CapabilityAction(
                    action=interaction.action,
                    target=target,
                    value=value,
                    url=url,
                )
            )

        return compiled_actions

    def compile_checkpoints(
        self,
        context: CapabilityContext,
        checkpoint_candidates: list[CheckpointCandidate],
        extracted_inputs: InputExtractionResult,
    ) -> list[CapabilityCheckpoint]:

        # compile_actions() creates one action per interaction,
        # preserving this same order.
        replay_index_by_source_step: dict[int, int] = {}

        for replay_index, interaction in enumerate(
            context.interactions,
            start=1,
        ):
            if interaction.step in replay_index_by_source_step:
                raise ValueError(
                    f"Duplicate discovery step "
                    f"{interaction.step} in capability context."
                )

            replay_index_by_source_step[interaction.step] = (
                replay_index
            )

        checkpoints: list[CapabilityCheckpoint] = []

        for candidate in checkpoint_candidates:

            # Only URL checkpoints are currently supported.
            if (
                candidate.evidence_type
                != CheckpointEvidenceType.URL
            ):
                continue

            replay_index = replay_index_by_source_step.get(
                candidate.source_step
            )

            # Never attach a checkpoint to a different action
            # when its original action was not compiled.
            if replay_index is None:
                raise ValueError(
                    f"Cannot compile checkpoint from discovery "
                    f"step {candidate.source_step}: its action "
                    f"is missing from the compiled replay path."
                )

            parsed_url = urlparse(candidate.after_url)

            # Keep the application path rather than the host.
            url_pattern = parsed_url.path

            if parsed_url.query:
                url_pattern += f"?{parsed_url.query}"

            # Parameterize discovery-specific input values.
            for input_candidate in extracted_inputs.inputs:
                if input_candidate.observed_value:
                    url_pattern = url_pattern.replace(
                        input_candidate.observed_value,
                        f"{{{{{input_candidate.name}}}}}",
                    )

            checkpoints.append(
                CapabilityCheckpoint(
                    after_action=replay_index,
                    url_pattern=url_pattern,
                    required_text=[],
                )
            )

        return checkpoints

    def compile_outputs(
        self,
        context: CapabilityContext,
        output_locations: list[DiscoveredOutputLocation],
        extracted_inputs: InputExtractionResult | None = None,
    ) -> list[CapabilityOutput]:

        # Match each semantic output with the verified
        # binding produced during discovery.
        location_by_name = {
            location.output_name: location
            for location in output_locations
        }

        compiled_outputs: list[CapabilityOutput] = []

        for output in context.completion.outputs:

            location = location_by_name.get(
                output.name
            )

            if location is None:
                raise ValueError(
                    f"No verified output binding found "
                    f"for output '{output.name}'."
                )

            binding = location.binding

            # MVP currently supports verified table
            # output bindings.
            if binding.kind != "table":
                raise ValueError(
                    f"Unsupported verified output "
                    f"binding kind: '{binding.kind}'."
                )

            row_match_value = binding.row_match.value
            observed_matches = [
                candidate
                for candidate in (
                    extracted_inputs.inputs if extracted_inputs is not None else []
                )
                if candidate.observed_value == row_match_value
            ]
            if len(observed_matches) > 1:
                raise ValueError(
                    "Row identity matches multiple runtime input parameters."
                )
            if observed_matches:
                row_match_value = f"{{{{{observed_matches[0].name}}}}}"
            elif (
                binding.row_match.column == binding.value_column
                and binding.row_match.value == location.observed_value
            ):
                raise ValueError(
                    "An output value cannot identify its own row across replay."
                )

            compiled_outputs.append(
                CapabilityOutput(
                    name=output.name,
                    type=output.type,
                    binding=TableOutputBinding(
                        kind="table",
                        row_match=TableRowMatch(
                            column=binding.row_match.column,
                            value=row_match_value,
                        ),
                        value_column=binding.value_column,
                    ),
                )
            )

        return compiled_outputs