#!/usr/bin/env bash
# ==========================================================================
#  Разбор отказа в доступе к Yandex Object Storage.
#
#      ./check-access.sh
#
#  Печатает всё, что нужно, чтобы понять причину, и ничего секретного:
#  только длины ключей и первые символы. Вывод можно показывать.
# ==========================================================================
set -uo pipefail
cd "$(dirname "$0")"

BUCKET="${BUCKET:-rublbarber.ru}"
PROFILE="${AWS_PROFILE_NAME:-rubl}"
ENDPOINT="https://storage.yandexcloud.net"

echo "=================================================================="
echo " 1. ЧАСЫ"
echo "=================================================================="
# Подпись запроса привязана ко времени. Расхождение с сервером больше
# четверти часа — и она не сойдётся, как бы ни были верны ключи.
SERVER_DATE=$(curl -sI --max-time 20 "$ENDPOINT/" 2>/dev/null | awk -F': ' 'tolower($1)=="date"{print $2}' | tr -d '\r')
echo "  на компьютере: $(date -u '+%a, %d %b %Y %H:%M:%S GMT')"
if [ -n "$SERVER_DATE" ]; then
    echo "  у Яндекса:     $SERVER_DATE"
    LOCAL_S=$(date -u +%s)
    # -u обязателен: без него BSD-шный date на макоси читает строку как
    # местное время и молча игнорирует GMT в формате. В Москве это давало
    # ровно три часа мнимого расхождения и обвиняло исправные часы.
    if SERVER_S=$(date -j -u -f "%a, %d %b %Y %H:%M:%S GMT" "$SERVER_DATE" +%s 2>/dev/null) \
       || SERVER_S=$(date -u -d "$SERVER_DATE" +%s 2>/dev/null); then
        DIFF=$(( LOCAL_S - SERVER_S )); [ "$DIFF" -lt 0 ] && DIFF=$(( -DIFF ))
        echo "  расхождение:   $DIFF с"
        if [ "$DIFF" -gt 300 ]; then
            echo "  ✗ ЭТО МНОГО. Часы сбиты — подпись из-за этого и не сходится."
            echo "    Лечится так:  sudo sntp -sS time.apple.com"
        else
            echo "  ✓ часы в порядке, дело не в них"
        fi
    fi
else
    echo "  ✗ Яндекс не ответил. Проверьте интернет."
fi

echo ""
echo "=================================================================="
echo " 2. КЛЮЧИ В ПРОФИЛЕ $PROFILE"
echo "=================================================================="
KEY=$(aws configure get aws_access_key_id     --profile "$PROFILE" 2>/dev/null || true)
SEC=$(aws configure get aws_secret_access_key --profile "$PROFILE" 2>/dev/null || true)
printf '  идентификатор: длина %d, начало %s\n' "${#KEY}" "$(printf '%s' "$KEY" | cut -c1-5)"
printf '  секрет:        длина %d, начало %s\n' "${#SEC}" "$(printf '%s' "$SEC" | cut -c1-5)"
echo "  ожидается:     идентификатор 25 знаков YCAJE..., секрет 40 знаков"

echo ""
echo "=================================================================="
echo " 3. ОТВЕЧАЕТ ЛИ БАКЕТ БЕЗ КЛЮЧЕЙ"
echo "=================================================================="
# Если бакета нет или он в другом облаке, ответ будет иным, чем при
# работающем бакете с закрытым списком объектов.
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$ENDPOINT/$BUCKET/" 2>/dev/null || echo "нет")
echo "  GET $ENDPOINT/$BUCKET/  ->  $CODE"
case "$CODE" in
    403) echo "  ✓ бакет существует, список объектов закрыт — так и настроено" ;;
    200) echo "  ✓ бакет существует и список открыт" ;;
    404) echo "  ✗ бакета с таким именем нет в этом облаке" ;;
    *)   echo "  ? неожиданный ответ" ;;
esac

echo ""
echo "=================================================================="
echo " 4. ЗАПРОС С КЛЮЧАМИ"
echo "=================================================================="
# Отладочный вывод нужен ровно ради одной строки — области подписи.
# Саму ошибку берём из обычного запуска, иначе её не найти в потоке.
SCOPE=$(aws --profile "$PROFILE" --endpoint-url "$ENDPOINT" s3api list-objects-v2 \
        --bucket "$BUCKET" --max-items 1 --debug 2>&1 \
        | grep -o 'Credential=[^,]*' | head -1 || true)
[ -n "$SCOPE" ] && echo "  область подписи: $SCOPE"

ERR=$(aws --profile "$PROFILE" --endpoint-url "$ENDPOINT" s3api list-objects-v2 \
        --bucket "$BUCKET" --max-items 1 2>&1 || true)
echo "  ответ сервера:"
if printf '%s' "$ERR" | grep -q "An error occurred"; then
    printf '%s' "$ERR" | grep "An error occurred" | head -1 | sed 's/^/    /'
else
    echo "    ✓ ОТКАЗА НЕТ — доступ есть, можно выкладывать"
fi

echo ""
echo "=================================================================="
echo " ЧТО ЭТО ЗНАЧИТ"
echo "=================================================================="
echo "  Часы разошлись        -> поправить время, повторить"
echo "  Бакет ответил 404     -> ключ от другого облака, либо имя не то"
echo "  Всё выше в порядке, а SignatureDoesNotMatch остаётся"
echo "                        -> секрет не подходит к этому идентификатору"
