from config import Settings, provider_key_status
from pydantic import ValidationError


def test_provider_placeholder_keys_are_ignored_and_realistic_fake_is_configured():
    placeholders = [
        "test-placeholder",
        "YOUR-KEY-here",
        "your_key_value",
        "PleaseChangeMe",
        "abcXXXXdef",
        "example-secret",
        "<secret>",
    ]
    for value in placeholders:
        settings = Settings(_env_file=None, openai_api_key=value)
        assert provider_key_status(value) == "placeholder-ignored"
        assert settings.available_keys["gpt4o"] is False
        assert settings.available_keys["gpt4o_mini"] is False

    for value in (None, "", "   "):
        settings = Settings(_env_file=None, gemini_api_key=value)
        assert provider_key_status(value) == "not configured"
        assert settings.available_keys["gemini"] is False

    realistic_fake = "fake-key-for-tests-0123456789"
    settings = Settings(_env_file=None, gemini_api_key=realistic_fake)
    assert provider_key_status(realistic_fake) == "configured"
    assert settings.available_keys["gemini"] is True


def test_production_rejects_placeholder_only_provider_keys(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    try:
        Settings(
            _env_file=None,
            app_env="production",
            anthropic_api_key=None,
            openai_api_key="test-placeholder",
            gemini_api_key=None,
        )
    except ValidationError as exc:
        assert "Production requires at least one valid AI API key" in str(exc)
    else:
        raise AssertionError("Production must reject placeholder-only keys")
