import pytest


@pytest.fixture(autouse=True)
def synthetic_provider_keys(monkeypatch):
    from config import PROVIDER_KEY_NAMES, settings

    for provider, field in PROVIDER_KEY_NAMES.items():
        value = "fake-key-for-tests-0123456789" if provider == "gemini" else ""
        monkeypatch.setenv(field.upper(), value)
        monkeypatch.setattr(settings, field, value)
