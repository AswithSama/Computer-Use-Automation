import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from app.agent.discovery.output_binding.output_locator import (
    OutputStructuralContext,
)


class TableRowMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    value: str


class TableOutputBindingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["table"]
    row_match: TableRowMatch
    value_column: str


class OutputBindingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_name: str
    binding: TableOutputBindingProposal


OUTPUT_BINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "output_name": {
            "type": "string",
        },
        "binding": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["table"],
                },
                "row_match": {
                    "type": "object",
                    "properties": {
                        "column": {
                            "type": "string",
                        },
                        "value": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "column",
                        "value",
                    ],
                    "additionalProperties": False,
                },
                "value_column": {
                    "type": "string",
                },
            },
            "required": [
                "kind",
                "row_match",
                "value_column",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "output_name",
        "binding",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """
You define reusable output extraction rules for a
computer-use automation system.

The output value has already been discovered and verified.
The DOM structure surrounding that output has also already
been collected deterministically.

Your job is NOT to discover new page information.

Your job is to identify the semantic relationship in the
provided structure that can locate the same logical output
during future executions with different business data.

For a table output:

1. Choose a row_match column and value that identify the
   semantic row containing the requested output.

2. Prefer semantic properties such as type, category,
   purpose, or another stable business meaning.

3. Avoid discovery-specific identifiers such as account
   numbers, member IDs, transaction IDs, generated IDs,
   or other values that are likely to change between
   executions.

4. row_match.column must exactly match one provided header.

5. row_match.value must exactly match the corresponding
   value in the provided row.

6. value_column must exactly match the provided
   output_column.

7. Do not invent any column or value.

You are proposing a binding only.
Deterministic code will verify the proposal before it can
be stored in the reusable capability.
"""


class OutputBindingLLM:
    def __init__(
        self,
        client: OpenAI,
        model: str,
    ):
        self.client = client
        self.model = model

    def propose(
        self,
        context: OutputStructuralContext,
    ) -> OutputBindingProposal:

        if context.structure != "table":
            raise ValueError(
                "OutputBindingLLM currently supports "
                "table outputs only."
            )

        input_data = {
            "output": {
                "name": context.output_name,
                "type": context.output_type,
                "observed_value": context.observed_value,
            },
            "structure": {
                "kind": context.structure,
                "headers": context.headers,
                "containing_row": context.containing_row,
                "output_column": context.output_column,
            },
        }

        response = self.client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=json.dumps(
                input_data,
                indent=2,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "output_binding",
                    "strict": True,
                    "schema": OUTPUT_BINDING_SCHEMA,
                }
            },
        )

        return OutputBindingProposal.model_validate_json(
            response.output_text
        )