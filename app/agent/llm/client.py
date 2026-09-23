import json
import os
from typing import Any

from openai import OpenAI

DEFAULT_MODEL = "gpt-5-mini"
MODEL_ENV_VAR = "OPENAI_MODEL"


class StructuredLLMClient:
    """Shared OpenAI transport for structured model calls."""

    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        model: str | None = None,
    ) -> None:
        self.client = client or OpenAI()
        self.model = (
            model
            or os.getenv(MODEL_ENV_VAR)
            or DEFAULT_MODEL
        )

    def create_json_schema(
        self,
        *,
        instructions: str,
        input_data: Any,
        schema_name: str,
        schema: dict,
    ) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=self._serialize_input(input_data),
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        )

        return response.output_text

    def parse_structured(
        self,
        *,
        input_messages: list[dict[str, str]],
        text_format: type,
    ) -> Any:
        response = self.client.responses.parse(
            model=self.model,
            input=input_messages,
            text_format=text_format,
        )

        return response.output_parsed

    def create_json_object_chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str | None:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            response_format={"type": "json_object"},
        )

        return response.choices[0].message.content

    @staticmethod
    def _serialize_input(input_data: Any) -> str:
        if isinstance(input_data, str):
            return input_data

        return json.dumps(
            input_data,
            indent=2,
        )
