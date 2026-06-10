# utils/llm_helpers.py

import json
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="qwen/qwen3.5-397b-a17b", temperature=0)
llm_json = llm.bind(response_format={"type": "json_object"})


def parse_json_response(response, model_class):
    """Parst LLM JSON-Response in ein Pydantic Model."""
    content = response.content

    # Manchmal wrapped das LLM JSON in ```json ... ```
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    content = content.strip()

    try:
        data = json.loads(content)
        return model_class(**data)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  ⚠️ JSON Parse Fehler: {e}")
        print(f"  📝 Raw Response: {content[:500]}")
        raise
