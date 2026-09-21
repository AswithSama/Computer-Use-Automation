import json
from collections.abc import Callable

from app.agent.schemas.capability import CapabilityArtifact
from app.agent.capability.registry import SelectionContext


class SelectionContextGenerator:
    def __init__(self, ask_llm: Callable[[str], str]):
        self.ask_llm = ask_llm

    def generate(
        self,
        *,
        user_request: str,
        artifact: CapabilityArtifact,
    ) -> SelectionContext:
        # The compiled artifact contains the reusable workflow,
        # including input placeholders rather than the specific
        # member ID used during discovery.
        workflow = artifact.model_dump(
            mode="json",
            include={"description", "inputs", "actions", "outputs"},
        )

        prompt = (
            "Create selection metadata for a browser automation "
            "that has already been discovered.\n"
            "Use the supplied workflow as evidence. Do not invent "
            "additional actions, required inputs, or outputs.\n"
            "Distinguish values supplied by the user from values "
            "the automation reads from the website.\n"
            "The workflow summary should explain the business-level "
            "sequence, not repeat low-level browser locators.\n"
            "Example goals should be alternative phrasings of the "
            "same operation, with example input values only.\n"
            "Return only JSON with exactly these keys: "
            "use_when, workflow_summary, example_goals.\n\n"
            f"Original request:\n{user_request}\n\n"
            f"Compiled workflow:\n{json.dumps(workflow, indent=2)}"
        )

        response = self.ask_llm(prompt)

        return SelectionContext.model_validate_json(response)