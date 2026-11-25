
from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field, field_validator, model_validator
from typing import Optional
import os
import shlex
import sys
from pathlib import Path
from urllib.parse import urlparse


DOTENV_PATH = Path(__file__).resolve().parent / ".env"
PROVIDER_KEY_NAMES = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
}


def provider_key_status(value: Optional[str]) -> str:
    if value is None or not value.strip():
        return "not configured"

    candidate = value.strip()
    if (candidate.startswith("<") and candidate.endswith(">")) or any(
        marker in candidate.casefold()
        for marker in ("placeholder", "your-key", "your_key", "changeme", "xxxx", "example")
    ):
        return "placeholder-ignored"
    return "configured"


def _has_configured_provider_key(value: Optional[str]) -> bool:
    return provider_key_status(value) == "configured"


def _worker_counts_from_args(arguments: list[str]) -> list[int]:
    counts = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        value = None
        if argument in {"--workers", "-w"} and index + 1 < len(arguments):
            index += 1
            value = arguments[index]
        elif argument.startswith("--workers="):
            value = argument.partition("=")[2]
        elif argument.startswith("-w") and argument[2:].isdigit():
            value = argument[2:]
        if value is not None:
            try:
                counts.append(int(value))
            except ValueError as exc:
                raise ValueError("Worker count must be an integer.") from exc
        index += 1
    return counts


def _configured_worker_count() -> int:
    counts = [1]
    web_concurrency = os.getenv("WEB_CONCURRENCY")
    if web_concurrency:
        try:
            counts.append(int(web_concurrency))
        except ValueError as exc:
            raise ValueError("WEB_CONCURRENCY must be an integer.") from exc
    counts.extend(_worker_counts_from_args(sys.argv[1:]))
    counts.extend(_worker_counts_from_args(shlex.split(os.getenv("GUNICORN_CMD_ARGS", ""))))
    return max(counts)


