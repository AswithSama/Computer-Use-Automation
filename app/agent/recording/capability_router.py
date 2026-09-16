import json
import os

from openai import OpenAI

from app.agent.discovery.models import (
    CapabilitySummary,
    RouteDecision,
    TaskRequest,
)


ROUTER_INSTRUCTIONS = """
You are a capability router for a computer-use automation system.

You receive:
1. A user's natural-language goal.
2. A target application.
3. A catalog of capabilities that were previously discovered and recorded.

Your job is NOT to operate the website.

Your only job is to decide whether an existing capability can satisfy the
user's requested business task.

Choose REPLAY only when an existing capability clearly performs the same
business operation requested by the user.

Do not choose a capability merely because it is somewhat related.

If a capability matches:
- return mode "replay"
- return its capability_id
- extract the required input values from the user's goal

If no existing capability clearly matches:
- return mode "discover"
- capability_id must be null
- arguments must be empty

Never invent a capability.
Never invent missing input values.
When uncertain, prefer "discover".
"""


ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["replay", "discover"],
        },
        "capability_id": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ]
        },
        "arguments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["name", "value"],
                "additionalProperties": False,
            },
        },
        "reason": {
            "type": "string"
        },
    },
    "required": [
        "mode",
        "capability_id",
        "arguments",
        "reason",
    ],
    "additionalProperties": False,
}


class CapabilityRouter:
    def __init__(self):
        self.client = OpenAI()

        self.model = os.getenv(
            "ROUTER_MODEL",
            "gpt-5.6-luna",
        )

    def route(
        self,
        request: TaskRequest,
        capabilities: list[CapabilitySummary],
    ) -> RouteDecision:

        payload = {
            "goal": request.goal,
            "target": request.target,
            "available_capabilities": [
                capability.model_dump()
                for capability in capabilities
            ],
        }

        response = self.client.responses.create(
            model=self.model,
            instructions=ROUTER_INSTRUCTIONS,
            input=json.dumps(payload, indent=2),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "capability_route",
                    "strict": True,
                    "schema": ROUTE_SCHEMA,
                }
            },
        )

        return RouteDecision.model_validate_json(
            response.output_text
        )