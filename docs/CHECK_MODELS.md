# Checking model configuration

`scripts/check_models.py` sends a small request to every model in the configured `MODELS` map. A normal run contacts model providers and loads `backend/.env`. Do not run it unless you intentionally want those provider requests and have configured credentials locally. Never paste your key into a command, chat, issue, or document.

## Safe mocked example

The following PowerShell commands set the requested placeholders and run the script with the dotenv loader and provider client replaced in memory. The mock raises an error instead of opening a network connection. Run them from the repository root:

```powershell
$env:GEMINI_API_KEY = 'invalid-placeholder'
$env:MODEL_GEMINI = 'gemini/placeholder-model'
@'
import os, runpy, sys, types
dotenv = types.ModuleType('dotenv')
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules['dotenv'] = dotenv
config = types.ModuleType('config')
config.settings = types.SimpleNamespace(anthropic_api_key=None, openai_api_key=None, gemini_api_key=os.environ['GEMINI_API_KEY'])
sys.modules['config'] = config
litellm = types.ModuleType('litellm')
def completion(**kwargs):
    raise RuntimeError('mocked completion; network disabled')
litellm.completion = completion
sys.modules['litellm'] = litellm
router = types.ModuleType('utils.ai_router')
router.MODELS = {'gemini': os.environ['MODEL_GEMINI']}
sys.modules['utils.ai_router'] = router
runpy.run_path('backend/scripts/check_models.py', run_name='__main__')
'@ | python -
Remove-Item Env:GEMINI_API_KEY
Remove-Item Env:MODEL_GEMINI
```

This deliberately does not verify provider access. Its expected result is:

| Role | Model | Result |
| --- | --- | --- |
| gemini | gemini/placeholder-model | `ERROR`: mocked completion; network disabled |

The default IDs are **UNVERIFIED - no key tested**. They come from the provider model pages, but this project has not tested them with real credentials:

| Role | Default model | Source |
| --- | --- | --- |
| Claude | `anthropic/claude-sonnet-5-5` | [Anthropic models overview](https://docs.anthropic.com/en/docs/about-claude/models/overview) |
| GPT-4o role | `openai/gpt-6.1-sol` | [OpenAI models](https://platform.openai.com/docs/models) |
| GPT-4o-mini role | `openai/gpt-6-luna` | [OpenAI models](https://platform.openai.com/docs/models) |
| Gemini and Gemini Flash | `gemini/gemini-3.8-flash` | [Gemini API models](https://ai.google.dev/gemini-api/docs/models) |

Model strings get an explicit provider prefix automatically when the configured value omits it. Gemini IDs must use the `gemini/` prefix.

## Step 3: Run it

This command sends a real request only for roles whose provider key is set. Run it only when you intend to contact those providers. Open PowerShell in the `backend` folder, then run:

```powershell
.\venv\Scripts\python.exe scripts\check_models.py
```

Run it from `backend`, not from `scripts`. The script loads `.env` from the backend directory when it is run. It retries a 503 once after 10 seconds and exits with code 1 if any configured role fails. Never paste your key.

In development, leave `REDIS_URL` empty unless Redis is running locally. A non-empty URL makes app components attempt Redis operations and can make startup or requests fail when Redis is unavailable.

## Step 4: Read the result

| You see | Meaning | What to do |
| --- | --- | --- |
| `OK` for a role | It works | Share the output only after checking that it contains no private information. |
| `SKIPPED <role> (no key)` | That provider has no configured key | No request was sent for that role. |
| model not found / 404 | The model ID is wrong | Recopy it from the model page. Keep the `gemini/` prefix. |
| API key invalid / 401 / 403 | Wrong key, or a typo in `.env` | Recreate the key in AI Studio. |
| 429 / quota | Free-tier limit hit | Wait, and don’t turn on billing. |
| `ModuleNotFoundError` | The wrong Python environment is running the script | Run it with the backend virtual environment's Python from the `backend` directory. |
| “no AI key configured” | `.env` wasn’t loaded | You’re in the wrong folder. |

A LiteLLM warning about missing price data is harmless. Never paste your key.
