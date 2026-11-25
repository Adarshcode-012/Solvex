import json
from pathlib import Path

from config import Settings


def test_smoke_configuration_passes_production_startup_validation():
    root = Path(__file__).resolve().parents[2]
    override = json.loads((root / ".github/compose-smoke.override.json").read_text(encoding="utf-8"))
    values = override["services"]["api"]["environment"]

    settings = Settings(
        _env_file=None,
        **values,
        ANTHROPIC_API_KEY="",
        GEMINI_API_KEY="",
        REDIS_URL="redis://:ci-fixture@redis:6379/0",
        RATE_LIMIT_STORAGE_URI="redis://:ci-fixture@redis:6379/1",
    )

    assert settings.app_env == "production"
    assert settings.available_keys["gpt4o"]
