#!/usr/bin/env bash
# ==========================================================================
#  Узнать chat_id для TELEGRAM_CHAT_ID в .env.
#
#     ./scripts/телеграм-chat-id.sh <ТОКЕН БОТА>
#
#  Токен передаётся аргументом прямо в терминале — сюда, в чат с Claude, его
#  вставлять не нужно и не стоит: это такой же секрет, как пароль, и правило
#  проекта то же самое, что для остальных ключей (см. ROTATION.md) — секреты
#  живут только в .env на твоей машине или сервере. Сам скрипт токен нигде
#  не печатает и не сохраняет, только использует для одного запроса к
#  Telegram.
#
#  Порядок:
#    1. Напиши @BotFather в Telegram → /newbot → получишь токен вида
#       123456:ABC-DEF...
#    2. Добавь бота в нужный чат или группу (или просто напиши ему в личку).
#    3. Отправь в этот чат любое сообщение ПОСЛЕ того, как бот там появился.
#    4. Запусти этот скрипт с токеном из шага 1.
# ==========================================================================
set -uo pipefail

ТОКЕН="${1:-}"
if [ -z "$ТОКЕН" ]; then
    echo "Использование: ./scripts/телеграм-chat-id.sh <ТОКЕН БОТА>"
    exit 1
fi

ОТВЕТ=$(curl -s --max-time 20 "https://api.telegram.org/bot${ТОКЕН}/getUpdates")

if ! printf '%s' "$ОТВЕТ" | grep -q '"ok":true'; then
    echo "✗ Telegram не принял токен."
    echo "  Проверьте, что скопировали его у @BotFather целиком, без пробелов."
    exit 1
fi

НАЙДЕНО=$(printf '%s' "$ОТВЕТ" | python3 -c '
import json, sys
data = json.load(sys.stdin)
чаты = {}
for u in data.get("result", []):
    msg = u.get("message") or u.get("channel_post") or {}
    chat = msg.get("chat")
    if chat:
        чаты[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
for cid, title in чаты.items():
    print(f"{cid}\t{title}")
' 2>/dev/null)

if [ -z "$НАЙДЕНО" ]; then
    echo "Сообщений не найдено. Проверьте:"
    echo "  - бот действительно добавлен в чат или группу;"
    echo "  - сообщение в чате отправлено ПОСЛЕ добавления бота (старые getUpdates не видит);"
    echo "  - если это группа — у бота выключен Privacy Mode: @BotFather → /mybots →"
    echo "    выбрать бота → Bot Settings → Group Privacy → Turn off."
    exit 1
fi

echo "Найденные чаты (chat_id → название):"
printf '%s\n' "$НАЙДЕНО" | while IFS=$'\t' read -r cid title; do
    printf '  %s → %s\n' "$cid" "$title"
done
echo ""
echo "Впишите нужный chat_id в .env → TELEGRAM_CHAT_ID и перезапустите:"
echo "  ./local/update.sh"
