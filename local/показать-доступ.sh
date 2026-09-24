#!/usr/bin/env bash
# ==========================================================================
#  Что ввести, чтобы войти в Директора: адрес, логин и пароль.
#
#  Печатает на экран этого компьютера. Вывод никому не пересылать —
#  в нём пароли от Директора.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

if [ ! -f "$ROOT/.env" ]; then
    echo "Файл настроек $ROOT/.env не найден."
    exit 1
fi

# Читаем сами, а не через source: в пароле может быть что угодно, включая
# знак доллара и кавычки, и подставлять такую строку в shell нельзя.
value() {
    sed -n "s/^$1=//p" "$ROOT/.env" | head -1 | sed -e 's/^"//' -e "s/^'//" \
        -e 's/"$//' -e "s/'$//"
}

PORT="$(value APP_PORT)"
PORT="${PORT:-8000}"

echo ""
echo "── Вход в Директор ───────────────────────────────"
echo "  Адрес:  http://localhost:$PORT"
if [ "$(value BIND_HOST)" = "0.0.0.0" ]; then
    IP=$(ipconfig getifaddr en0 2>/dev/null || echo "адрес-этого-компьютера")
    echo "  В сети: http://$IP:$PORT"
fi
echo ""
echo "  Владелец"
echo "    логин:  $(value OWNER_LOGIN)"
echo "    пароль: $(value OWNER_PASSWORD)"
echo ""
echo "  Администратор"
echo "    логин:  $(value OPERATOR_LOGIN)"
echo "    пароль: $(value OPERATOR_PASSWORD)"
echo ""
echo "  Набирать ровно как здесь, с учётом заглавных букв."
echo "──────────────────────────────────────────────────"
echo ""
