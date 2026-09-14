#!/usr/bin/env bash
# Двойной щелчок по этому файлу запускает Директора на Mac.
cd "$(dirname "$0")"
./start.sh
echo ""
echo "Окно можно закрыть."
read -r -p "Нажмите Enter..."
