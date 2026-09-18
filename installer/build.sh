#!/usr/bin/env bash
# ==========================================================================
#  Сборка установщика для Windows. Запускается на Linux — makensis умеет
#  собирать exe для Windows, поэтому отдельная машина не нужна.
#
#  Нужен пакет nsis:  apt-get install -y nsis
#
#  Результат: ../РублЪ-Директор-Установка.exe
# ==========================================================================
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(dirname "$here")
payload="$here/payload"

if ! command -v makensis >/dev/null 2>&1; then
    echo "makensis не найден. Установите: apt-get install -y nsis" >&2
    exit 1
fi

# Состав payloadа берём из git, а не из файловой системы. Так в установщик
# заведомо не попадут ни .env, ни .venv, ни node_modules: всё это в
# .gitignore. Один раз собранный «по маске» архив уже увозил чужие файлы —
# больше так не делаем.
rm -rf "$payload"
mkdir -p "$payload"

cd "$root"
git ls-files -z backend frontend local assets .env.example .dockerignore \
    | tar --null -cf - -T - \
    | tar -xf - -C "$payload"

# Ключей быть не должно ни в каком виде. Проверка дешёвая, а цена промаха —
# рабочие токены YCLIENTS внутри файла, который уедет на чужой компьютер.
if find "$payload" -name '.env' -o -name '.env.*' ! -name '.env.example' | grep -q .; then
    echo "В payloadе оказался файл настроек — сборка остановлена." >&2
    exit 1
fi

echo "Груз: $(find "$payload" -type f | wc -l) файлов, $(du -sh "$payload" | cut -f1)"

cd "$here"
# Локаль обязательна. В POSIX-локали makensis падает с segmentation fault,
# как только доходит до файла с кириллицей в имени (frontend/src/мастера.tsx).
LC_ALL=C.UTF-8 makensis -V2 -WX installer.nsi

echo
ls -lh "$root"/*.exe
