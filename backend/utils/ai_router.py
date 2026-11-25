
import os
import json
import asyncio
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional, Callable
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import litellm
import redis
from litellm import acompletion
from litellm.exceptions import (
    RateLimitError,
    AuthenticationError,
    Timeout as LiteLLMTimeout,
    ServiceUnavailableError,
    APIConnectionError,
)

from config import settings
from logger import log

litellm.set_verbose = False

MODELS: dict[str, str] = {
    "claude":       settings.claude_model,
    "gpt4o":        settings.gpt4o_model,
    "gpt4o_mini":   settings.gpt4o_mini_model,
    "gemini":       settings.gemini_model,
    "gemini_flash": settings.gemini_flash_model,
}

ROLE_BEST_AI: dict[str, str] = {
    "analyzer":   "gemini",
    "strategist": "claude",
    "coder":      "gpt4o",
    "reviewer":   "claude",
    "judge":      "gpt4o_mini",
}

FALLBACK_ORDER = ["claude", "gpt4o", "gpt4o_mini", "gemini"]
_fallback_logged: ContextVar[bool] = ContextVar("ai_fallback_logged", default=False)
_solve_ai_calls: ContextVar[Optional[int]] = ContextVar("solve_ai_calls", default=None)
_solve_timings: ContextVar[Optional[list[dict]]] = ContextVar("solve_timings", default=None)
_progress_callback: ContextVar[Optional[Callable[[dict], None]]] = ContextVar("progress_callback", default=None)


@contextmanager
def ai_request_scope():
    token = _fallback_logged.set(False)
    calls_token = _solve_ai_calls.set(0)
    timings_token = _solve_timings.set([])
    try:
        yield _solve_timings.get()
    finally:
        _solve_timings.reset(timings_token)
        _solve_ai_calls.reset(calls_token)
        _fallback_logged.reset(token)


@contextmanager
def ai_progress_scope(callback: Callable[[dict], None]):
    token = _progress_callback.set(callback)
    try:
        yield
    finally:
        _progress_callback.reset(token)


def publish_progress(role: str, status: str) -> None:
    callback = _progress_callback.get()
    if callback is not None:
        callback({"agent": role, "status": status})


def _rate_limit_type(message: str) -> str | None:
    lowered = message.casefold()
    if any(term in lowered for term in ("daily", "requests/day", "tokens/day")) or re.search(r"per[\s_-]*day", lowered):
        return "daily"
    if any(term in lowered for term in ("requests/minute", "tokens/minute", "rpm", "tpm")) or re.search(r"per[\s_-]*minute", lowered):
        return "per-minute"
    return None

FREE_TIER_LIMITS: dict[str, dict] = {
    "claude":     {"calls": 1000,  "label": "Claude Sonnet"},
    "gpt4o":      {"calls": 500,   "label": "GPT-4o"},
    "gpt4o_mini": {"calls": 10000, "label": "GPT-4o-mini"},
    "gemini":     {"calls": 1500,  "label": "Gemini"},
}

_USAGE_FILE = os.path.join(os.path.dirname(__file__), "..", "memory", "data", "usage_stats.json")
_USAGE_REDIS_KEY = "solvex:usage"


def _redis_usage_client():
    if not settings.redis_url:
        return None
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)

def _load_usage() -> dict:
    client = _redis_usage_client()
    if client is not None:
        values = client.hgetall(_USAGE_REDIS_KEY)
        if values:
            return {
                key: {
                    "calls": int(values.get(f"{key}:calls", 0)),
                    "tokens_in": int(values.get(f"{key}:tokens_in", 0)),
                    "tokens_out": int(values.get(f"{key}:tokens_out", 0)),
                }
                for key in FREE_TIER_LIMITS
            }
    os.makedirs(os.path.dirname(_USAGE_FILE), exist_ok=True)
    if os.path.exists(_USAGE_FILE):
        with open(_USAGE_FILE) as f:
            return json.load(f)
    return {k: {"calls": 0, "tokens_in": 0, "tokens_out": 0} for k in FREE_TIER_LIMITS}

def _save_usage(stats: dict) -> None:
    client = _redis_usage_client()
    if client is not None:
        mapping = {
            f"{key}:{field}": value
            for key, values in stats.items()
            for field, value in values.items()
        }
        client.hset(_USAGE_REDIS_KEY, mapping=mapping)
        return
    with open(_USAGE_FILE, "w") as f:
        json.dump(stats, f, indent=2)

_usage_stats = _load_usage()


