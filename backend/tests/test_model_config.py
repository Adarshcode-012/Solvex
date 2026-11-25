import os
from pathlib import Path
import subprocess
import sys

from config import Settings


def test_model_names_get_provider_prefixes_for_each_role():
    settings = Settings(
        _env_file=None,
        openai_api_key="fake-key-for-tests-0123456789",
        claude_model="claude-custom",
        gpt4o_model="gpt-custom",
        gpt4o_mini_model="gpt-mini-custom",
        gemini_model="gemini-custom",
        gemini_flash_model="gemini-flash-custom",
    )

    assert settings.claude_model == "anthropic/claude-custom"
    assert settings.gpt4o_model == "openai/gpt-custom"
    assert settings.gpt4o_mini_model == "openai/gpt-mini-custom"
    assert settings.gemini_model == "gemini/gemini-custom"
    assert settings.gemini_flash_model == "gemini/gemini-flash-custom"

def test_model_environment_override_changes_selected_model():
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "fake-key-for-tests-0123456789"
    env["MODEL_GPT4O"] = "unit-test-model"
    env.pop("GPT4O_MODEL", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from utils.ai_router import get_agent_model; "
            "print(get_agent_model('coder')[1])",
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "openai/unit-test-model"
