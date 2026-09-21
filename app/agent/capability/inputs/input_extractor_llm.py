import json

from openai import OpenAI

from app.agent.capability.inputs.input_extraction import (
    InputExtractionResult,
)
from app.agent.capability.context import CapabilityContext


class InputExtractorLLM:

    def __init__(self) -> None:
        self.client = OpenAI()

    def extract(
        self,
        context: CapabilityContext,
    ) -> InputExtractionResult:

        interactions = [
            interaction.model_dump(mode="json")
            for interaction in context.interactions
        ]

        user_message = f"""
The following browser automation successfully completed
the user's request.

ORIGINAL USER REQUEST:
{context.user_request}

SUCCESSFUL INTERACTIONS:
{json.dumps(interactions, indent=2)}

The interactions above are the successful UI actions from
the final candidate path.

Identify the user-specific values or choices that should
become reusable input parameters when this same capability
is executed for future requests.

Use the interaction step numbers and observed values as
evidence for every input you identify.
""".strip()

        response = self.client.responses.parse(
            model="gpt-5-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You identify reusable input parameters from a "
                        "successfully completed browser automation run. "

                        "An input is information or a user choice that may "
                        "change between future executions of the same "
                        "capability. "

                        "Do not treat ordinary navigation or submission "
                        "actions as inputs. "

                        "Use snake_case names for input parameters, such as "
                        "'member_id' or 'start_date'. "

                        "Identifiers such as member IDs, account IDs, "
                        "reference numbers, and similar identifiers should "
                        "normally use type 'string' even when the observed "
                        "value contains only digits. "

                        "Use only the supplied evidence. "

                        "source_step must reference the successful "
                        "interaction that provides evidence for the input. "

                        "observed_value must exactly match a value present "
                        "in that interaction."
                    ),
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            text_format=InputExtractionResult,
        )

        return response.output_parsed