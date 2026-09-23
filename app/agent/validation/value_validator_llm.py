from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.agent.llm.client import StructuredLLMClient


class ValidatorDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class ValidatorLLMResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ValidatorDecision
    reason: str


VALIDATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": [
                "approve",
                "reject",
                "escalate_to_human",
            ],
        },
        "reason": {
            "type": "string",
        },
    },
    "required": [
        "decision",
        "reason",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """
You are a validation agent.

You do NOT operate the browser.
You do NOT create browser actions.
You do NOT modify proposed values.

You receive a browser action containing a value that deterministic
validation could not directly ground in trusted user input or trusted
page information.

Your only responsibility is to decide whether the proposed value is
sufficiently justified.

Return exactly one decision:

- approve
- reject
- escalate_to_human

Rules:

1. APPROVE only when the proposed value is clearly justified by the
   provided evidence and business validation policy.

2. REJECT when the proposed value conflicts with the evidence or policy,
   or appears unjustified.

3. ESCALATE_TO_HUMAN when the evidence or policy is insufficient to
   safely approve or reject.

4. Never invent a replacement value.

5. Never modify the proposed value.

6. Never propose another browser action.

7. Treat the business validation policy as authoritative.
"""


class ValueValidatorLLM:
    def __init__(
        self,
        business_policy: str = "",
    ):
        self.llm = StructuredLLMClient()
        self.client = self.llm.client
        self.model = self.llm.model
        self.business_policy = business_policy

    def validate(
        self,
        user_request: str,
        action: dict,
        observation: str,
        deterministic_reason: str,
    ) -> ValidatorLLMResult:

        validation_context = {
            "user_request": user_request,
            "proposed_action": action,
            "page_observation": observation,
            "deterministic_validation_reason": (
                deterministic_reason
            ),
            "business_validation_policy": (
                self.business_policy
            ),
        }

        output_text = self.llm.create_json_schema(
            instructions=SYSTEM_PROMPT,
            input_data=validation_context,
            schema_name="validator_decision",
            schema=VALIDATOR_SCHEMA,
        )

        return ValidatorLLMResult.model_validate_json(
            output_text
        )