from openai import OpenAI


def ask_selection_llm(prompt: str) -> str:
    """
    Reusable LLM adapter for:
      1. Selecting an approved capability.
      2. Generating selection context after discovery.

    Both callers supply their own task-specific prompts.
    """
    model = "gpt-5-mini"

    client = OpenAI()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Follow the supplied task instructions. "
                    "Return only a valid JSON object."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("The LLM returned an empty response.")

    return content
