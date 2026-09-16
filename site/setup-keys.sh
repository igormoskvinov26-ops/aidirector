#!/usr/bin/env bash
# ==========================================================================
#  Настройка доступа к Yandex Object Storage для выкладки сайта.
#
#      ./setup-keys.sh
#
#  Скрипт спросит ключи сам: так они не попадают в историю команд, и не важно,
#  как читает ввод ваша оболочка (у bash и zsh это разные флаги).
#
#  Ключи берутся в консоли Yandex Cloud: Сервисные аккаунты → нужный аккаунт →
#  Создать новый ключ → Создать статический ключ доступа. Достаточно роли
#  storage.editor. Секрет показывают ОДИН раз, в окне создания: закрыли окно —
#  восстановить нельзя, только выпускать новый ключ.
#
#  Настройки пишутся в отдельный профиль "rubl", чужие профили AWS не
#  затрагиваются.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"

BUCKET="${BUCKET:-rublbarber.ru}"
PROFILE="${AWS_PROFILE_NAME:-rubl}"
ENDPOINT="https://storage.yandexcloud.net"

if ! command -v aws >/dev/null; then
    echo "Нет команды aws. Установить:"
    echo "    uv tool install awscli"
    echo "Затем откройте терминал заново и повторите."
    exit 1
fi

if [ -z "${YC_KEY_ID:-}" ]; then
    printf 'Ключи сервисного аккаунта Yandex Cloud.\n'
    printf 'Вводятся вслепую — на экране ничего не появится, это нормально.\n\n'
    read -r -s -p "Идентификатор ключа (YCAJE...): " YC_KEY_ID || true; echo
fi
if [ -z "${YC_SECRET:-}" ]; then
    read -r -s -p "Секретный ключ: " YC_SECRET || true; echo
fi

# Пробелы и переводы строк цепляются при копировании незаметно, а подпись
# запроса от них разъезжается.
YC_KEY_ID="$(printf '%s' "$YC_KEY_ID" | tr -d '[:space:]')"
YC_SECRET="$(printf '%s' "$YC_SECRET" | tr -d '[:space:]')"

[ -n "$YC_KEY_ID" ] || { echo "Идентификатор ключа не введён."; exit 1; }
[ -n "$YC_SECRET" ] || { echo "Секретный ключ не введён."; exit 1; }

case "$YC_SECRET" in
    YCAJE*) echo ""
            echo "Похоже, значения перепутаны: секрет начинается на YCAJE, а так"
            echo "начинается идентификатор ключа. Запустите скрипт заново."
            exit 1 ;;
esac

aws configure set aws_access_key_id     "$YC_KEY_ID" --profile "$PROFILE"
aws configure set aws_secret_access_key "$YC_SECRET" --profile "$PROFILE"
aws configure set region                ru-central1  --profile "$PROFILE"
# Точка в имени бакета несовместима с адресацией через поддомен: имя
# rublbarber.ru.storage.yandexcloud.net не покрывается сертификатом
# *.storage.yandexcloud.net. Нужна адресация через путь.
aws configure set s3.addressing_style   path         --profile "$PROFILE"

echo ""
echo "✓ Профиль $PROFILE записан"
echo "  Проверка доступа к s3://$BUCKET:"

if aws --profile "$PROFILE" --endpoint-url "$ENDPOINT" s3 ls "s3://$BUCKET" >/dev/null 2>&1; then
    echo "    ✓ бакет доступен. Дальше: ./deploy.sh --dry-run"
    exit 0
fi

echo "    ✗ не вышло. Что ответил сервер:"
# Без || true конвейер вернёт код ошибки от aws, pipefail его пропустит
# наружу, и set -e оборвёт скрипт ровно перед подсказкой — то есть перед
# единственным, ради чего мы сюда попали.
aws --profile "$PROFILE" --endpoint-url "$ENDPOINT" s3 ls "s3://$BUCKET" 2>&1 \
    | sed 's/^/      /' || true
cat <<'ПОДСКАЗКА'

  SignatureDoesNotMatch — ключ недействителен. Так отвечают и на неверный
    секрет, и на удалённый ключ, и на выдуманный: по тексту их не различить.
    Выпустите новый статический ключ и скопируйте оба значения, НЕ закрывая
    окно создания — секрет показывают только там и только один раз.
  AccessDenied — ключ настоящий, но прав на бакет нет. Проверьте, что у
    сервисного аккаунта роль storage.editor в том же каталоге, где бакет.
  NoSuchBucket — бакета с таким именем нет в этом облаке.
ПОДСКАЗКА
exit 1
