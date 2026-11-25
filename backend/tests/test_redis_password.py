import os
from pathlib import Path
import subprocess
import sys


def _run_settings(redis_url, allow_no_auth=None):
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
        "REDIS_URL": redis_url,
        "RATE_LIMIT_STORAGE_URI": "redis://redis:6379/1",
    }
    if allow_no_auth is not None:
        env["REDIS_ALLOW_NO_AUTH"] = allow_no_auth
    return subprocess.run(
        [sys.executable, "-c", "from config import settings; print(settings.redis_url)"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )


def test_production_redis_url_requires_password_unless_explicitly_allowed():
    rejected = _run_settings("redis://redis:6379/0")
    assert rejected.returncode != 0
    assert "must include a password" in rejected.stderr

    allowed = _run_settings("redis://redis:6379/0", "true")
    assert allowed.returncode == 0, allowed.stderr
