#!/usr/bin/env bash
# ==========================================================================
#  Сборка архива для macOS. Установщика под Mac нет — только чистый архив с
#  кодом, docker-compose и скриптами запуска; распаковывает и запускает его
#  сам человек (см. local/УСТАНОВКА.md, раздел «Установка, macOS»).
#
#  Результат: ../rubl-director.zip
#
#  Имя папки внутри архива — ровно rubl-director: инструкция называет её по
#  имени («появится папка ~/rubl-director») и командой ditto распаковывает
#  именно в неё.
# ==========================================================================
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(dirname "$here")
stage=$(mktemp -d)
payload="$stage/rubl-director"
trap 'rm -rf "$stage"' EXIT

mkdir -p "$payload"

cd "$root"
# Тот же приём, что и в build.sh для Windows: состав берём из git, а не из
# файловой системы. Так в архив заведомо не попадут ни .env, ни .venv, ни
# node_modules — всё это в .gitignore. scripts добавлен сюда же: без него
# «получить-токен.py» и «показать-филиалы.py» из инструкции просто не
# существовали бы на компьютере, куда архив распаковали.
git ls-files -z backend frontend local scripts assets .env.example .dockerignore \
    | tar --null -cf - -T - \
    | tar -xf - -C "$payload"

# Ключей быть не должно ни в каком виде — та же проверка, что в build.sh.
if find "$payload" -name '.env' -o -name '.env.*' ! -name '.env.example' | grep -q .; then
    echo "В архиве оказался файл настроек — сборка остановлена." >&2
    exit 1
fi

echo "Груз: $(find "$payload" -type f | wc -l) файлов, $(du -sh "$payload" | cut -f1)"

out="$root/rubl-director.zip"
rm -f "$out"
(cd "$stage" && zip -qr "$out" "rubl-director")

echo
ls -lh "$out"
