# SolveX Deployment

## Required configuration

Set these values in `backend/.env` or your secret manager:

- One AI provider key: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`
- `GUEST_SESSION_SECRET`: random value used to sign anonymous guest cookies
- `APP_ENV=production`
- `CORS_ORIGINS`: comma-separated HTTPS frontend origins
- `REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0`
- `RATE_LIMIT_STORAGE_URI=redis://:<REDIS_PASSWORD>@redis:6379/1`
- `REDIS_PASSWORD`: generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`; Compose refuses to start when it is unset
- `MEMORY_BACKEND=chroma`
- `CHROMA_DB_PATH=/app/memory/chroma_db`
- Optional `JUDGE0_API_KEY`

Production refuses to start with memory-only rate limiting, unavailable Chroma, missing guest signing secrets, missing Redis passwords (unless `REDIS_ALLOW_NO_AUTH=true` is explicitly set), invalid CORS origins, or more than one worker when using local Chroma.

## Start and health check

```bash
docker compose --env-file backend/.env up -d --build
curl http://localhost:8000/health
```

The API, Redis, and frontend services have health checks. Uvicorn allows 30 seconds for in-flight requests during shutdown.

Redis TLS is not configured by this Compose file. To add it, configure Redis with a TLS certificate and trusted CA, use `rediss://` for `REDIS_URL` and `RATE_LIMIT_STORAGE_URI`, and configure the API's Redis client to verify that CA.

## Admin-only diagnostics

Set a server-side `ADMIN_TOKEN` using `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Keep it in the API's environment only; never add it to a `VITE_` variable or frontend file, because frontend values are public to every browser user. Rotate it by generating a new token, updating the API environment, and restarting the API; the previous token stops working after restart. The public nginx frontend returns 404 for `/api/health/detailed` and `/api/usage/reset`. Operators can call these inside the API container, for example `docker compose exec api curl -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/health/detailed` or `docker compose exec api curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/usage/reset`.

## Behind a CDN or platform proxy

Set `TRUSTED_PROXIES` to the addresses or CIDRs of every trusted proxy that can connect to the API. Compose assigns nginx the fixed address `172.30.0.4` and trusts only `172.30.0.4/32`. The proxy must replace `X-Forwarded-For` with the client address it verified; nginx does this with `proxy_set_header X-Forwarded-For $remote_addr;`. If nginx itself receives traffic from a CDN, configure nginx's real-IP module with the CDN's published ranges (`set_real_ip_from <CDN-CIDR>;`, `real_ip_header X-Forwarded-For;`, and `real_ip_recursive on;`) before forwarding. Do not add arbitrary client networks to `TRUSTED_PROXIES`.

## Key rotation

1. Generate a new `GUEST_SESSION_SECRET`.
2. Update the secret in the deployment secret manager.
3. Restart or roll the API service.
4. Existing guest cookies become invalid and receive new sessions.
5. Rotate AI and Judge0 keys through the same secret manager; never commit them.

## Storage and scaling

Run one API instance with one worker when `MEMORY_BACKEND=chroma`. SQLite metadata and Chroma are local files on that instance, stored in the Compose `solvex_memory` and `solvex_chroma` volumes. Back up both volumes. Redis can be shared by multiple services, but shared Redis does not make the local SQLite or Chroma files safe for multiple API replicas. Multi-replica storage needs PostgreSQL and a Chroma server; neither is implemented here.

The startup guard reads `WEB_CONCURRENCY`, visible Uvicorn/Gunicorn `--workers` or `-w` arguments, and `GUNICORN_CMD_ARGS`. If a platform hides its worker count from the API process, set `WEB_CONCURRENCY=1` explicitly.

### Backup and restore

Before an upgrade, stop the API and archive both local data volumes. Replace `<compose-project>` with the project prefix shown by `docker volume ls`:

```bash
docker compose --env-file backend/.env stop api
mkdir -p backups
docker run --rm -v <compose-project>_solvex_memory:/data -v "$PWD/backups:/backup" alpine tar -czf /backup/solvex_memory.tar.gz -C /data .
docker run --rm -v <compose-project>_solvex_chroma:/data -v "$PWD/backups:/backup" alpine tar -czf /backup/solvex_chroma.tar.gz -C /data .
```

For restore, stop the API, restore the archive contents into the corresponding volumes, start the API, and check `/health`:

```bash
docker compose --env-file backend/.env stop api
docker run --rm -v <compose-project>_solvex_memory:/data -v "$PWD/backups:/backup" alpine sh -c 'tar -xzf /backup/solvex_memory.tar.gz -C /data'
docker run --rm -v <compose-project>_solvex_chroma:/data -v "$PWD/backups:/backup" alpine sh -c 'tar -xzf /backup/solvex_chroma.tar.gz -C /data'
docker compose --env-file backend/.env up -d api
curl --fail http://localhost:8000/health
```

## Chroma upgrade path

Make and verify a backup of `solvex_chroma` before changing Chroma versions. Stop the API so no writes occur during export. Run `backend/scripts/migrate_chroma.py export` using the old Chroma environment, then run `import` using the new environment and an empty target persistence directory. The script transfers collection names, collection metadata, IDs, documents, and record metadata in batches; it does not delete or modify the source database. Keep the old volume and JSON export until collection counts and `where={"user_id": "..."}` queries match in the new database. Point `CHROMA_DB_PATH` at the migrated target only after verification, then start the API and check `/health` and guest-scoped memory results.

Example commands, run once with the old environment and once with the new environment:

```bash
python backend/scripts/migrate_chroma.py export --path /path/to/old/chroma --output backups/chroma-export.json
python backend/scripts/migrate_chroma.py import --path /path/to/new/empty/chroma --input backups/chroma-export.json
```
