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
python main.py

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open `http://localhost:5173`.

## Configuration

All configuration is via environment variables — see `backend/.env.example` and `frontend/.env.example` for the full list. At minimum you'll need one AI provider key (Anthropic, OpenAI, or Gemini) and a `GUEST_SESSION_SECRET` (or `APP_SECRET_KEY`) to sign guest sessions. Set `MEMORY_BACKEND=chroma` for vector memory or `MEMORY_BACKEND=json` for the explicit JSON backend.

A Judge0 API key is optional: without it, the Judge step is skipped and results are marked `unverified` rather than pretending to have compiled and run the code.

## Deployment

A `Dockerfile` and `docker-compose.yml` are included for the backend. In production, set `APP_ENV=production` — the app will refuse to start unless a guest session secret and valid HTTPS `CORS_ORIGINS` are set. If `MEMORY_BACKEND=chroma`, Chroma must also start successfully; otherwise production boot fails instead of silently falling back to JSON.

## License

MIT
