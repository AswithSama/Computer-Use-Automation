from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from app.agent.discovery.output_binding.output_locator import (
    OutputStructuralContext,
)
from app.agent.llm.client import StructuredLLMClient


# Intentionally separate from the committed capability schema.
# These models represent untrusted LLM proposals that must be
# deterministically verified before becoming artifact bindings.
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

The requested output has already been discovered, and the
structure surrounding it has been collected.

Your task is to identify a structural relationship that
locates the same logical output during future executions,
even when runtime inputs and business data change.

The observed row is evidence of where the output was found
during discovery. It is not, by itself, a definition of
what the user intended to retrieve.

Interpret the original user request together with the
provided structural context and input evidence.

COLUMN SELECTION PRIORITY

Multiple columns may each uniquely identify the observed row.
Uniqueness alone does not make a column the correct choice.
When more than one column could serve as row_match.column,
choose between them using this priority order, highest first:

1. CATEGORICAL / CLASSIFICATION COLUMNS whose value set is
   closed and small (e.g. Type, Status, Category), where the
   observed value in that column matches a term the user's
   request uses to describe what kind of record they want.
   This is the strongest signal of intent: it expresses WHAT
   the user asked for, not which specific record happened to
   be found.

2. RUNTIME-INPUT-DERIVED COLUMNS, where the column's observed
   value matches a value the user supplied as input evidence
   (e.g. a member ID the user typed in). These express WHICH
   specific record, parameterized by input, not an incidental
   fact about this one discovery run.

3. Everything else is INCIDENTAL and must not be chosen if a
   rule-1 or rule-2 column is available: free-text labels or
   nicknames (user-editable, no guaranteed relationship to the
   request), opaque identifiers (account numbers, row IDs,
   auto-generated codes), and any column that merely happens
   to be unique in this one observed table.

A column being "the only one that reads naturally in English"
or "the one containing the word from the request" is NOT
sufficient by itself if that match is coincidental (e.g. a
free-text nickname that happens to contain a keyword) rather
than structural (e.g. a Type/Category column whose defined
purpose is to classify rows into kinds).

WORKED EXAMPLE

Table headers: Account, Type, Nickname, Status, Current Balance
Row: Account=SAV-40082, Type=Savings, Nickname="Holiday Savings",
     Status=Open, Current Balance=$630.00
User request: "get the current savings balance"

Wrong: row_match.column = "Nickname", value = "Holiday Savings"
  (Nickname is free text; a different user's savings account
  could be nicknamed anything, e.g. "Rainy Day Fund". Matching
  worked here only because this label happened to contain the
  word "Savings" -- coincidence, not structure.)

Wrong: row_match.column = "Account", value = "SAV-40082"
  (Opaque per-account identifier. Uniquely identifies this row,
  but has no relationship to "savings" at all -- it identifies
  THIS row, not "the savings row" for any member.)

Correct: row_match.column = "Type", value = "Savings"
  (Type is a closed-set classification column. "Savings" is
  the exact term the user's request uses to describe the kind
  of account. Every member's table has exactly one row where
  Type = "Savings", regardless of what it's nicknamed or its
  account number. This condition is reusable and semantically
  grounded, not a coincidence of one observation.)

Determine what makes the observed row the correct row for
the user's request. Distinguish properties that express the
requested meaning from incidental properties that happen to
identify this particular observation.

Choose a row condition that preserves that meaning across
future executions. A condition is not reusable merely
because it uniquely identifies the observed row.

When the requested record is identified by a runtime input,
use the corresponding observed input value in the proposed
row condition (priority 2 above). A later compilation stage
will verify and parameterize that value.

The proposed binding must satisfy these structural
constraints:

1. row_match.column must exactly match a provided header.

2. row_match.value must exactly match the corresponding
   value in the provided containing row.

3. value_column must exactly match the provided
   output_column.

4. The row condition must identify exactly one appropriate
   row in the observed table.

5. Never use the changing output value itself as the row
   identifier.

6. Do not invent columns, values, input evidence, or
   information about future executions.

If the available structure does not support a meaningful
reusable binding, do not disguise an incidental match as
a reusable one.

You are proposing a binding only. Deterministic code will
verify the proposal against the observed structure before
it can be stored in a reusable capability.
"""


class OutputBindingLLM:
    def __init__(
        self,
        client: OpenAI,
        model: str,
    ):
        self.llm = StructuredLLMClient(
            client=client,
            model=model,
        )
        self.client = self.llm.client
        self.model = self.llm.model

    def propose(
        self,
        context: OutputStructuralContext,
        user_request: str,
        input_evidence: list[dict[str, str]] | None = None,
    ) -> OutputBindingProposal:

        if context.structure != "table":
            raise ValueError(
                "OutputBindingLLM currently supports "
                "table outputs only."
            )

        input_data = {
            "original_user_request": user_request,
            "output": {
                "name": context.output_name,
                "type": context.output_type,
                "observed_value": context.observed_value,
            },
            "user_supplied_input_evidence": input_evidence or [],
            "structure": {
                "kind": context.structure,
                "headers": context.headers,
                "containing_row": context.containing_row,
                "output_column": context.output_column,
            },
        }

        output_text = self.llm.create_json_schema(
            instructions=SYSTEM_PROMPT,
            input_data=input_data,
            schema_name="output_binding",
            schema=OUTPUT_BINDING_SCHEMA,
        )

        return OutputBindingProposal.model_validate_json(
            output_text
        )