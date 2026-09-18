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

# Незакоммиченные правки в уже отслеживаемых файлах — не должно быть на
# рабочей копии, но если есть, лучше остановиться и сказать прямо, чем
# затереть их слиянием. Файлы, которых git вообще не знает (--untracked-files=no),
# сюда не в счёт: pull их не трогает, они не в счёт риска.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "  ✗ В отслеживаемых файлах есть несохранённые правки — обновление"
    echo "    остановлено, чтобы их не потерять. Обратитесь к разработчику."
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
    # Имя переменной — латиницей: bash не принимает кириллицу в идентификаторах
    # ни при какой локали, это синтаксис языка, а не вопрос кодировки.
    COMMITS_COUNT=$(git rev-list --count "$LOCAL..$REMOTE")
    echo "  ✓ Обновлено: $COMMITS_COUNT коммит(ов), теперь $(git rev-parse --short HEAD)"
fi

echo ""
"$ROOT/local/start.sh"
