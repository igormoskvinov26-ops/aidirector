#!/usr/bin/env bash
# ==========================================================================
#  Выкладка сайта rublbarber.ru в Yandex Object Storage
#
#     ./deploy.sh            — выложить
#     ./deploy.sh --dry-run  — показать, что изменится, ничего не трогая
#
#  Требуется aws (AWS CLI) и настроенный профиль — см. ./setup-keys.sh
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"

BUCKET="${BUCKET:-rublbarber.ru}"
PROFILE="${AWS_PROFILE_NAME:-rubl}"
ENDPOINT="https://storage.yandexcloud.net"
S3="s3://$BUCKET"

DRY=""
[ "${1:-}" = "--dry-run" ] && DRY="--dryrun"

aws_() { aws --profile "$PROFILE" --endpoint-url "$ENDPOINT" "$@"; }

command -v aws >/dev/null || {
    echo "Нет команды aws. Установить: uv tool install awscli"; exit 1; }

# Проверки перед выкладкой: лучше упасть здесь, чем выложить сломанное.
echo "── Проверки ──────────────────────────────────────"

for f in index.html privacy.html 404.html sitemap.xml robots.txt; do
    [ -f "$f" ] || { echo "  ✗ нет файла $f"; exit 1; }
done
echo "  ✓ все страницы на месте"

# Правило: страницы не обращаются к зарубежным доменам. Сайт переехал из
# Амстердама именно потому, что перестал открываться из России, и один
# сторонний CDN возвращает эту беду целиком.
#
# Проверяется именно правило, а не список известных нарушителей: раньше здесь
# перечислялись четыре имени, и любой пятый прошёл бы насквозь. Теперь
# наоборот — перечислено разрешённое, всё прочее останавливает выкладку.
# Совпадение проверяется по хвосту имени, поэтому поддомены покрыты:
# mc.yandex.ru и n2387007.yclients.com пройдут, а mc.yandex.ru.evil.com — нет.
ALLOWED="yclients\.com|yandex\.ru|yandex\.net|yandexcloud\.net|rublbarber\.ru|schema\.org|t\.me|www\.w3\.org"
FOREIGN=$(grep -ohE 'https?://[A-Za-z0-9._-]+' index.html privacy.html 404.html \
          | sed -E 's|https?://||' | sort -u | grep -vE "(^|\.)($ALLOWED)$" || true)
if [ -n "$FOREIGN" ]; then
    echo "  ✗ на страницах есть обращения к посторонним доменам:"
    printf '%s\n' "$FOREIGN" | sed 's/^/      /'
    echo "    Из России такой сайт может не открыться. Если домен нужен —"
    echo "    внесите его в ALLOWED в этом скрипте, осознанно."
    exit 1
fi
echo "  ✓ посторонних доменов нет"

[ -f img/og-cover.jpg ] || { echo "  ✗ нет img/og-cover.jpg — превью ссылок будет пустым"; exit 1; }
echo "  ✓ превью для мессенджеров на месте"

if ! aws_ s3 ls "$S3" >/dev/null 2>&1; then
    echo "  ✗ нет доступа к $S3. Настройте ключи: ./setup-keys.sh"
    exit 1
fi
echo "  ✓ доступ к бакету есть"

echo ""
echo "── Выкладка в $S3 ──────────────────"

# В бакет уезжает только перечисленное. Список разрешённого, а не
# запрещённого: при перечислении исключений любой новый файл рядом уехал бы
# на витрину по умолчанию — так едва не уехал скрипт с настройкой ключей.
STATIC=(--exclude "*" --include "img/*" --include "fonts/*")
PAGES=(--exclude "*" --include "*.html" --include "*.xml" --include "*.txt")

# Картинки, видео и шрифты меняются редко: держим в кеше долго.
aws_ s3 sync ./ "$S3/" $DRY "${STATIC[@]}" \
    --cache-control "public, max-age=31536000, immutable"

# HTML и служебные файлы: короткий кеш, иначе правки не дойдут до людей.
aws_ s3 sync ./ "$S3/" $DRY "${PAGES[@]}" \
    --cache-control "public, max-age=300, must-revalidate"

# Удалить из бакета то, чего больше нет локально.
aws_ s3 sync ./ "$S3/" $DRY --delete \
    --exclude "*" --include "img/*" --include "fonts/*" \
    --include "*.html" --include "*.xml" --include "*.txt"

echo ""
if [ -n "$DRY" ]; then
    echo "Это была примерка. Без --dry-run изменения применятся."
else
    echo "Готово. Проверить: https://$BUCKET"
    echo "Технический адрес, минуя домен: https://$BUCKET.website.yandexcloud.net"
    echo "У страниц кеш 300 секунд — правки появятся в течение пяти минут."
    echo "И обязательно — с мобильного интернета российского оператора, без VPN."
fi
