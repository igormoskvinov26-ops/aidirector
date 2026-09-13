#!/usr/bin/env bash
# ==========================================================================
#  Создаёт ~/.s3cfg с ключами сервисного аккаунта Yandex Cloud.
#
#  Ключи передаются через переменные окружения, чтобы не остаться
#  в истории команд:
#
#      read -s -p "Key ID: "  YC_KEY_ID  && echo
#      read -s -p "Secret: "  YC_SECRET  && echo
#      export YC_KEY_ID YC_SECRET
#      ./setup-s3cfg.sh
#
#  Где взять ключи: консоль → Сервисные аккаунты → нужный аккаунт →
#  Создать новый ключ → Создать статический ключ доступа.
#
#  Про host_bucket: намеренно указан тот же адрес, что и host_base, —
#  это адресация вида storage.yandexcloud.net/имя-бакета/файл.
#  Обычный для S3 вариант имя-бакета.storage.yandexcloud.net здесь не
#  работает: в имени нашего бакета есть точка, и такое имя не покрывается
#  сертификатом *.storage.yandexcloud.net — соединение рвётся на проверке
#  сертификата. Не «упрощайте» эту строку обратно.
# ==========================================================================
set -euo pipefail

: "${YC_KEY_ID:?не задан YC_KEY_ID — идентификатор статического ключа}"
: "${YC_SECRET:?не задан YC_SECRET — секретный ключ}"

umask 077
cat > ~/.s3cfg <<CFG
[default]
access_key = $YC_KEY_ID
secret_key = $YC_SECRET
host_base = storage.yandexcloud.net
host_bucket = storage.yandexcloud.net
bucket_location = ru-central1
use_https = True
signature_v2 = False
CFG
chmod 600 ~/.s3cfg

echo "✓ ~/.s3cfg записан, права 600"
echo "  Проверка доступа:"
s3cmd ls 2>&1 | sed 's/^/    /'
