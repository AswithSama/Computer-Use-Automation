import json
import os

from openai import OpenAI

from app.agent.discovery.models import BrowserAction


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
    - put the final user-facing answer in result
    - use only information supported by the current page observation
    - do not target an element

13. Keep reason short and specific.
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
        "target_ref": {"type": ["string", "null"]},
        "target_role": {"type": ["string", "null"]},
        "target_name": {"type": ["string", "null"]},
        "value": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]},
        "result": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": [
        "action",
        "target_ref",
        "target_role",
        "target_name",
        "value",
        "url",
        "result",
        "reason",
    ],
    "additionalProperties": False,
}


class BrowserLLM:
    def __init__(self):
        self.client = OpenAI()
        self.model = os.getenv("BROWSER_MODEL", "gpt-5.6-luna")

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

        response = self.client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=json.dumps(input_data, indent=2),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "browser_action",
                    "strict": True,
                    "schema": BROWSER_ACTION_SCHEMA,
                }
            },
        )

        return BrowserAction.model_validate_json(response.output_text)