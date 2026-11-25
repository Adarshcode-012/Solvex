FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# fixed uid and gid keep volume ownership stable across restarts
RUN useradd --create-home --uid 1000 solvex \
    && mkdir -p /app/memory/data /app/memory/chroma_db \
    && chown -R solvex:solvex /app
USER solvex

# mount a volume here to keep memory and usage data
VOLUME ["/app/memory/data", "/app/memory/chroma_db"]

EXPOSE 8000

# check that the API can serve requests
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# set app_env to production through the deployment environment
CMD ["sh", "-c", "python startup_check.py && exec uvicorn main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 30"]
