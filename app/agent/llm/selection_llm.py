from app.agent.llm.client import StructuredLLMClient


def ask_selection_llm(prompt: str) -> str:
    """
    Reusable LLM adapter for:
      1. Selecting an approved capability.
      2. Generating selection context after discovery.

    Both callers supply their own task-specific prompts.
    """
    llm = StructuredLLMClient()

    content = llm.create_json_object_chat(
        system_prompt=(
            "Follow the supplied task instructions. "
            "Return only a valid JSON object."
        ),
        user_prompt=prompt,
    )

    if not content:
        raise ValueError("The LLM returned an empty response.")

    return content
