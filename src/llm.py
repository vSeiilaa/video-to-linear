import json
import re
from typing import Literal

Provider = Literal["openai", "claude", "gemini"]

PROVIDER_MODELS: dict[str, list[dict]] = {
    "openai": [
        {"id": "gpt-5.5", "label": "GPT-5.5"},
        {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini"},
    ],
    "claude": [
        {"id": "claude-opus-4-8", "label": "Claude Opus 4.8"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
    ],
    "gemini": [
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
        {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite"},
    ],
}

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.4-mini"


def call_llm_json(
    provider: Provider,
    model_id: str,
    system: str,
    user: str,
    api_key: str | None = None,
) -> str:
    """Call the given provider/model and return a raw JSON string (retries up to 3×)."""
    for attempt in range(3):
        if provider == "openai":
            raw = _call_openai(model_id, system, user, api_key=api_key)
        elif provider == "claude":
            raw = _call_claude(model_id, system, user, api_key=api_key)
        elif provider == "gemini":
            raw = _call_gemini(model_id, system, user, api_key=api_key)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        text = _strip_markdown_json(raw)
        try:
            json.loads(text)
            return text
        except Exception:
            user = f"The previous JSON was invalid. Fix it:\n{text}"

    raise RuntimeError("Failed to get valid JSON after 3 attempts")


def _strip_markdown_json(text: str) -> str:
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return m.group(1).strip() if m else text.strip()


def _call_openai(model_id: str, system: str, user: str, api_key: str | None = None) -> str:
    from openai import OpenAI
    from .config import OPENAI_API_KEY

    client = OpenAI(api_key=api_key or OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _call_claude(model_id: str, system: str, user: str, api_key: str | None = None) -> str:
    import anthropic
    from .config import ANTHROPIC_API_KEY

    client = anthropic.Anthropic(api_key=api_key or ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model_id,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


def _call_gemini(model_id: str, system: str, user: str, api_key: str | None = None) -> str:
    # Gemini supports OpenAI-compatible API — no extra SDK needed.
    from openai import OpenAI
    from .config import GEMINI_API_KEY

    client = OpenAI(
        api_key=api_key or GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # Gemini's OpenAI-compatible endpoint honors json_object; without it the
        # model tends to wrap output in prose/markdown, forcing wasted retries.
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content
