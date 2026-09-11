#!/usr/bin/env bash
# ==========================================================================
#  Сверка старого и нового .env
#
#  Показывает по каждому ключу, сменилось значение или нет, не печатая
#  сами значения — только короткий отпечаток sha256. Отпечатки достаточно
#  сравнить глазами: одинаковые = ключ НЕ перевыпущен.
#
#  Использование:
#     ./scripts/compare-env.sh /путь/к/старому/.env  .env
# ==========================================================================
set -euo pipefail

OLD="${1:-}"
NEW="${2:-.env}"

if [ -z "$OLD" ] || [ ! -f "$OLD" ]; then
    echo "Использование: $0 <старый .env> [новый .env]"
    echo "Старый лежит в присланном архиве: ai-director/.env"
    exit 1
fi
[ -f "$NEW" ] || { echo "Нет файла $NEW"; exit 1; }

# Ключи, которые обязаны смениться после утечки
SECRETS="YCLIENTS_PARTNER_TOKEN YCLIENTS_USER_TOKEN YCLIENTS_OLD_USER_TOKEN
         POSTGRES_PASSWORD DEEPSEEK_API_KEY ADMIN_PASSWORD TELEGRAM_BOT_TOKEN"

fp() {  # отпечаток значения, 8 символов
    local v="$1"
    [ -z "$v" ] && { echo "—пусто—"; return; }
    printf '%s' "$v" | sha256sum | cut -c1-8
}

val() { grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- || true; }

printf "%-26s %-10s %-10s %s\n" "КЛЮЧ" "СТАРЫЙ" "НОВЫЙ" "СТАТУС"
printf '%s\n' "--------------------------------------------------------------------"

problems=0
for key in $SECRETS; do
    o=$(val "$OLD" "$key")
    n=$(val "$NEW" "$key")

    if [ -z "$o" ] && [ -z "$n" ]; then
        status="не используется"
    elif [ -z "$n" ]; then
        status="ОТСУТСТВУЕТ в новом"; problems=$((problems+1))
    elif [ "$o" = "$n" ]; then
        status="НЕ ПЕРЕВЫПУЩЕН"; problems=$((problems+1))
    else
        status="перевыпущен"
    fi

    printf "%-26s %-10s %-10s %s\n" "$key" "$(fp "$o")" "$(fp "$n")" "$status"
done

echo ""
# Несекретные поля — их менять не нужно, но полезно видеть, что не потерялись
for key in YCLIENTS_COMPANY_ID YCLIENTS_OLD_COMPANY_ID POSTGRES_DB POSTGRES_USER ADMIN_LOGIN TELEGRAM_CHAT_ID; do
    o=$(val "$OLD" "$key"); n=$(val "$NEW" "$key")
    [ "$o" = "$n" ] && mark="=" || mark="изменено"
    printf "%-26s %s\n" "$key" "$mark"
done

echo ""
if [ "$problems" -gt 0 ]; then
    echo "Не готово: $problems ключ(ей) требуют внимания."
    exit 1
fi
echo "Все секреты перевыпущены."
