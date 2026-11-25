import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("worker_env", "arguments"),
    [
        ({"WEB_CONCURRENCY": "2"}, []),
        ({}, ["--workers", "2"]),
        ({"GUNICORN_CMD_ARGS": "-w 2"}, []),
    ],
)
def test_production_chroma_rejects_multiple_workers(worker_env, arguments):
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
        "MEMORY_BACKEND": "chroma",
        "REDIS_URL": "redis://:test-password@localhost:6379/0",
        "RATE_LIMIT_STORAGE_URI": "redis://:test-password@localhost:6379/1",
    }
    env.update(worker_env)
    result = subprocess.run(
        [sys.executable, "-c", "from config import settings", *arguments],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "requires one worker" in result.stderr
