"""
Shared LLM access with optional providers.

Provider order: Groq (if GROQ_API_KEY is set) -> OpenAI (if OPENAI_API_KEY is set).
If the first provider is configured but a request fails (rate limit, outage),
the next configured provider is tried before giving up.

Groq exposes an OpenAI-compatible API, so the `openai` package is used for both.

Optional .env overrides:
    GROQ_MODEL     (default: openai/gpt-oss-120b)
    OPENAI_MODEL   (default: gpt-4o-mini)
    LLM_PROVIDER   groq | openai   -> force the preferred provider
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Groq retires models over time (llama-3.3-70b-versatile now returns 404 for this account).
# List what your key can use: GET https://api.groq.com/openai/v1/models
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _configured_providers():
    """Return [(name, client, model)] for every provider that has an API key, preferred first."""
    providers = []

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        providers.append((
            "groq",
            OpenAI(api_key=groq_key, base_url=GROQ_BASE_URL),
            os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
        ))

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        providers.append((
            "openai",
            OpenAI(api_key=openai_key),
            os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        ))

    preferred = os.getenv("LLM_PROVIDER", "").strip().lower()
    providers.sort(key=lambda p: p[0] != preferred)  # stable: preferred first, rest keep Groq -> OpenAI order
    return providers


def active_provider():
    """Name of the provider that will be tried first ('groq', 'openai') or None."""
    providers = _configured_providers()
    return providers[0][0] if providers else None


def chat(messages, temperature: float = 0, json_mode: bool = False):
    """
    Run a chat completion and return the response text.
    Raises RuntimeError if no provider is configured, or the last provider's
    exception if every configured provider fails.
    """
    providers = _configured_providers()
    if not providers:
        raise RuntimeError("No LLM API key found. Set GROQ_API_KEY or OPENAI_API_KEY in your .env file.")

    kwargs = {"temperature": temperature}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_error = None
    for name, client, model in providers:
        try:
            response = client.chat.completions.create(model=model, messages=messages, **kwargs)
            return response.choices[0].message.content.strip()
        except Exception as exc:
            print(f"⚠️ {name} request failed: {exc}")
            last_error = exc

    raise last_error