def get_agent_model(
    role: str,
    manual_overrides: Optional[dict] = None
) -> tuple[str, str]:
    available = settings.available_keys

    if manual_overrides and role in manual_overrides:
        chosen = manual_overrides[role]
        if chosen in MODELS and available.get(chosen):
            return chosen, MODELS[chosen]
        log.warning("manual_override_unavailable", role=role, chosen=chosen)

    best = ROLE_BEST_AI.get(role, "claude")
    if available.get(best):
        return best, MODELS[best]

    for ai in FALLBACK_ORDER:
        if available.get(ai):
            if not _fallback_logged.get():
                log.warning("ai_fallback", role=role, best=best, using=ai)
                _fallback_logged.set(True)
            return ai, MODELS[ai]

    raise ValueError(
        "No AI API keys configured. Add at least one to .env: "
        "ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY"
    )


def _build_vision_message(content_text: str, image_base64: str, ai_key: str, image_mime_type: str) -> dict:
    image_url = f"data:{image_mime_type};base64,{image_base64}"

    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": content_text},
        ]
    }


def provider_auth_error_message(ai_key: str) -> str:
    provider_name = {
        "claude": "Anthropic",
        "gpt4o": "OpenAI",
        "gpt4o_mini": "OpenAI",
        "gemini": "Gemini",
    }.get(ai_key, "AI provider")
    return (
        f"{provider_name} rejected the API key. "
        f"Check the key for {provider_name} and restart the backend."
    )


