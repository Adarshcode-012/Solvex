import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from config import Settings


def _clean_settings(monkeypatch, **kwargs):
    for name in (
        "OPENAI_API_KEY", "APP_ENV", "APP_SECRET_KEY", "GUEST_SESSION_SECRET",
        "CORS_ORIGINS", "MEMORY_BACKEND", "REDIS_URL", "RATE_LIMIT_STORAGE_URI",
    ):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None, **kwargs)


def _run_settings_subprocess(**settings_env):
    backend_dir = Path(__file__).resolve().parents[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "OPENAI_API_KEY": "fake-key-for-tests-0123456789",
        "APP_SECRET_KEY": "test-secret",
        "APP_ENV": "production",
        "CORS_ORIGINS": "https://app.example.com",
        "MEMORY_BACKEND": "json",
        "REDIS_URL": "redis://:test-password@localhost:6379/0",
        "RATE_LIMIT_STORAGE_URI": "redis://:test-password@localhost:6379/1",
    }
    env.update(settings_env)
    return subprocess.run(
        [sys.executable, "-c", "from config import settings; print(settings.cors_origins_list)"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )


def test_mixed_wildcard_cors_rejected_in_production(monkeypatch):
    with pytest.raises(ValidationError):
        _clean_settings(
            monkeypatch,
            openai_api_key="fake-key-for-tests-0123456789",
            app_env="production",
            app_secret_key="test-secret",
            cors_origins="https://app.example.com,*",
            redis_url="redis://:test-password@localhost:6379/0",
            rate_limit_storage_uri="redis://:test-password@localhost:6379/1",
        )


def test_https_cors_origin_allowed_in_production(monkeypatch):
    settings = _clean_settings(
        monkeypatch,
        openai_api_key="fake-key-for-tests-0123456789",
        app_env="production",
        app_secret_key="test-secret",
        cors_origins="https://app.example.com",
        redis_url="redis://:test-password@localhost:6379/0",
        rate_limit_storage_uri="redis://:test-password@localhost:6379/1",
    )
    assert settings.cors_origins_list == ["https://app.example.com"]


def test_memory_backend_accepts_only_explicit_values(monkeypatch):
    with pytest.raises(ValidationError):
        _clean_settings(monkeypatch, openai_api_key="fake-key-for-tests-0123456789", memory_backend="sqlite")

    settings = _clean_settings(monkeypatch, openai_api_key="fake-key-for-tests-0123456789", memory_backend="json")
    assert settings.memory_backend == "json"


def test_production_env_rejects_wildcard_cors():
    result = _run_settings_subprocess(CORS_ORIGINS="https://app.example.com,*")
    assert result.returncode != 0
    assert "invalid CORS_ORIGINS" in result.stderr


def test_production_env_accepts_https_cors():
    result = _run_settings_subprocess(CORS_ORIGINS="https://app.example.com")
    assert result.returncode == 0, result.stderr
    assert "https://app.example.com" in result.stdout


def test_environment_rejects_bogus_memory_backend():
    result = _run_settings_subprocess(APP_ENV="development", MEMORY_BACKEND="bogus")
    assert result.returncode != 0
    assert "MEMORY_BACKEND must be 'chroma' or 'json'" in result.stderr


def test_production_env_rejects_empty_redis_url():
    result = _run_settings_subprocess(REDIS_URL="")
    assert result.returncode != 0
    assert "Production requires REDIS_URL" in result.stderr
