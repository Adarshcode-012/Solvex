import pytest
from pydantic import ValidationError

from config import Settings


def test_mixed_wildcard_cors_rejected_in_production():
    with pytest.raises(ValidationError):
        Settings(
            openai_api_key="test-placeholder",
            app_env="production",
            app_secret_key="test-secret",
            cors_origins="trusted.example,*",
        )


def test_https_cors_origin_allowed_in_production():
    settings = Settings(
        openai_api_key="test-placeholder",
        app_env="production",
        app_secret_key="test-secret",
        cors_origins="https://app.example.com",
        redis_url="redis://localhost:6379/0",
        rate_limit_storage_uri="redis://localhost:6379/1",
    )
    assert settings.cors_origins_list == ["https://app.example.com"]


def test_memory_backend_accepts_only_explicit_values():
    with pytest.raises(ValidationError):
        Settings(openai_api_key="test-placeholder", memory_backend="sqlite")

    settings = Settings(openai_api_key="test-placeholder", memory_backend="json")
    assert settings.memory_backend == "json"