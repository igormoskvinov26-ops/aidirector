#!/bin/bash
# Локальный запуск для разработки.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== РублЪ AI Director (dev) ==="

if [ ! -f .env ]; then
    echo "Нет .env. Скопируй .env.example в .env и заполни:"
    echo "  cp .env.example .env"
    echo "  POSTGRES_PASSWORD:  openssl rand -base64 24"
    echo "  ADMIN_PASSWORD:     openssl rand -base64 18"
    exit 1
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "[1/4] PostgreSQL..."
docker compose -f docker/docker-compose.yml up -d postgres
until docker compose -f docker/docker-compose.yml exec -T postgres pg_isready -q 2>/dev/null; do
    sleep 1
done
echo "       OK"

echo "[2/4] Миграции..."
(cd backend && uv run alembic upgrade head 2>&1 | tail -2)

echo "[3/4] Бэкенд :8000..."
(cd backend && uv run uvicorn app.main:app --reload --port 8000) &
for _ in $(seq 1 30); do
    curl -sf http://localhost:8000/health >/dev/null && break
    sleep 1
done
curl -sf http://localhost:8000/health >/dev/null || { echo "       бэкенд не поднялся"; exit 1; }
echo "       OK"

echo "[4/4] Фронтенд :3000..."
(cd frontend && npm run dev) &

echo ""
echo "  http://localhost:3000     — дашборд"
echo "  http://localhost:8000/api/docs — API (при DEBUG=true)"
echo "  Ctrl+C — остановить всё"
wait
