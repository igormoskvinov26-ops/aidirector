FROM python:3.12-slim

# Fonts for story rendering. Brand faces are mounted from assets/fonts at
# runtime; these are the fallback so rendering degrades instead of crashing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install from the lockfile so builds are reproducible. The previous Dockerfile
# ran `uv pip install -r pyproject.toml`, which ignored uv.lock entirely and
# could pull different versions on every build.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

RUN useradd --system --create-home rubl && chown -R rubl:rubl /app
USER rubl

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
