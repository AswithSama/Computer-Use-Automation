import json

from app.agent.capability.context import CapabilityContext
from app.agent.capability.inputs.input_extraction import InputExtractionResult
from app.agent.llm.client import StructuredLLMClient
from app.agent.schemas.discovery import ActionType


class InputExtractorLLM:

    def __init__(self) -> None:
        self.llm = StructuredLLMClient()
        self.client = self.llm.client
        self.model = self.llm.model

    def extract(
        self,
        context: CapabilityContext,
    ) -> InputExtractionResult:

        # For the current system, reusable runtime inputs must come
        # from values that the user actually supplied through a
        # successful FILL interaction.
        #
        # This prevents capability semantics such as "Savings" from
        # being promoted into runtime inputs unless they were actually
        # entered by the user during discovery.
        eligible_interactions = [
            interaction
            for interaction in context.interactions
            if (
                interaction.action == ActionType.FILL
                and interaction.value is not None
                and interaction.value in context.user_request
            )
        ]

        interactions = [
            interaction.model_dump(mode="json")
            for interaction in eligible_interactions
        ]

        user_message = f"""
The following browser automation successfully completed
the user's request.

ORIGINAL USER REQUEST:
{context.user_request}

ELIGIBLE INPUT INTERACTIONS:
{json.dumps(interactions, indent=2)}

Only the interactions above are eligible evidence for reusable
runtime inputs.

Identify the user-specific values that should become reusable
input parameters when this same capability is executed for
future requests.

Important rules:

1. Every proposed input must come from one of the eligible
   interactions above.

2. source_step must exactly match the step that supplied the value.

3. observed_value must exactly match that interaction's value.

4. Do not infer an input only because a word appears in the
   original user request.

5. Capability-defining concepts such as "savings", "balance",
   "member", or "account" are not runtime inputs unless the user
   actually entered them through an eligible interaction.

Example:

Request:
"Get the savings balance for member 12345"

Eligible interaction:
Member ID = "12345"

Correct reusable input:
member_id = "12345"

Incorrect reusable input:
account_type = "Savings"

"Savings" describes what the capability does. It was not supplied
through an eligible input interaction.
""".strip()

        return self.llm.parse_structured(
            input_messages=[
                {
                    "role": "system",
                    "content": (
                        "You identify reusable runtime input parameters "
                        "from a successfully completed browser automation "
                        "run. "

                        "An input is a value supplied by the user during "
                        "the successful interaction path that may change "
                        "between future executions of the same capability. "

                        "Only propose inputs supported by the supplied "
                        "eligible interactions. "

                        "Do not turn capability semantics, navigation "
                        "labels, output concepts, page content, or task "
                        "descriptions into inputs. "

                        "Do not treat ordinary navigation or submission "
                        "actions as inputs. "

                        "Use snake_case names for input parameters, such "
                        "as 'member_id' or 'start_date'. "

                        "Identifiers such as member IDs, account IDs, "
                        "reference numbers, and similar identifiers should "
                        "normally use type 'string' even when the observed "
                        "value contains only digits. "

                        "source_step must reference the successful "
                        "interaction that directly supplied the input. "

                        "observed_value must exactly equal the value from "
                        "that interaction. "

                        "If there are no eligible runtime inputs, return "
                        "an empty inputs list."
                    ),
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            text_format=InputExtractionResult,
        )