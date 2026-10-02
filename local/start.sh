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

# Docker Desktop кладёт команду docker не всегда туда, куда смотрит PATH.
. "./docker-path.sh"

echo "── Проверки ──────────────────────────────────────"

if ! command -v docker >/dev/null; then
    echo "  ✗ Команда docker не найдена. Искал здесь:$DOCKER_LOOKED_IN"
    echo ""
    echo "    Если Docker Desktop ещё не установлен — поставьте:"
    echo "    https://www.docker.com/products/docker-desktop/"
    echo ""
    echo "    Если установлен и открыт — значит команды лежат в другом месте."
    echo "    Откройте Docker Desktop → Settings → Advanced и включите"
    echo "    установку CLI-инструментов в /usr/local/bin (потребуется пароль)."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "  ✗ Docker установлен, но не запущен."
    echo "    Откройте Docker Desktop и дождитесь, пока он загрузится."
    exit 1
fi
echo "  ✓ Docker работает"

# Файл настроек создаётся сам, и человека ни о чём не спрашивают. Здесь
# только то, что человеку знать незачем: адрес базы и пароль к ней. Ключи
# YCLIENTS и Telegram задаются в самом Директоре, в разделе
# «Настройки → Интеграции» — раньше ради них приходилось открывать этот файл
# в редакторе, и половина установок на этом и останавливалась.
if [ ! -f "$ROOT/.env" ]; then
    PASS=$(openssl rand -hex 24 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    cat > "$ROOT/.env" <<ENVEOF
# Создан автоматически при первом запуске. Ключи YCLIENTS и Telegram задаются
# в самом Директоре: «Настройки → Интеграции». Вписывать их сюда не нужно.
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rubl_director
POSTGRES_USER=rubl
POSTGRES_PASSWORD=$PASS
APP_PORT=8000
DEBUG=false
ENVEOF
    chmod 600 "$ROOT/.env"
    echo "  ✓ файл настроек создан, пароль базы сгенерирован"
else
    # Незаполненные заготовки вида КЛЮЧ=<что-то> раньше останавливали запуск.
    # Теперь они просто убираются: пустое значение означает «не настроено», и
    # Директор сам покажет, чего ему не хватает.
    if grep -qE '^[A-Z_]+=<' "$ROOT/.env"; then
        sed -i.bak -E '/^[A-Z_]+=</d' "$ROOT/.env"
        echo "  ✓ незаполненные заготовки убраны (копия: .env.bak)"
    fi
    echo "  ✓ файл настроек на месте"
fi

# Пароль базы обязателен: без него не поднимется сам PostgreSQL. Если файл
# достался от прежней установки и пароля в нём нет — дописываем.
if ! grep -qE '^POSTGRES_PASSWORD=.+' "$ROOT/.env"; then
    PASS=$(openssl rand -hex 24 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    sed -i.bak -E '/^POSTGRES_PASSWORD=/d' "$ROOT/.env"
    printf 'POSTGRES_PASSWORD=%s\n' "$PASS" >> "$ROOT/.env"
    echo "  ✓ пароль базы сгенерирован"
fi

# Папка для журнала обзвона. Её нужно создать до запуска: иначе Docker
# создаст её сам от root, и приложение внутри контейнера писать не сможет.
mkdir -p "$ROOT/output"
echo "  ✓ папка для журнала обзвона готова"

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

# На Linux смонтированная папка принадлежит хозяину компьютера, а приложение
# работает под своим пользователем. Без этой строки журнал обзвона не пишется.
# На Windows и macOS Docker решает это сам, и команда просто ничего не меняет.
docker compose --env-file "$ROOT/.env" exec -T -u root director \
    chown -R rubl /app/output >/dev/null 2>&1 || true

# Пароль базы в .env и пароль внутри самой базы могут разойтись.
#
# PostgreSQL берёт POSTGRES_PASSWORD только один раз — когда впервые создаёт
# том с данными. Дальше пароль живёт внутри тома, и смена строки в .env на
# него уже не влияет. Том при этом переживает переустановку программы и
# бывает общим у старой и новой установки: docker compose называет его по
# имени папки local, а она одинакова у всех версий. Так 30.09.2026 и вышло:
# новая установка создала .env со свежим паролем, а база помнила прежний, и
# Директор перестал запускаться с «password authentication failed».
#
# Чиним не удалением тома — в нём смены, заметки администратора и настройки
# себестоимости, которых больше нигде нет, — а приведением пароля внутри базы
# к тому, что в .env. Изнутри контейнера базы вход через локальный сокет не
# требует пароля: так устроен официальный образ PostgreSQL, и попасть туда
# может только тот, у кого есть Docker на этом компьютере.
DB_USER=$(grep -m1 -E '^POSTGRES_USER=' "$ROOT/.env" | cut -d= -f2-)
DB_USER=${DB_USER:-rubl}
DB_PASS=$(grep -m1 -E '^POSTGRES_PASSWORD=' "$ROOT/.env" | cut -d= -f2-)

if ! docker compose --env-file "$ROOT/.env" exec -T director python -c "
import psycopg2
from app.config import settings
psycopg2.connect(settings.database_url_sync, connect_timeout=5).close()
" >/dev/null 2>&1; then
    echo "  · пароль базы не совпадает с настройками — согласую…"
    # Пароль шестнадцатеричный (так его генерирует установка), кавычек и
    # спецсимволов в нём нет — подставлять в SQL безопасно. На случай пароля,
    # вписанного руками, одинарные кавычки удваиваются.
    SAFE_PASS=$(printf '%s' "$DB_PASS" | sed "s/'/''/g")
    if docker exec -i rubl_db psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -q \
            -c "ALTER USER \"$DB_USER\" WITH PASSWORD '$SAFE_PASS';" >/dev/null 2>&1; then
        echo "  ✓ пароль базы согласован, данные на месте"
    else
        echo "  ✗ Согласовать пароль базы не удалось."
        echo ""
        echo "    База создана с другим именем пользователя, чем указано в .env"
        echo "    (POSTGRES_USER=$DB_USER). Проверьте, что .env — от этой установки."
        exit 1
    fi
fi

# Вывод миграции придерживаем: при ошибке в .env приложение отвечает
# трейсбеком на десятки строк, в котором по делу одна — какая настройка не
# подошла. Её и нужно показать человеку, а не заставлять искать.
if ! MIGRATION=$(docker compose --env-file "$ROOT/.env" exec -T director \
        alembic upgrade head 2>&1); then
    # Из строки берём только текст ошибки. Хвост «[type=..., input_value=...]»
    # отбрасывается не для красоты: pydantic вкладывает туда само значение,
    # то есть в вывод попал бы кусок пароля.
    REASON=$(printf '%s\n' "$MIGRATION" | awk '/Value error, /{
        sub(/.*Value error, /, ""); sub(/ \[type=.*/, ""); print; exit }')
    # Название настройки pydantic печатает строкой выше текста ошибки.
    FIELD=$(printf '%s\n' "$MIGRATION" | awk '
        /Value error, /{ gsub(/^[ \t]+|[ \t]+$/, "", prev); print prev; exit }
        { prev = $0 }')

    if [ -n "$REASON" ]; then
        echo "  ✗ Настройки в .env не подошли:"
        echo ""
        echo "      $REASON"
        echo ""
        if [ -n "$FIELD" ]; then
            echo "    Строка в .env: $(printf '%s' "$FIELD" | tr '[:lower:]' '[:upper:]')"
        fi
        echo "    Откройте .env, исправьте и запустите этот файл снова."
    else
        echo "  ✗ Не удалось обновить структуру базы. Директор запущен не будет."
        printf '%s\n' "$MIGRATION" | tail -20 | sed 's/^/      /'
    fi
    exit 1
fi
echo "  ✓ структура базы обновлена"

# Последняя проверка: приложение должно отвечать. Печатать «запущен», не
# убедившись в этом, — значит отправить человека искать несуществующий адрес.
#
# Проверяем в цикле, а не один раз. Uvicorn начинает принимать соединения не
# в тот же миг, когда контейнер запущен, и одна попытка попадает в промежуток:
# на живой установке скрипт сообщил, что приложение не отвечает, тогда как в
# журнале рядом стояло «Application startup complete».
ANSWERS=""
for _ in $(seq 1 30); do
    if docker compose --env-file "$ROOT/.env" exec -T director python -c \
            "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')" \
            >/dev/null 2>&1; then
        ANSWERS="да"
        break
    fi
    sleep 1
done

if [ -z "$ANSWERS" ]; then
    echo "  ✗ Приложение не ответило за 30 секунд. Последние строки журнала:"
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
