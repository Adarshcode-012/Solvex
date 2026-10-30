"""
utils/ai_router.py

Routes each agent's request to the right underlying AI provider (Claude,
GPT-4o, or Gemini), with manual overrides, automatic fallback when a
provider is unavailable, per-provider usage tracking, and retry with
exponential backoff on transient errors. call_ai() is async (backed by
litellm.acompletion) so concurrent solve requests don't block on each
other's network calls.
"""

import os
import json
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import litellm
from litellm import acompletion
from litellm.exceptions import (
    RateLimitError,
    AuthenticationError,
    ServiceUnavailableError,
    APIConnectionError,
)

from config import settings
from logger import log

# ── Silence LiteLLM's own verbose logging ─────────────────────────────────────
litellm.set_verbose = False

# ── Model strings ─────────────────────────────────────────────────────────────
# Sourced from config/env (CLAUDE_MODEL, GPT4O_MODEL, ...) so a provider
# deprecating a version doesn't require a code change + redeploy.
MODELS: dict[str, str] = {
    "claude":       settings.claude_model,
    "gpt4o":        settings.gpt4o_model,
    "gpt4o_mini":   settings.gpt4o_mini_model,
    "gemini":       settings.gemini_model,
    "gemini_flash": settings.gemini_flash_model,
}

# Best AI per agent role (when all keys available)
ROLE_BEST_AI: dict[str, str] = {
    "analyzer":   "gemini",      # Best at reading/parsing long text + images
    "strategist": "claude",      # Best at deep constraint-driven reasoning
    "coder":      "gpt4o",       # Best at code generation
    "reviewer":   "claude",      # Best at critical bug detection
    "judge":      "gpt4o_mini",  # Fast + cheap for error classification
}

# Fallback order when best AI unavailable — FIX: gpt4o_mini included
FALLBACK_ORDER = ["claude", "gpt4o", "gpt4o_mini", "gemini"]

FREE_TIER_LIMITS: dict[str, dict] = {
    "claude":     {"calls": 1000,  "label": "Claude Sonnet"},
    "gpt4o":      {"calls": 500,   "label": "GPT-4o"},
    "gpt4o_mini": {"calls": 10000, "label": "GPT-4o-mini"},
    "gemini":     {"calls": 1500,  "label": "Gemini 1.5 Pro"},
}

# ── Usage stats (persisted to disk) ───────────────────────────────────────────
_USAGE_FILE = os.path.join(os.path.dirname(__file__), "..", "memory", "data", "usage_stats.json")

def _load_usage() -> dict:
    os.makedirs(os.path.dirname(_USAGE_FILE), exist_ok=True)
    if os.path.exists(_USAGE_FILE):
        with open(_USAGE_FILE) as f:
            return json.load(f)
    return {k: {"calls": 0, "tokens_in": 0, "tokens_out": 0} for k in FREE_TIER_LIMITS}

def _save_usage(stats: dict) -> None:
    with open(_USAGE_FILE, "w") as f:
        json.dump(stats, f, indent=2)

_usage_stats = _load_usage()


def get_agent_model(
    role: str,
    manual_overrides: Optional[dict] = None
) -> tuple[str, str]:
    """Returns (ai_key, model_string) for a given agent role."""
    available = settings.available_keys

    # 1. Manual override from user
    if manual_overrides and role in manual_overrides:
        chosen = manual_overrides[role]
        if chosen in MODELS and available.get(chosen):
            return chosen, MODELS[chosen]
        log.warning("manual_override_unavailable", role=role, chosen=chosen)

    # 2. Best AI for this role
    best = ROLE_BEST_AI.get(role, "claude")
    if available.get(best):
        return best, MODELS[best]

    # 3. Fallback chain
    for ai in FALLBACK_ORDER:
        if available.get(ai):
            log.info("ai_fallback", role=role, best=best, using=ai)
            return ai, MODELS[ai]

    raise ValueError(
        "No AI API keys configured. Add at least one to .env: "
        "ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY"
    )


def _build_vision_message(content_text: str, image_base64: str, ai_key: str) -> dict:
    """
    Builds the correct vision message format per provider.
    Gemini and OpenAI/Anthropic use different image_url structures via LiteLLM.
    """
    image_url = f"data:image/png;base64,{image_base64}"

    # All providers use the same LiteLLM image_url format
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": content_text},
        ]
    }


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
) -> tuple[str, str]:
    """
    Routes an AI call through LiteLLM with retry, usage tracking, and error handling.
    Async — uses litellm.acompletion so it doesn't block the event loop while
    waiting on the network, which matters the moment more than one request
    is in flight at once.

    Returns: (response_text, ai_key_used)
    Raises:  RateLimitHit | AIProviderError | ValueError
    """
    ai_key, model = get_agent_model(role, manual_overrides)

    # Inject image into last user message if provided
    if image_base64:
        last_idx = len(messages) - 1
        last = messages[last_idx]
        if isinstance(last.get("content"), str):
            messages[last_idx] = _build_vision_message(last["content"], image_base64, ai_key)

    log.info("ai_call", role=role, ai=ai_key, model=model)

    try:
        response = await acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # Track usage and persist
        usage = response.usage
        if usage and ai_key in _usage_stats:
            _usage_stats[ai_key]["calls"]      += 1
            _usage_stats[ai_key]["tokens_in"]  += getattr(usage, "prompt_tokens", 0)
            _usage_stats[ai_key]["tokens_out"] += getattr(usage, "completion_tokens", 0)
            _save_usage(_usage_stats)

        content = response.choices[0].message.content
        log.info("ai_response", role=role, ai=ai_key, chars=len(content or ""))
        return content, ai_key

    except RateLimitError as e:
        label = FREE_TIER_LIMITS.get(ai_key, {}).get("label", ai_key)
        log.warning("rate_limit_hit", ai=ai_key)
        raise RateLimitHit(ai_key=ai_key, ai_label=label, original_error=str(e))

    except AuthenticationError as e:
        log.error("ai_auth_error", role=role, ai=ai_key, error=str(e))
        raise AIProviderError(
            f"Invalid or expired API key for {ai_key}. Check your .env file."
        ) from e


def get_usage_stats() -> dict:
    """Returns per-AI usage for the frontend progress bars."""
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


def get_ai_config_summary() -> dict:
    """Returns AI assignment per agent for the frontend config panel."""
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


def reset_usage_stats() -> None:
    """Resets all usage counters. Called from admin endpoint."""
    global _usage_stats
    _usage_stats = {k: {"calls": 0, "tokens_in": 0, "tokens_out": 0} for k in FREE_TIER_LIMITS}
    _save_usage(_usage_stats)
    log.info("usage_stats_reset")


class RateLimitHit(Exception):
    """A provider's rate limit was hit. Recoverable — user can switch AI or wait."""
    def __init__(self, ai_key: str, ai_label: str, original_error: str):
        self.ai_key         = ai_key
        self.ai_label       = ai_label
        self.original_error = original_error
        super().__init__(
            f"{ai_label} rate limit reached. Switch AI or wait for reset."
        )


class AIProviderError(Exception):
    """
    An AI provider call failed in a way that isn't recoverable by retrying
    (bad/expired key, malformed request, etc). Distinct from RateLimitHit
    (which is transient) so callers can tell the two apart.
    """
    pass
