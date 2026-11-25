from types import SimpleNamespace

from scripts.check_models import main


def test_checker_redacts_a_fake_provider_key_and_skips_roles_without_keys(capsys):
    fake_key = "provider-secret-token-abcdef1234"
    settings = SimpleNamespace(
        anthropic_api_key=None,
        openai_api_key=fake_key,
        gemini_api_key=None,
    )

    def completion(**_kwargs):
        raise RuntimeError(f"provider rejected key {fake_key}")

    result = main(
        settings_obj=settings,
        models={"claude": "anthropic/model", "gpt4o": "openai/model", "gemini": "gemini/model"},
        completion_fn=completion,
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "SKIPPED claude (no key)" in output
    assert "SKIPPED gemini (no key)" in output
    assert "[REDACTED]" in output
    assert fake_key not in output


def test_checker_retries_503_once_after_ten_seconds(capsys):
    settings = SimpleNamespace(
        anthropic_api_key=None,
        openai_api_key=None,
        gemini_api_key="fake-key-for-tests-0123456789",
    )
    calls = []
    waits = []

    def completion(**_kwargs):
        calls.append(True)
        if len(calls) == 1:
            error = RuntimeError("service unavailable")
            error.status_code = 503
            raise error
        return object()

    result = main(
        settings_obj=settings,
        models={"gemini": "gemini/model"},
        completion_fn=completion,
        sleep_fn=waits.append,
    )

    assert result == 0
    assert len(calls) == 2
    assert waits == [10]
    assert "OK gemini" in capsys.readouterr().out
