#!/usr/bin/env bash
# ==========================================================================
#  Проверка ключей из .env — до деплоя, ничего не меняет.
#
#     ./scripts/check-keys.sh
#
#  Стучится в YCLIENTS, DeepSeek и Telegram твоими ключами и говорит по
#  каждому: работает или нет. Значения ключей нигде не печатаются.
# ==========================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${1:-.env}"
ok=0; bad=0

green(){ printf '  \033[32m✓\033[0m %s\n' "$1"; ok=$((ok+1)); }
red(){   printf '  \033[31m✗\033[0m %s\n' "$1"; bad=$((bad+1)); }
warn(){  printf '  \033[33m!\033[0m %s\n' "$1"; }

if [ ! -f "$ENV_FILE" ]; then
    red "нет файла $ENV_FILE"
    echo ""
    echo "Файл должен лежать здесь, рядом с deploy.sh."
    echo "Если браузер сохранил его как .env.txt — переименуй: mv .env.txt .env"
    exit 1
fi

set -a; . "./$ENV_FILE"; set +a

echo ""
echo "── Файл ──────────────────────────────────────────"
green "$ENV_FILE найден"

perms=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE" 2>/dev/null)
if [ "$perms" = "600" ]; then green "права 600 — читаешь только ты"
else warn "права $perms — выполни: chmod 600 $ENV_FILE"; fi

echo ""
echo "── Обязательные поля ─────────────────────────────"
for k in YCLIENTS_PARTNER_TOKEN YCLIENTS_USER_TOKEN YCLIENTS_COMPANY_ID \
         OWNER_LOGIN OWNER_PASSWORD OPERATOR_LOGIN OPERATOR_PASSWORD POSTGRES_PASSWORD; do
    if [ -n "${!k:-}" ]; then green "$k заполнен"; else red "$k пустой"; fi
done

echo ""
echo "── Пароли ────────────────────────────────────────"
# Сожжённые и типовые пароли сравниваются по отпечатку sha256:
# сами значения лежали в публичном репозитории и здесь не повторяются.
WEAK_HASHES="$(sed -n 's/^    "\([0-9a-f]\{64\}\)".*/\1/p' backend/app/config.py)"
for k in OWNER_PASSWORD OPERATOR_PASSWORD POSTGRES_PASSWORD; do
    v="${!k:-}"
    h=$(printf '%s' "$v" | tr 'A-Z' 'a-z' | sha256sum | cut -d' ' -f1)
    if printf '%s\n' "$WEAK_HASHES" | grep -qx "$h"; then
        red "$k — известный слабый или сожжённый пароль, приложение не запустится"
    elif [ "${#v}" -lt 12 ]; then
        red "$k короче 12 символов — приложение не запустится"
    else
        green "$k подходит (${#v} символов)"
    fi
done

echo ""
echo "── YCLIENTS ──────────────────────────────────────"
yc=$(curl -s -o /tmp/.yc -w '%{http_code}' --max-time 20 \
     -H "Authorization: Bearer $YCLIENTS_PARTNER_TOKEN, User $YCLIENTS_USER_TOKEN" \
     -H "Accept: application/vnd.yclients.v2+json" \
     "https://api.yclients.com/api/v1/company/$YCLIENTS_COMPANY_ID/staff" 2>/dev/null)
case "$yc" in
    200) n=$(grep -o '"name"' /tmp/.yc 2>/dev/null | wc -l | tr -d ' ')
         green "токены работают, филиал отвечает (мастеров в ответе: $n)";;
    401|403) red "YCLIENTS отклонил токены ($yc) — проверь partner и user токен";;
    404) red "филиал $YCLIENTS_COMPANY_ID не найден — проверь YCLIENTS_COMPANY_ID";;
    000) red "нет связи с api.yclients.com";;
    *)   red "YCLIENTS ответил $yc";;
esac
rm -f /tmp/.yc


echo ""
echo "── Telegram ──────────────────────────────────────"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then warn "не задан — сторис отправляться не будут, остальное поедет"
else
    tg=$(curl -s --max-time 20 "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe" 2>/dev/null)
    if printf '%s' "$tg" | grep -q '"ok":true'; then
        green "бот отвечает: $(printf '%s' "$tg" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)"
        [ -z "${TELEGRAM_CHAT_ID:-}" ] && warn "TELEGRAM_CHAT_ID пустой — боту некуда слать"
    else red "Telegram отклонил токен — /revoke у @BotFather"; fi
fi

echo ""
echo "── Домен ─────────────────────────────────────────"
DOM="${DOMAIN:-$(printf '%s' "${CORS_ORIGINS:-}" | sed 's|https\?://||; s|/.*||; s|,.*||')}"
if [ -z "$DOM" ]; then warn "домен не определён"
else
    ip=$(dig +short "$DOM" 2>/dev/null | tail -1)
    if [ -z "$ip" ]; then red "$DOM не резолвится — A-запись ещё не создана или не разошлась"
    else green "$DOM → $ip"
         [ "$ip" != "95.81.99.227" ] && warn "ожидался 95.81.99.227 — проверь, тот ли это сервер"; fi
fi

echo ""
echo "──────────────────────────────────────────────────"
if [ "$bad" -gt 0 ]; then
    echo "  Не готово: $bad проблем(ы). Деплоить рано."
    exit 1
fi
echo "  Всё в порядке ($ok проверок). Можно деплоить:"
echo "    DOMAIN=$DOM ./deploy.sh"
