from pathlib import Path


def test_dotenv_file_and_ai_config_routing_are_cwd_independent(monkeypatch, tmp_path):
    import config
    import utils.ai_router as ai_router

    assert config.DOTENV_PATH == Path(config.__file__).resolve().parent / ".env"

    env_file = tmp_path / "backend-copy" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("GEMINI_API_KEY=fake-key-for-tests-0123456789\n")
    for name in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "APP_ENV",
        "MODEL_CLAUDE", "MODEL_GPT4O", "MODEL_GPT4O_MINI", "MODEL_GEMINI",
        "MODEL_GEMINI_FLASH", "CLAUDE_MODEL", "GPT4O_MODEL", "GPT4O_MINI_MODEL",
        "GEMINI_MODEL", "GEMINI_FLASH_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(
        config.Settings,
        "model_config",
        {**config.Settings.model_config, "env_file": env_file},
    )
    workdirs = [tmp_path / "cwd-one", tmp_path / "nested" / "cwd-two"]
    for workdir in workdirs:
        workdir.mkdir(parents=True)
        monkeypatch.chdir(workdir)
        loaded = config.Settings()
        assert loaded.available_keys["gemini"] is True

        monkeypatch.setattr(ai_router, "settings", loaded)
        monkeypatch.setattr(
            ai_router,
            "MODELS",
            {
                "claude": loaded.claude_model,
                "gpt4o": loaded.gpt4o_model,
                "gpt4o_mini": loaded.gpt4o_mini_model,
                "gemini": loaded.gemini_model,
                "gemini_flash": loaded.gemini_flash_model,
            },
        )
        summary = ai_router.get_ai_config_summary()
        for assignment in summary["auto_assignment"].values():
            assert assignment["ai"] == "gemini"
            assert assignment["model"] == "gemini/gemini-4-hydrogen"
