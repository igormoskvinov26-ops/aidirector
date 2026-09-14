#!/usr/bin/env bash
# Остановить Директора. Данные остаются на месте — при следующем запуске
# всё будет как было.
set -euo pipefail
cd "$(dirname "$0")"
docker compose --env-file ../.env down
echo "Директор остановлен. Данные сохранены."
