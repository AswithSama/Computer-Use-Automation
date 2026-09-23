from app.agent.llm.client import StructuredLLMClient
from app.agent.schemas.discovery import BrowserAction

SYSTEM_PROMPT = """
You are a browser reasoning agent.

Your job is to complete the user's task by examining the current webpage
observation and choosing exactly ONE next action.

Rules:

1. Use only information present in:
   - the user's request
   - the current webpage observation

2. Never invent page elements.

3. When targeting an element, copy its:
   - ref into target_ref
   - semantic role into target_role
   - accessible name into target_name

4. The target must exist in the CURRENT page observation.

5. If entering a value, propose the value needed for the action.
   Do not classify or describe where the value came from.
   Value grounding is handled separately by the validator.

6. Do not assume future pages or elements exist.

7. Choose exactly ONE action at a time.

8. After an action changes the page, reason again from the new observation.

9. If the current observation is insufficient or ambiguous,
   choose "request_visual".

10. If the task cannot safely continue, choose "request_human".

11. Choose "finish" only when the current page contains enough evidence
    to answer the user's request.

12. When using "finish":
    - put the concise final user-facing answer in result
    - use only information supported by the current page observation
    - do not target an element
    - populate outputs with all specific data values requested by the user
    - include only outputs relevant to the user's request
    - do not include incidental page data that the user did not request

    Each output defines one semantic value returned by the completed task.

    Each output must contain:

    - name:
      A stable, reusable snake_case semantic name describing what the
      output represents.

      The name must describe the meaning of the output, not its current
      observed value and not user-specific data.

      Examples:
      savings_balance
      customer_name
      account_status
      transaction_count

    - type:
      The reusable semantic data type of the output.

      It must be exactly one of:
      string
      integer
      number
      boolean
      date
      currency

    - value:
      The exact value observed in the current page observation for this
      specific discovery run.

    The output name and type together define the reusable output contract
    for future deterministic replay.

    The value is discovery-run evidence only. It may change on future
    executions and must not be encoded into the reusable output definition.

13. For all non-finish actions, outputs must be null.

14. Keep reason short and specific.
"""


BROWSER_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "click",
                "fill",
                "go_back",
                "navigate",
                "wait",
                "finish",
                "request_visual",
                "request_human",
            ],
        },
        "target_ref": {
            "type": ["string", "null"],
        },
        "target_role": {
            "type": ["string", "null"],
        },
        "target_name": {
            "type": ["string", "null"],
        },
        "value": {
            "type": ["string", "null"],
        },
        "url": {
            "type": ["string", "null"],
        },
        "result": {
            "type": ["string", "null"],
        },
        "outputs": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "string",
                            "integer",
                            "number",
                            "boolean",
                            "date",
                            "currency",
                        ],
                    },
                    "value": {
                        "type": "string",
                    },
                },
                "required": [
                    "name",
                    "type",
                    "value",
                ],
                "additionalProperties": False,
            },
        },
        "reason": {
            "type": "string",
        },
    },
    "required": [
        "action",
        "target_ref",
        "target_role",
        "target_name",
        "value",
        "url",
        "result",
        "outputs",
        "reason",
    ],
    "additionalProperties": False,
}


class BrowserLLM:
    def __init__(self):
        self.llm = StructuredLLMClient()

        # Kept for collaborators that intentionally share the same
        # client/model during one discovery run.
        self.client = self.llm.client
        self.model = self.llm.model

    def decide(
        self,
        user_request: str,
        current_url: str,
        observation: str,
    ) -> BrowserAction:

        input_data = {
            "user_request": user_request,
            "current_url": current_url,
            "page_observation": observation,
        }

        output_text = self.llm.create_json_schema(
            instructions=SYSTEM_PROMPT,
            input_data=input_data,
            schema_name="browser_action",
            schema=BROWSER_ACTION_SCHEMA,
        )

        return BrowserAction.model_validate_json(
            output_text
        )