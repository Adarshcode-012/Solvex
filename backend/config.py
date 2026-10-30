"""
config.py

Single source of truth for all configuration. Uses pydantic-settings to
load and validate environment variables at startup, and fails fast with a
clear error message if required config is missing or unsafe for the
configured environment (e.g. deploying to production without an API secret
or with a wildcard CORS policy).
"""

from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from typing import Optional
import os


class Settings(BaseSettings):
    # ── App auth (protects mutating / expensive endpoints) ─────────────────────
    app_secret_key: Optional[str] = Field(None, validation_alias="APP_SECRET_KEY")

    # ── AI API Keys (all optional — at least one required) ─────────────────────
    anthropic_api_key: Optional[str] = Field(None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key:    Optional[str] = Field(None, validation_alias="OPENAI_API_KEY")
    gemini_api_key:    Optional[str] = Field(None, validation_alias="GEMINI_API_KEY")

    # ── Model versions (env-overridable so a provider deprecation doesn't need a redeploy) ─
    claude_model:       str = Field("claude-sonnet-4-20250514", validation_alias="CLAUDE_MODEL")
    gpt4o_model:        str = Field("gpt-4o",                  validation_alias="GPT4O_MODEL")
    gpt4o_mini_model:   str = Field("gpt-4o-mini",              validation_alias="GPT4O_MINI_MODEL")
    gemini_model:       str = Field("gemini/gemini-1.5-pro",    validation_alias="GEMINI_MODEL")
    gemini_flash_model: str = Field("gemini/gemini-1.5-flash",  validation_alias="GEMINI_FLASH_MODEL")

    # ── Rate limiting (protects paid AI calls from abuse) ───────────────────────
    solve_rate_limit: str = Field("5/minute", validation_alias="SOLVE_RATE_LIMIT")

    # ── Judge0 ─────────────────────────────────────────────────────────────────
    judge0_api_key:  Optional[str] = Field(None, validation_alias="JUDGE0_API_KEY")
    judge0_base_url: str = Field(
        "https://judge0-ce.p.rapidapi.com",
        validation_alias="JUDGE0_BASE_URL"
    )

    # ── Memory ─────────────────────────────────────────────────────────────────
    chroma_db_path: str = Field("./memory/chroma_db", validation_alias="CHROMA_DB_PATH")

    # ── App ────────────────────────────────────────────────────────────────────
    judge_max_iterations: int  = Field(5,     validation_alias="JUDGE_MAX_ITERATIONS")
    log_level:            str  = Field("INFO", validation_alias="LOG_LEVEL")
    cors_origins:         str  = Field("*",    validation_alias="CORS_ORIGINS")
    app_env:              str  = Field("development", validation_alias="APP_ENV")

    @model_validator(mode="after")
    def at_least_one_ai_key(self) -> "Settings":
        """Fail at startup if no AI key is configured."""
        has_key = any([
            self.anthropic_api_key,
            self.openai_api_key,
            self.gemini_api_key,
        ])
        if not has_key:
            raise ValueError(
                "\n\n❌ SolveX requires at least one AI API key.\n"
                "Add one of these to your .env file:\n"
                "  ANTHROPIC_API_KEY=sk-ant-...\n"
                "  OPENAI_API_KEY=sk-...\n"
                "  GEMINI_API_KEY=AIza...\n"
            )
        return self

    @property
    def available_keys(self) -> dict[str, bool]:
        return {
            "claude":     bool(self.anthropic_api_key),
            "gpt4o":      bool(self.openai_api_key),
            "gpt4o_mini": bool(self.openai_api_key),
            "gemini":     bool(self.gemini_api_key),
        }

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @model_validator(mode="after")
    def warn_if_unprotected_in_prod(self) -> "Settings":
        """Fail fast if deploying to production with no API key gate — avoids
        accidentally exposing paid AI endpoints to the whole internet."""
        if self.app_env == "production" and not self.app_secret_key:
            raise ValueError(
                "\n\n❌ APP_ENV=production but APP_SECRET_KEY is not set.\n"
                "Every /solve call spends real money on AI providers — set:\n"
                "  APP_SECRET_KEY=<a long random string>\n"
                "in your .env before deploying, or the app will refuse to start.\n"
            )
        return self

    @model_validator(mode="after")
    def warn_if_wildcard_cors_in_prod(self) -> "Settings":
        """Fail fast if deploying to production with CORS still wide open —
        the same reasoning as the secret-key guard above: this is the kind
        of thing that's trivial to forget when copying .env.example → .env."""
        if self.app_env == "production" and self.cors_origins.strip() == "*":
            raise ValueError(
                "\n\n❌ APP_ENV=production but CORS_ORIGINS is still \"*\".\n"
                "Set it to your real frontend domain(s), comma-separated, e.g.:\n"
                "  CORS_ORIGINS=https://your-frontend-domain.com\n"
                "in your .env before deploying, or the app will refuse to start.\n"
            )
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }


# Singleton — import this everywhere
settings = Settings()

# Push keys into env for LiteLLM (it reads from os.environ)
if settings.anthropic_api_key:
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
if settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