class Settings(BaseSettings):
    @field_validator(
        "claude_model",
        "gpt4o_model",
        "gpt4o_mini_model",
        "gemini_model",
        "gemini_flash_model",
        mode="before",
    )
    @classmethod
    def ensure_model_provider_prefix(cls, value: str, info):
        provider_by_field = {
            "claude_model": "anthropic",
            "gpt4o_model": "openai",
            "gpt4o_mini_model": "openai",
            "gemini_model": "gemini",
            "gemini_flash_model": "gemini",
        }
        model = str(value).strip()
        if not model:
            return cls.model_fields[info.field_name].default
        if "/" not in model:
            model = f"{provider_by_field[info.field_name]}/{model}"
        return model

    app_secret_key: Optional[str] = Field(None, validation_alias="APP_SECRET_KEY")
    guest_session_secret: Optional[str] = Field(None, validation_alias="GUEST_SESSION_SECRET")

    anthropic_api_key: Optional[str] = Field(None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key:    Optional[str] = Field(None, validation_alias="OPENAI_API_KEY")
    gemini_api_key:    Optional[str] = Field(None, validation_alias="GEMINI_API_KEY")

    claude_model: str = Field(
        "anthropic/claude-sonnet-5-5",
        validation_alias=AliasChoices("MODEL_CLAUDE", "CLAUDE_MODEL"),
    )
    gpt4o_model: str = Field(
        "openai/gpt-6.1-sol",
        validation_alias=AliasChoices("MODEL_GPT4O", "GPT4O_MODEL"),
    )
    gpt4o_mini_model: str = Field(
        "openai/gpt-6-luna",
        validation_alias=AliasChoices("MODEL_GPT4O_MINI", "GPT4O_MINI_MODEL"),
    )
    gemini_model: str = Field(
        "gemini/gemini-4-hydrogen",
        validation_alias=AliasChoices("MODEL_GEMINI", "GEMINI_MODEL"),
    )
    gemini_flash_model: str = Field(
        "gemini/gemini-4-hydrogen",
        validation_alias=AliasChoices("MODEL_GEMINI_FLASH", "GEMINI_FLASH_MODEL"),
    )

    solve_rate_limit: str = Field("5/minute", validation_alias="SOLVE_RATE_LIMIT")
    ip_solve_rate_limit: str = Field("10/minute", validation_alias="IP_SOLVE_RATE_LIMIT")
    ip_solve_daily_rate_limit: str = Field("100/day", validation_alias="IP_SOLVE_DAILY_RATE_LIMIT")
    guest_solve_rate_limit: str = Field("5/minute", validation_alias="GUEST_SOLVE_RATE_LIMIT")
    new_guests_per_ip_per_hour: int = Field(20, validation_alias="NEW_GUESTS_PER_IP_PER_HOUR")
    global_daily_solve_cap: int = Field(200, validation_alias="GLOBAL_DAILY_SOLVE_CAP")
    trusted_proxies: str = Field("", validation_alias="TRUSTED_PROXIES")
    rate_limit_storage_uri: str = Field("memory://", validation_alias="RATE_LIMIT_STORAGE_URI")
    redis_url: Optional[str] = Field(None, validation_alias="REDIS_URL")
    redis_allow_no_auth: bool = Field(False, validation_alias="REDIS_ALLOW_NO_AUTH")
    explain_cache_ttl_seconds: int = Field(604800, validation_alias="EXPLAIN_CACHE_TTL_SECONDS")
    admin_token: Optional[str] = Field(None, validation_alias="ADMIN_TOKEN")
    ai_request_timeout_seconds: int = Field(120, validation_alias="AI_REQUEST_TIMEOUT_SECONDS", gt=0)
    job_max_seconds: int = Field(900, validation_alias="JOB_MAX_SECONDS", gt=0)
    solvex_mock_ai: bool = Field(False, validation_alias="SOLVEX_MOCK_AI")
    ai_max_calls_per_solve: int = Field(12, validation_alias="AI_MAX_CALLS_PER_SOLVE", gt=0)
    ai_min_seconds_between_calls: float = Field(0, validation_alias="AI_MIN_SECONDS_BETWEEN_CALLS", ge=0)
    model_fast: Optional[str] = Field(None, validation_alias="MODEL_FAST")
    analyzer_max_tokens: int = Field(2048, validation_alias="ANALYZER_MAX_TOKENS", gt=0)
    strategist_max_tokens: int = Field(4096, validation_alias="STRATEGIST_MAX_TOKENS", gt=0)
    coder_max_tokens: int = Field(4096, validation_alias="CODER_MAX_TOKENS", gt=0)
    reviewer_max_tokens: int = Field(2048, validation_alias="REVIEWER_MAX_TOKENS", gt=0)

    judge0_api_key:  Optional[str] = Field(None, validation_alias="JUDGE0_API_KEY")
    judge0_base_url: str = Field(
        "https://judge0-ce.p.rapidapi.com",
        validation_alias="JUDGE0_BASE_URL"
    )
    judge0_poll_count: int = Field(12, validation_alias="JUDGE0_POLL_COUNT")
    judge0_poll_interval_seconds: float = Field(
        1.5,
        validation_alias="JUDGE0_POLL_INTERVAL_SECONDS",
    )

    chroma_db_path: str = Field("./memory/chroma_db", validation_alias="CHROMA_DB_PATH")
    memory_backend: str = Field("chroma", validation_alias="MEMORY_BACKEND")

    judge_max_iterations: int  = Field(5,     validation_alias="JUDGE_MAX_ITERATIONS")
    log_level:            str  = Field("INFO", validation_alias="LOG_LEVEL")
    cors_origins:         str  = Field("http://localhost:5173", validation_alias="CORS_ORIGINS")
    app_env:              str  = Field("development", validation_alias="APP_ENV")

    @model_validator(mode="after")
    def at_least_one_ai_key(self) -> "Settings":
        if self.app_env == "production" and self.solvex_mock_ai:
            raise ValueError("SOLVEX_MOCK_AI is forbidden in production")
        if self.app_env == "production" and not any(self.available_keys.values()):
            raise ValueError(
                "\n\n Production requires at least one valid AI API key.\n"
                "Set one of these in backend/.env or the process environment:\n"
                "  ANTHROPIC_API_KEY=sk-ant-...\n"
                "  OPENAI_API_KEY=sk-...\n"
                "  GEMINI_API_KEY=AIza...\n"
            )
        return self

    @model_validator(mode="after")
    def validate_memory_backend(self) -> "Settings":
        if self.memory_backend not in {"chroma", "json"}:
            raise ValueError("MEMORY_BACKEND must be 'chroma' or 'json'.")
        return self

    @model_validator(mode="after")
    def validate_process_storage(self) -> "Settings":
        if self.app_env == "production" and (
            not self.redis_url or self.rate_limit_storage_uri == "memory://"
        ):
            raise ValueError(
                "Production requires REDIS_URL and a non-memory RATE_LIMIT_STORAGE_URI."
            )
        if self.app_env == "production" and self.redis_url and not self.redis_allow_no_auth:
            try:
                has_password = bool(urlparse(self.redis_url).password)
            except ValueError as exc:
                raise ValueError("REDIS_URL is invalid.") from exc
            if not has_password:
                raise ValueError(
                    "Production REDIS_URL must include a password; "
                    "set REDIS_ALLOW_NO_AUTH=true only for an intentional no-auth deployment."
                )
        return self

    @model_validator(mode="after")
    def validate_admin_token(self) -> "Settings":
        if self.admin_token == "":
            self.admin_token = None
        elif self.admin_token is not None and len(self.admin_token) < 32:
            raise ValueError("ADMIN_TOKEN must be at least 32 characters when set.")
        return self

    @model_validator(mode="after")
    def validate_single_worker_with_local_chroma(self) -> "Settings":
        if self.app_env == "production" and self.memory_backend == "chroma":
            workers = _configured_worker_count()
            if workers > 1:
                raise ValueError(
                    "Production with MEMORY_BACKEND=chroma requires one worker; "
                    "set WEB_CONCURRENCY=1 and remove multi-worker arguments."
                )
        return self

    @property
    def available_keys(self) -> dict[str, bool]:
        return {
            "claude":     _has_configured_provider_key(self.anthropic_api_key),
            "gpt4o":      _has_configured_provider_key(self.openai_api_key),
            "gpt4o_mini": _has_configured_provider_key(self.openai_api_key),
            "gemini":     _has_configured_provider_key(self.gemini_api_key),
        }

    @property
    def provider_key_statuses(self) -> dict[str, str]:
        return {
            provider: provider_key_status(getattr(self, field_name))
            for provider, field_name in PROVIDER_KEY_NAMES.items()
        }

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @model_validator(mode="after")
    def warn_if_unprotected_in_prod(self) -> "Settings":
        if self.app_env == "production" and not (self.app_secret_key or self.guest_session_secret):
            raise ValueError(
                "\n\n APP_ENV=production but no guest session secret is set.\n"
                "Set GUEST_SESSION_SECRET or APP_SECRET_KEY to a long random string.\n"
                "in your .env before deploying, or the app will refuse to start.\n"
            )
        return self

    @model_validator(mode="after")
    def warn_if_wildcard_cors_in_prod(self) -> "Settings":
        origins = self.cors_origins_list
        if self.app_env == "production" and (
            not origins
            or any(
                origin == "*"
                or not origin
                or urlparse(origin).scheme != "https"
                or not urlparse(origin).netloc
                for origin in origins
            )
        ):
            raise ValueError(
                "\n\n APP_ENV=production has invalid CORS_ORIGINS.\n"
                "Use one or more https:// origins, comma-separated; wildcard is forbidden.\n"
                "  CORS_ORIGINS=https://your-frontend-domain.com\n"
                "in your .env before deploying, or the app will refuse to start.\n"
            )
        if self.app_env == "development":
            for origin in origins:
                parsed = urlparse(origin)
                if origin != "*" and (
                    parsed.scheme not in {"http", "https"} or not parsed.netloc
                ):
                    raise ValueError("Development CORS origins must be valid http(s) origins or '*'.")
        return self

    model_config = {
        "env_file": DOTENV_PATH,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }


settings = Settings()

for env_name, field_name in (
    ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    ("OPENAI_API_KEY", "openai_api_key"),
    ("GEMINI_API_KEY", "gemini_api_key"),
):
    value = getattr(settings, field_name)
    if _has_configured_provider_key(value):
        os.environ[env_name] = value
    else:
        os.environ.pop(env_name, None)