@retry(
    retry=retry_if_exception_type((ServiceUnavailableError, APIConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def call_ai(
    role: str,
    messages: list[dict],
    manual_overrides: Optional[dict] = None,
    max_tokens: int = 4096,
    temperature: float = 0.1,
    image_base64: Optional[str] = None,
    image_mime_type: str = "image/png",
) -> tuple[str, str]:
    if settings.solvex_mock_ai:
        if settings.app_env == 'production':
            raise ValueError('SOLVEX_MOCK_AI is forbidden in production')
        from utils.mock_ai import completion
        return await completion(role)
    ai_key, model = get_agent_model(role, manual_overrides)
    if role in {"analyzer", "reviewer"} and settings.model_fast:
        fast_model = settings.model_fast.strip()
        expected_provider = {"claude": "anthropic", "gpt4o": "openai", "gpt4o_mini": "openai", "gemini": "gemini"}.get(ai_key)
        fast_provider, separator, _ = fast_model.partition("/")
        if not separator and expected_provider:
            fast_model = f"{expected_provider}/{fast_model}"
            fast_provider = expected_provider
        if fast_provider == expected_provider:
            model = fast_model

    if image_base64:
        last_idx = len(messages) - 1
        last = messages[last_idx]
        if isinstance(last.get("content"), str):
            messages[last_idx] = _build_vision_message(last["content"], image_base64, ai_key, image_mime_type)

    log.info("ai_call", role=role, ai=ai_key, model=model)

    call_count = _solve_ai_calls.get()
    if call_count is not None:
        if call_count >= settings.ai_max_calls_per_solve:
            raise AIProviderError("AI call limit for this solve was reached.", code="ai_call_limit")
        _solve_ai_calls.set(call_count + 1)
    if call_count is not None and call_count > 0 and settings.ai_min_seconds_between_calls:
        await asyncio.sleep(settings.ai_min_seconds_between_calls)

    request_started = time.perf_counter()
    prompt_tokens = 0
    completion_tokens = 0
    call_succeeded = False
    publish_progress(role, "started")
    try:
        response = await acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=settings.ai_request_timeout_seconds,
        )

        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        if usage and ai_key in _usage_stats:
            _usage_stats[ai_key]["calls"]      += 1
            _usage_stats[ai_key]["tokens_in"]  += getattr(usage, "prompt_tokens", 0)
            _usage_stats[ai_key]["tokens_out"] += getattr(usage, "completion_tokens", 0)
            _save_usage(_usage_stats)

        content = response.choices[0].message.content
        call_succeeded = True
        log.info("ai_response", role=role, ai=ai_key, chars=len(content or ""))
        return content, ai_key

    except RateLimitError as e:
        provider = {"claude": "Anthropic", "gpt4o": "OpenAI", "gpt4o_mini": "OpenAI", "gemini": "Gemini"}.get(ai_key, ai_key)
        quota_type = _rate_limit_type(str(e))
        label = f"{provider} ({model})"
        log.warning("provider_quota_exceeded", provider=provider, model=model, role=role,
                    retry_after_present=_retry_after_seconds(e) is not None)
        raise RateLimitHit(
            ai_key=ai_key,
            ai_label=label,
            original_error=str(e),
            retry_after_seconds=_retry_after_seconds(e),
            quota_type=quota_type,
        )

    except LiteLLMTimeout as e:
        provider_name = {
            "claude": "Anthropic",
            "gpt4o": "OpenAI",
            "gpt4o_mini": "OpenAI",
            "gemini": "Gemini",
        }.get(ai_key, "AI provider")
        timeout = settings.ai_request_timeout_seconds
        log.warning("ai_provider_timeout", role=role, ai=ai_key, timeout_seconds=timeout)
        raise AIProviderError(
            f"{provider_name} request timed out after {timeout} seconds. "
            "Check backend connectivity and try again.",
            code="ai_provider_timeout",
        ) from e
    except AuthenticationError as e:
        log.error("ai_auth_error", role=role, ai=ai_key)
        raise AIProviderError(
            provider_auth_error_message(ai_key),
            code="ai_auth_failed",
        ) from e
    finally:
        seconds = round(time.perf_counter() - request_started, 3)
        log.info("ai_call_timing", role=role, provider=ai_key, model=model, seconds=seconds,
                 prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        timings = _solve_timings.get()
        if timings is not None:
            timings.append({"role": role, "seconds": seconds})
        publish_progress(role, "done" if call_succeeded else "failed")


def get_usage_stats() -> dict:
    available = settings.available_keys
    result = {}
    for ai_key, limits in FREE_TIER_LIMITS.items():
        calls   = _usage_stats.get(ai_key, {}).get("calls", 0)
        limit   = limits["calls"]
        percent = round((calls / limit) * 100, 1) if limit > 0 else 0
        result[ai_key] = {
            "label":     limits["label"],
            "calls":     calls,
            "tokens_in":  _usage_stats.get(ai_key, {}).get("tokens_in", 0),
            "tokens_out": _usage_stats.get(ai_key, {}).get("tokens_out", 0),
            "limit":     limit,
            "percent":   min(percent, 100.0),
            "available": available.get(ai_key, False),
            "warning":   90 <= percent < 100,
            "exhausted": percent >= 100,
        }
    return result


def _retry_after_seconds(error: Exception) -> Optional[int]:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        seconds = int(headers.get("retry-after", ""))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _get_ai_config_summary() -> dict:
    available  = settings.available_keys
    key_count  = sum(1 for v in available.values() if v)
    assignment = {}
    for role in ["analyzer", "strategist", "coder", "reviewer", "judge"]:
        try:
            ai_key, model = get_agent_model(role)
            assignment[role] = {
                "ai":    ai_key,
                "model": model,
                "label": FREE_TIER_LIMITS.get(ai_key, {}).get("label", ai_key),
            }
        except ValueError:
            assignment[role] = {"ai": "none", "model": "none", "label": "No key"}
    return {
        "keys_configured": key_count,
        "available":       available,
        "auto_assignment": assignment,
        "mode":            "auto" if key_count > 0 else "unconfigured",
    }


def get_ai_config_summary() -> dict:
    with ai_request_scope():
        return _get_ai_config_summary()


def reset_usage_stats() -> None:
    global _usage_stats
    _usage_stats = {k: {"calls": 0, "tokens_in": 0, "tokens_out": 0} for k in FREE_TIER_LIMITS}
    client = _redis_usage_client()
    if client is not None:
        client.delete(_USAGE_REDIS_KEY)
    _save_usage(_usage_stats)
    log.info("usage_stats_reset")


class RateLimitHit(Exception):
    def __init__(
        self,
        ai_key: str,
        ai_label: str,
        original_error: str,
        retry_after_seconds: Optional[int] = None,
        quota_type: Optional[str] = None,
    ):
        self.ai_key         = ai_key
        self.ai_label       = ai_label
        self.original_error = original_error
        self.retry_after_seconds = retry_after_seconds
        self.quota_type = quota_type
        if quota_type:
            message = f"{ai_label} rate limit reached ({quota_type} quota)."
        else:
            provider = ai_label.split(" (", 1)[0]
            message = f"{provider} quota exceeded (limit type not reported)."
        super().__init__(
            f"{message} A replacement key may still share the same quota. "
            "Switch providers or wait for the provider reset."
        )


class AIProviderError(Exception):
    def __init__(self, message: str, code: str = "ai_provider_failed"):
        self.code = code
        super().__init__(message)
