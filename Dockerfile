# NFL Edge Finder — production image
# Same image serves the app (default CMD) and, later, the cron sidecar
# (override CMD with the script runner). Targets: local test → VPS/Azure.
FROM python:3.13-slim

# tzdata: cron sidecar schedules are ET; app timestamps must match Mac behavior.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/New_York
# NOTE: PYTHONPATH is deliberately left unset — the Mac's run.command works
# around a leaked PYTHONPATH from the agent session; a clean container has none.

WORKDIR /app

# Dependencies first: this layer only rebuilds when requirements.txt changes,
# so code-only pushes produce fast image builds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code. .dockerignore keeps secrets/auth/data OUT of the image —
# auth.yaml and .streamlit/secrets.toml are bind-mounted at runtime:
#   docker run -v $PWD/auth.yaml:/app/auth.yaml:ro \
#              -v $PWD/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro ...
COPY . .

# Run as non-root. Streamlit writes nothing outside /app at runtime.
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

# Streamlit serves a built-in /healthz returning "ok" — used by compose,
# the VPS update flow, and any future Azure health probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/healthz', timeout=4)" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.headless", "true", \
     "--server.port", "8501", \
     "--server.address", "0.0.0.0", \
     "--browser.gatherUsageStats", "false"]
