# Один образ на всё: бэкенд отдаёт и API, и интерфейс — у Директора один
# адрес, и запускать нечего, кроме него и базы.
#
# Интерфейс приходит в пакете уже собранным (frontend/dist). Раньше он
# собирался здесь, и npm на салоне качал сотни пакетов из интернета;
# 30.10.2026 он завис на пятой минуте («Exit handler never called!») и
# обновление сорвалось. Собранный интерфейс от сети не зависит.

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
COPY frontend/dist ./static

# Папка для выгрузок создаётся здесь, до смены пользователя: приложение
# работает не от root и само её создать не сможет.
RUN mkdir -p /app/output/stories /app/assets/fonts

RUN useradd --system --create-home rubl && chown -R rubl:rubl /app
USER rubl

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Миграции — при каждом старте контейнера (инцидент 19.10.2026: пересборка
# прошла, а колонки в базу не добавились). Миграции идемпотентны.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
