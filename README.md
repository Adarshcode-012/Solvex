# SolveX

A multi-agent competitive-programming solver. Give it a DSA problem (as text or a screenshot), and a five-stage agent pipeline analyzes it, plans an approach, writes a solution, reviews it, and verifies it against sample test cases before returning it.

## How it works

Each solve request runs through five agents, orchestrated as a LangGraph state machine:

1. **Analyzer** — parses the problem statement into structured constraints, category, and sample I/O.
2. **Strategist** — picks an algorithmic approach given the constraints.
3. **Coder** — writes the solution in the requested language.
4. **Reviewer** — checks the solution for correctness/style issues before it's judged.
5. **Judge** — runs the code against sample test cases via [Judge0](https://rapidapi.com/judge0-official/api/judge0-ce) and loops back to the Coder with feedback if it fails.

A memory layer (episodic, semantic, procedural, temporal — backed by local JSON + ChromaDB) lets the pipeline learn from past attempts over time, and requests are routed across Claude, GPT-4o, and Gemini depending on which model each agent role is best suited for, with automatic fallback if a provider is unavailable.

## Stack

- **Backend**: FastAPI, LangGraph, LiteLLM (multi-provider AI routing), ChromaDB
- **Frontend**: React, TypeScript, Vite, Tailwind
- **Runtime**: Python 3.13 and Node.js 20.19+

## Getting started

See [`SETUP.md`](./SETUP.md) for full setup instructions, including generating the API secret key and configuring environment variables for both local development and production deployment.

Quick version:

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
.\venv\Scripts\python.exe -u dev_server.py 2>&1 | Tee-Object -FilePath .\dev.log 2>&1 | Tee-Object -FilePath .\dev.log

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open `http://localhost:5173`.

## Configuration

All configuration is via environment variables — see `backend/.env.example` and `frontend/.env.example` for the full list. At minimum you'll need one AI provider key (Anthropic, OpenAI, or Gemini). Guest session secrets are optional in development and required only in production: set `GUEST_SESSION_SECRET` or `APP_SECRET_KEY`. Set `MEMORY_BACKEND=chroma` for vector memory or `MEMORY_BACKEND=json` for the explicit JSON backend.

A Judge0 API key is optional: without it, the Judge step is skipped and results are marked `unverified` rather than pretending to have compiled and run the code.

### If you see a rate limit

Gemini quotas are applied to the Google Cloud project, so replacing an API key
from the same project does not reset the quota. In Google AI Studio, open the
project's **Rate limits** page and check the model row and the request-per-minute,
token-per-minute, and request-per-day limits against current usage. A few solves
can exhaust a free-tier quota when a thinking model is selected. Lower usage by
setting `MODEL_FAST` to a cheaper same-provider model for Analyzer and Reviewer,
setting the per-role `*_MAX_TOKENS` limits, or reducing the number of retries
with `JUDGE_MAX_ITERATIONS`. The installed LiteLLM version does not expose a
documented Gemini reasoning-effort control, so `AI_REASONING_EFFORT` is not
configured by this application.

## Deployment

A `Dockerfile` and `docker-compose.yml` are included for the backend. In production, set `APP_ENV=production` — the app will refuse to start unless a guest session secret and valid HTTPS `CORS_ORIGINS` are set. If `MEMORY_BACKEND=chroma`, Chroma must also start successfully; otherwise production boot fails instead of silently falling back to JSON.

## License

MIT

# Run locally on Windows

Use two PowerShell terminals from the repository root. The backend loads
`backend/.env` relative to `backend/config.py` and uses valid process environment
keys when supplied.
Changes saved to backend/.env trigger the backend development reloader.
Changes to keys set in the terminal process environment require restarting
the backend terminal.

Backend terminal:

```powershell
cd .\backend
$env:BACKEND_PORT = '8001'
.\venv\Scripts\python.exe -u dev_server.py 2>&1 | Tee-Object -FilePath .\dev.log
```

Frontend terminal:

```powershell
cd .\frontend
$env:DEV_API_PORT = '8001'
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`; the backend is at `http://127.0.0.1:8001`.
The Vite proxy targets `127.0.0.1` so `localhost` cannot resolve to a different
IPv6 listener. Docker Desktop may hold port 8000; this setup uses 8001 instead.
Before starting, check for port clashes with `netstat -ano | findstr :8001`
and `netstat -ano | findstr :5173`. The launcher
`powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1` checks both ports,
clears placeholder-looking inherited values in its own process, and prints the
two commands and URLs. Run the backend command in a visible
terminal so Windows can deliver Uvicorn's reload control event; run the frontend
command in a second terminal.

To confirm Gemini routing from the backend startup log, run this from the
repository root after the backend starts:

```powershell
Select-String -Path .\backend\dev.log -Pattern "ai_keys_loaded.*configured=\['gemini'\]"
```

If the browser shows a Vite “Not Found” response, verify that the backend is
running on 8001, the frontend terminal has `DEV_API_PORT` set to 8001, and the
proxy request uses `/api/...` (for example, `/api/health`). Restart Vite after
changing its environment variable. Check the backend with
`curl.exe http://127.0.0.1:8001/health` and the proxy with
`curl.exe http://127.0.0.1:5173/api/health`.
# Local solve jobs

Solve jobs are stored in local SQLite (`backend/memory/data/solve_jobs.sqlite3`).
This job runner supports a single instance only. A restart loses running jobs;
their next poll returns `job_not_found`. Completed snapshots remain available
to the guest who created them.
