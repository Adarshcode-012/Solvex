
import os
from pathlib import Path
import re
import sys
import time

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

ROLE_KEY_ATTRIBUTE = {
    "claude": "anthropic_api_key",
    "gpt4o": "openai_api_key",
    "gpt4o_mini": "openai_api_key",
    "gemini": "gemini_api_key",
    "gemini_flash": "gemini_api_key",
}


def _secrets_to_redact(settings_obj) -> list[str]:
    values = [
        getattr(settings_obj, name, None)
        for name in ("anthropic_api_key", "openai_api_key", "gemini_api_key")
    ]
    values.extend(
        value for name, value in os.environ.items()
        if "API_KEY" in name.upper() and value
    )
    return sorted({value for value in values if value}, key=len, reverse=True)


def _safe_error(error: Exception, secrets: list[str]) -> str:
    message = f"{type(error).__name__}: {error}"
    for secret in secrets:
        message = message.replace(secret, "[REDACTED]")
    message = re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer)(\s*[:=]\s*|\s+)[^\s,;]+",
        r"\1\2[REDACTED]",
        message,
    )
    message = re.sub(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{8,}\b", "[REDACTED]", message)
    message = re.sub(r"\bAIza[A-Za-z0-9_-]{20,}\b", "[REDACTED]", message)
    return message


def _is_service_unavailable(error: Exception) -> bool:
    response = getattr(error, "response", None)
    status = (
        getattr(error, "status_code", None)
        or getattr(error, "status", None)
        or getattr(error, "code", None)
        or getattr(response, "status_code", None)
    )
    return str(status) == "503"


def main(settings_obj=None, models=None, completion_fn=None, sleep_fn=time.sleep) -> int:
    if settings_obj is None:
        load_dotenv(BACKEND_DIR / ".env")
        from config import settings as settings_obj
    if models is None:
        from utils.ai_router import MODELS as models
    if completion_fn is None:
        from litellm import completion as completion_fn

    secrets = _secrets_to_redact(settings_obj)
    failed = False
    for role, model in models.items():
        key_attribute = ROLE_KEY_ATTRIBUTE.get(role)
        if key_attribute is None or not getattr(settings_obj, key_attribute, None):
            print(f"SKIPPED {role} (no key)")
            continue
        try:
            for attempt in range(2):
                try:
                    completion_fn(
                        model=model,
                        messages=[{"role": "user", "content": "Reply OK."}],
                        max_tokens=5,
                    )
                except Exception as error:
                    if attempt == 0 and _is_service_unavailable(error):
                        sleep_fn(10)
                        continue
                    raise
                break
        except Exception as error:
            print(f"ERROR {role} ({model}): {_safe_error(error, secrets)}")
            failed = True
        else:
            print(f"OK {role} ({model})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
