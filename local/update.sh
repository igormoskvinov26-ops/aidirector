#!/usr/bin/env bash
# ==========================================================================
#  Обновление Директора до последней версии кода и перезапуск.
#
#  Запускать из Терминала: ./local/update.sh
#  Тянет текущую ветку из origin и перезапускает через start.sh — тот же
#  docker compose up -d --build, что подхватывает новый код и применяет
#  миграции базы.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
cd "$ROOT"

echo "── Обновление ────────────────────────────────────"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  ✗ Это не git-репозиторий. Обновление скриптом здесь невозможно."
    exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" = "HEAD" ]; then
    echo "  ✗ Репозиторий не на ветке (отсоединённый HEAD)."
    echo "    Обратитесь к разработчику."
    exit 1
fi
echo "  Ветка: $BRANCH"

# Несохранённые правки — не должно быть на рабочей копии, но если есть,
# лучше остановиться и сказать прямо, чем затереть их слиянием.
if [ -n "$(git status --porcelain)" ]; then
    echo "  ✗ В папке есть несохранённые изменения — обновление остановлено,"
    echo "    чтобы их не потерять. Обратитесь к разработчику."
    exit 1
fi

if ! git fetch origin "$BRANCH"; then
    echo "  ✗ Не удалось получить обновления. Проверьте интернет."
    exit 1
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "  ✓ Уже последняя версия ($(git rev-parse --short HEAD))"
else
    if ! git merge --ff-only "origin/$BRANCH"; then
        echo "  ✗ Обновить одним движением не вышло — история разошлась."
        echo "    Обратитесь к разработчику."
        exit 1
    fi
    КОММИТОВ=$(git rev-list --count "$LOCAL..$REMOTE")
    echo "  ✓ Обновлено: $КОММИТОВ коммит(ов), теперь $(git rev-parse --short HEAD)"
fi

echo ""
"$ROOT/local/start.sh"
