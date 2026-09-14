# Один образ на всё: интерфейс собирается здесь же и кладётся туда, откуда
# его отдаёт бэкенд. Так у Директора один адрес вместо двух, и запускать
# нечего, кроме него и базы.

# ── Сборка интерфейса ───────────────────────────────────────────────────────
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── Приложение ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
# Собранный интерфейс — туда, где бэкенд его ищет.
COPY --from=web /web/dist ./static

# Папка для выгрузок создаётся здесь, до смены пользователя: приложение
# работает не от root и само её создать не сможет.
RUN mkdir -p /app/output/stories /app/assets/fonts

RUN useradd --system --create-home rubl && chown -R rubl:rubl /app
USER rubl

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
