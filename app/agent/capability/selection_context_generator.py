import json

from app.agent.llm.client import StructuredLLMClient
from app.agent.schemas.capability import CapabilityArtifact
from app.agent.schemas.registry import SelectionContext


class SelectionContextGenerator:
    def __init__(self) -> None:
        self.llm = StructuredLLMClient()

    def generate(
        self,
        *,
        user_request: str,
        artifact: CapabilityArtifact,
    ) -> SelectionContext:

        workflow = artifact.model_dump(
            mode="json",
            include={
                "description",
                "inputs",
                "actions",
                "outputs",
            },
        )

        user_message = f"""
Create selection metadata for a browser automation that has
already been successfully discovered and compiled.

ORIGINAL REQUEST:
{user_request}

COMPILED WORKFLOW:
{json.dumps(workflow, indent=2)}

Use only the supplied workflow as evidence.

The fields mean:

use_when:
Describe when this capability should be selected.

workflow_summary:
Describe the business-level workflow concisely.
Do not repeat low-level browser selectors or element references.

example_goals:
Return alternative natural-language user requests for exactly
the same capability.

Each example_goals item MUST be a plain string.

Correct:
[
    "Get the savings balance for member 12345",
    "Show the savings balance for member 67890"
]

Incorrect:
[
    {{
        "goal": "Get the savings balance",
        "inputs": {{
            "member_id": "12345"
        }}
    }}
]

Do not invent additional inputs, outputs, actions, or capabilities.
Do not convert example goals into structured objects.
""".strip()

        return self.llm.parse_structured(
            input_messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate selection metadata for an already "
                        "compiled browser capability. "
                        "Use only the supplied evidence. "
                        "Do not invent new workflow behavior. "
                        "example_goals must contain only plain strings."
                    ),
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            text_format=SelectionContext,
        )