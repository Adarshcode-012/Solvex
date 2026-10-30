FROM python:3.11-slim

WORKDIR /app

# System deps for chromadb / building wheels + curl for the HEALTHCHECK below
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user — this app handles paid AI provider API keys, so we
# don't want a future dependency RCE to hand an attacker root inside the
# container. uid/gid 1000 is arbitrary but fixed, so the mounted volumes
# below have a stable, predictable owner across restarts.
RUN useradd --create-home --uid 1000 solvex \
    && mkdir -p /app/memory/data /app/memory/chroma_db \
    && chown -R solvex:solvex /app
USER solvex

# Persisted memory/usage data — mount a volume here in production
VOLUME ["/app/memory/data", "/app/memory/chroma_db"]

EXPOSE 8000

# Lets `docker ps` / orchestrators (Compose, Kubernetes, Railway, etc) see
# whether the app is actually serving requests, not just that the process
# is running.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# APP_ENV should be set to "production" via the platform's env config,
# which forces APP_SECRET_KEY and CORS_ORIGINS to be set too (see config.py).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
