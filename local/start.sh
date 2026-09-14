#!/usr/bin/env bash
# ==========================================================================
#  Запуск Директора на этом компьютере.
#
#  Первый запуск дольше — Docker собирает образ. Дальше секунды.
#  Остановить: local/stop.sh
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

echo "── Проверки ──────────────────────────────────────"

if ! command -v docker >/dev/null; then
    echo "  ✗ Docker не установлен."
    echo "    Скачайте Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "  ✗ Docker установлен, но не запущен."
    echo "    Откройте Docker Desktop и дождитесь, пока он загрузится."
    exit 1
fi
echo "  ✓ Docker работает"

if [ ! -f "$ROOT/.env" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo ""
    echo "  Создан файл настроек: $ROOT/.env"
    echo "  Откройте его и заполните значения в угловых скобках:"
    echo "    ключи YCLIENTS, пароль базы, логины и пароли для входа."
    echo "  Потом запустите этот файл ещё раз."
    exit 1
fi
echo "  ✓ Файл настроек на месте"

# Незаполненные заготовки — частая причина «оно не запускается».
if grep -qE '^[A-Z_]+=<' "$ROOT/.env"; then
    echo "  ✗ В .env остались незаполненные значения:"
    grep -nE '^[A-Z_]+=<' "$ROOT/.env" | sed 's/^/      /'
    exit 1
fi
echo "  ✓ Настройки заполнены"

echo ""
echo "── Запуск ────────────────────────────────────────"
docker compose --env-file "$ROOT/.env" up -d --build

echo ""
echo "── Подготовка базы ───────────────────────────────"

# Ждём, пока контейнер приложения действительно поднимется. Без этого
# миграция уходит в перезапускающийся контейнер и тихо не выполняется.
READY=""
for _ in $(seq 1 60); do
    STATE=$(docker inspect -f '{{.State.Status}}' rubl_director 2>/dev/null || echo "нет")
    if [ "$STATE" = "running" ]; then
        if docker compose --env-file "$ROOT/.env" exec -T director \
            python -c "import socket;socket.create_connection(('postgres',5432),3)" >/dev/null 2>&1; then
            READY="да"
            break
        fi
    fi
    sleep 2
done

if [ -z "$READY" ]; then
    echo "  ✗ Приложение не запустилось. Что случилось:"
    docker compose --env-file "$ROOT/.env" logs --tail 20 director | sed 's/^/      /'
    exit 1
fi

if ! docker compose --env-file "$ROOT/.env" exec -T director alembic upgrade head; then
    echo "  ✗ Не удалось обновить структуру базы. Директор запущен не будет."
    exit 1
fi
echo "  ✓ структура базы обновлена"

# Последняя проверка: приложение должно отвечать. Печатать «запущен», не
# убедившись в этом, — значит отправить человека искать несуществующий адрес.
if ! docker compose --env-file "$ROOT/.env" exec -T director \
        python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')" >/dev/null 2>&1; then
    echo "  ✗ Приложение не отвечает на проверку здоровья."
    docker compose --env-file "$ROOT/.env" logs --tail 20 director | sed 's/^/      /'
    exit 1
fi
echo "  ✓ приложение отвечает"

PORT="${APP_PORT:-8000}"
echo ""
echo "══════════════════════════════════════════════════"
echo "  Директор запущен: http://localhost:$PORT"
if [ "${BIND_HOST:-127.0.0.1}" = "0.0.0.0" ]; then
    IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "адрес-этого-компьютера")
    echo "  Из салона по сети:  http://$IP:$PORT"
fi
echo ""
echo "  Первая загрузка данных из YCLIENTS начнётся через"
echo "  десять секунд и займёт несколько минут."
echo "══════════════════════════════════════════════════"
