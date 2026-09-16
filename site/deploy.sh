#!/usr/bin/env bash
# ==========================================================================
#  Выкладка сайта rublbarber.ru в Yandex Object Storage
#
#     ./deploy.sh            — выложить
#     ./deploy.sh --dry-run  — показать, что изменится, ничего не трогая
#
#  Требуется s3cmd и файл ~/.s3cfg с ключами сервисного аккаунта.
#  Настройка ключей — в README.md рядом.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"

BUCKET="${BUCKET:-rublbarber.ru}"
S3="s3://$BUCKET"
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY="--dry-run"

command -v s3cmd >/dev/null || { echo "Нет s3cmd. Установить: pip install s3cmd"; exit 1; }
[ -f ~/.s3cfg ] || { echo "Нет ~/.s3cfg с ключами. См. README.md"; exit 1; }

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

echo ""
echo "── Выкладка в $S3 ──────────────────"

# Картинки, видео и шрифты меняются редко: держим в кеше долго.
s3cmd sync $DRY --acl-public --no-mime-magic --guess-mime-type \
    --add-header="Cache-Control:public, max-age=31536000, immutable" \
    --exclude="*" --include="img/*" --include="fonts/*" \
    ./ "$S3/"

# HTML и служебные файлы: короткий кеш, иначе правки не дойдут до людей.
s3cmd sync $DRY --acl-public --no-mime-magic --guess-mime-type \
    --add-header="Cache-Control:public, max-age=300, must-revalidate" \
    --exclude="*" --include="*.html" --include="*.xml" --include="*.txt" \
    ./ "$S3/"

# Удалить из бакета то, чего больше нет локально.
#
# Список разрешённого, а не запрещённого: при перечислении исключений любой
# новый файл рядом уезжает в публичный бакет по умолчанию. Так и вышло бы с
# setup-s3cfg.sh — служебный скрипт открылся бы по адресу сайта.
s3cmd sync $DRY --acl-public --delete-removed \
    --exclude="*" \
    --include="img/*" --include="fonts/*" \
    --include="*.html" --include="*.xml" --include="*.txt" \
    ./ "$S3/"

echo ""
if [ -n "$DRY" ]; then
    echo "Это была примерка. Без --dry-run изменения применятся."
else
    echo "Готово. Проверить: https://$BUCKET.website.yandexcloud.net"
    echo "И обязательно — с мобильного интернета российского оператора, без VPN."
fi
