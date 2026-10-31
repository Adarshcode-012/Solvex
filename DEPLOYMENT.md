# SolveX Deployment

## Required configuration

Set these values in `backend/.env` or your secret manager:

- One AI provider key: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`
- `GUEST_SESSION_SECRET`: random value used to sign anonymous guest cookies
- `APP_ENV=production`
- `CORS_ORIGINS`: comma-separated HTTPS frontend origins
- `REDIS_URL=redis://redis:6379/0`
- `RATE_LIMIT_STORAGE_URI=redis://redis:6379/1`
- `MEMORY_BACKEND=chroma`
- `CHROMA_DB_PATH=/app/memory/chroma_db`
- Optional `JUDGE0_API_KEY`

Production refuses to start with memory-only rate limiting, unavailable Chroma, missing guest signing secrets, or invalid CORS origins.

## Start and health check

```bash
docker compose up -d --build
curl http://localhost:8000/health
```

The API, Redis, and frontend services have health checks. Uvicorn allows 30 seconds for in-flight requests during shutdown.

## Key rotation

1. Generate a new `GUEST_SESSION_SECRET`.
2. Update the secret in the deployment secret manager.
3. Restart or roll the API service.
4. Existing guest cookies become invalid and receive new sessions.
5. Rotate AI and Judge0 keys through the same secret manager; never commit them.

## Backups

Back up both persistent stores before upgrades:

- Chroma: the `solvex_chroma` volume or `CHROMA_DB_PATH`
- Metadata: `backend/memory/data/metadata.sqlite3` and its `-wal`/`-shm` files while the service is stopped, or use a SQLite backup API
- Redis: the `solvex_redis` volume/AOF for rate-limit and usage continuity

Test restores on a separate deployment. Do not treat JSON fallback files as the source of truth when running multiple workers.

## Rollback

1. Identify the previous image tag or Git commit.
2. Stop the current deployment after draining traffic.
3. Restore compatible Chroma, SQLite, and Redis backups if the schema changed.
4. Deploy the previous image/commit.
5. Verify `/health`, a guest session, and `/health/detailed` through the admin path before reopening traffic.
