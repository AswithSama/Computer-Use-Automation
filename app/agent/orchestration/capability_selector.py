import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.schemas.registry import StoredCapability


EligibleCapability = tuple[Path, StoredCapability]

# The orchestrator expects:
# ((selected_path, stored_capability), extracted_inputs)
SelectionResult = tuple[EligibleCapability, dict[str, str]]


class SelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["selected", "no_match"]
    candidate_id: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)


class CapabilitySelector:
    def __init__(
        self,
        ask_llm: Callable[[str], str],
        direct_selection_limit: int = 30,
    ):
        self.ask_llm = ask_llm
        self.direct_selection_limit = direct_selection_limit

    def _retrieve_candidates(
        self,
        user_request: str,
        eligible: list[EligibleCapability],
    ) -> list[EligibleCapability]:
        # Future BM25 / hybrid retrieval implementation.
        # Do not send an oversized catalog to the LLM.
        raise NotImplementedError(
            "Capability retrieval is not implemented yet."
        )

    def select(
        self,
        *,
        user_request: str,
        eligible: list[EligibleCapability],
    ) -> SelectionResult | None:

        if not user_request.strip() or not eligible:
            return None

        candidates = eligible

        if len(eligible) > self.direct_selection_limit:
            candidates = self._retrieve_candidates(
                user_request=user_request,
                eligible=eligible,
            )

        # Candidate IDs are temporary identifiers for this
        # selection call, not filesystem paths or capability IDs.
        candidate_lookup = {
            f"candidate_{index}": candidate
            for index, candidate in enumerate(
                candidates,
                start=1,
            )
        }

        catalog = []

        for candidate_id, (_, stored) in candidate_lookup.items():
            artifact = stored.artifact
            context = stored.selection_context

            catalog.append(
                {
                    "candidate_id": candidate_id,
                    "capability_id": artifact.capability_id,
                    "description": artifact.description,
                    "use_when": (
                        context.use_when
                        if context is not None
                        else artifact.description
                    ),
                    "workflow_summary": (
                        context.workflow_summary
                        if context is not None
                        else ""
                    ),
                    "example_goals": (
                        context.example_goals
                        if context is not None
                        else []
                    ),
                    "inputs": [
                        {
                            "name": parameter.name,
                            "type": parameter.type,
                            "required": parameter.required,
                            "description": parameter.description,
                        }
                        for parameter in artifact.inputs
                    ],
                    "outputs": [
                        {
                            "name": output.name,
                            "type": output.type,
                        }
                        for output in artifact.outputs
                    ],
                }
            )

        prompt = (
            "You are selecting an existing, approved automation capability.\n"
            "Choose a capability only if its described operation "
            "matches the user's requested operation.\n"
            "Different runtime input values do not make an otherwise "
            "matching capability unsuitable.\n"
            "Do not invent capabilities or candidate IDs.\n"
            "If no capability matches, return no_match.\n\n"

            "For a selected capability, extract runtime inputs "
            "that the user explicitly provided in their request.\n"
            "Use only input names declared by the selected capability.\n"
            "Do not guess missing input values.\n"
            "Do not treat values that the automation retrieves from "
            "the website as user-supplied inputs.\n"
            "If a required input is missing, still select the "
            "matching capability and omit that input. "
            "The runtime will request it later.\n\n"

            "Return only a JSON object with exactly three keys: "
            "'decision', 'candidate_id', and 'inputs'.\n\n"

            "For a selection, return:\n"
            '{"decision": "selected", '
            '"candidate_id": "candidate_1", '
            '"inputs": {"member_id": "12345"}}\n\n'

            "The example above illustrates the response format only. "
            "Use the actual candidate ID and inputs from this request.\n\n"

            "For no match, return:\n"
            '{"decision": "no_match", '
            '"candidate_id": null, '
            '"inputs": {}}\n\n'

            f"User request:\n{user_request}\n\n"
            "Eligible capability catalog:\n"
            f"{json.dumps(catalog, indent=2)}"
        )

        response_text = self.ask_llm(prompt)

        try:
            response = SelectionResponse.model_validate_json(
                response_text
            )
        except ValidationError as exc:
            raise ValueError(
                "Capability selector returned an invalid response."
            ) from exc

        # -----------------------------------------------------
        # No matching capability: allow orchestration to
        # route the request to discovery.
        # -----------------------------------------------------
        if response.decision == "no_match":
            if response.candidate_id is not None or response.inputs:
                raise ValueError(
                    "A no_match response must have "
                    "candidate_id=null and inputs={}."
                )

            return None

        # -----------------------------------------------------
        # Validate that the selected candidate exists in the
        # approved catalog supplied to this selection call.
        # -----------------------------------------------------
        if response.candidate_id not in candidate_lookup:
            raise ValueError(
                "Capability selector chose an unavailable candidate."
            )

        selected = candidate_lookup[response.candidate_id]
        _, stored = selected

        # -----------------------------------------------------
        # Validate extracted input names against the selected
        # capability's declared input contract.
        # -----------------------------------------------------
        allowed_input_names = {
            parameter.name
            for parameter in stored.artifact.inputs
        }

        unknown_input_names = (
            set(response.inputs) - allowed_input_names
        )

        if unknown_input_names:
            raise ValueError(
                "Capability selector returned undeclared inputs: "
                f"{sorted(unknown_input_names)}"
            )

        # Missing required inputs are intentionally permitted.
        # Replay's REQUEST_INPUT recovery handles them.
        return selected, response.inputs