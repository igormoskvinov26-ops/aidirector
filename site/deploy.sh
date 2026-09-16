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

if grep -qE "fonts\.googleapis|fonts\.gstatic|cdn\.jsdelivr|unpkg\.com" index.html privacy.html 404.html; then
    echo "  ✗ на страницах есть внешние ресурсы — сайт не откроется из России"
    grep -nE "fonts\.googleapis|fonts\.gstatic|cdn\.jsdelivr|unpkg\.com" index.html privacy.html 404.html
    exit 1
fi
echo "  ✓ внешних зависимостей нет"

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
    echo "Готово. Проверить: https://$BUCKET.website.yandexcloud.net"
    echo "И обязательно — с мобильного интернета российского оператора, без VPN."
fi
