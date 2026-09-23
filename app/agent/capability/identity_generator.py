"""Name a verified operation without coupling identity to discovery input values."""

import json
import re

from pydantic import BaseModel, ConfigDict

from app.agent.llm.client import StructuredLLMClient
from app.agent.capability.context import CapabilityContext
from app.agent.capability.inputs.input_extraction import InputExtractionResult


class CapabilityIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    description: str


class CapabilityIdentityGenerator:
    def __init__(self):
        self.llm = StructuredLLMClient()

    def generate(
        self,
        *,
        context: CapabilityContext,
        extracted_inputs: InputExtractionResult,
    ) -> CapabilityIdentity:
        outputs = [
            {"name": output.name, "type": output.type}
            for output in context.completion.outputs
        ]
        inputs = [item.name for item in extracted_inputs.inputs]
        request = (
            "Name the reusable *operation*, not this execution. "
            "Return a semantic capability_id of the form get_<operation> "
            "and a short description. The ID must distinguish different "
            "business questions even if their navigation paths are identical. "
            "Prefer an ID based on the actual requested output(s). "
            "Do not include member IDs, account IDs, dates, observed output "
            "values, or other per-request data in the ID or description. "
            "Do not invent additional inputs or outputs. "
            "Use only snake_case ASCII letters/numbers/underscores for ID. "
            "Return exactly the requested schema.\n"
            + json.dumps(
                {"user_request": context.user_request,
                 "input_names": inputs, "outputs": outputs},
                ensure_ascii=False,
            )
        )
        result = self.llm.parse_structured(
            input_messages=[
                {"role": "system", "content": (
                    "You name verified, read-only browser capabilities. "
                    "Names must be stable across different runtime input values."
                )},
                {"role": "user", "content": request},
            ],
            text_format=CapabilityIdentity,
        )
        if (
            len(result.capability_id) > 80
            or not re.fullmatch(r"get_[a-z][a-z0-9_]*", result.capability_id)
        ):
            raise ValueError("Generated capability identifier is invalid.")
        if not 10 <= len(result.description.strip()) <= 180:
            raise ValueError("Generated capability description is invalid.")
        for item in extracted_inputs.inputs:
            value = item.observed_value.strip()
            if value and (
                (len(value) >= 3 and value.casefold() in result.capability_id.casefold())
                or re.search(r"\b" + re.escape(value) + r"\b", result.description)
            ):
                raise ValueError(
                    "Generated capability metadata contains a runtime input value."
                )
        return result
