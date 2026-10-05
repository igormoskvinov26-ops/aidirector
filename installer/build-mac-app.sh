#!/usr/bin/env bash
# ==========================================================================
#  Сборка «РублЪ Директор.app» для macOS — тот же формат, что у вендора:
#  .app сам при каждом запуске rsync'ит свой Resources/app в рабочую копию
#  (~/Library/Application Support/РублЪ Директор), исключая .env/output/log.
#  Поэтому обновление — это просто «заменить программу в Программах»:
#  никакого отдельного update-пакета для Mac не нужно, в отличие от Windows.
#
#  Собирается полностью на Linux — .app это просто папка со строгой
#  структурой, подписи Apple нет (см. ПРОЧТИ МЕНЯ.txt про карантин).
#
#  Результат: ../РублЪ-Директор-<версия>-macOS.zip
#
#  Запуск: installer/build-mac-app.sh <версия> "<текст ПРОЧТИ МЕНЯ.txt>"
# ==========================================================================
set -euo pipefail

VERSION="${1:?укажите версию, например 9.17.1}"
NOTES="${2:?укажите текст «что нового» вторым аргументом}"

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(dirname "$here")
name="РублЪ-Директор-$VERSION-macOS"
stage=$(mktemp -d)
pkg="$stage/$name"
app="$pkg/РублЪ Директор.app"
trap 'rm -rf "$stage"' EXIT

mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/app"

cd "$root"
git ls-files -z backend frontend local scripts assets .env.example .dockerignore \
    | tar --null -cf - -T - \
    | tar -xf - -C "$app/Contents/Resources/app"

if find "$app/Contents/Resources/app" -name '.env' -o -name '.env.*' ! -name '.env.example' | grep -q .; then
    echo "В payloadе оказался файл настроек — сборка остановлена." >&2
    exit 1
fi

cat > "$app/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>РублЪ Директор</string>
    <key>CFBundleDisplayName</key>     <string>РублЪ Директор</string>
    <key>CFBundleIdentifier</key>      <string>ru.rublbarber.director</string>
    <key>CFBundleVersion</key>         <string>$VERSION</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleExecutable</key>      <string>Директор</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleSignature</key>       <string>????</string>
    <key>LSMinimumSystemVersion</key>  <string>11.0</string>
    <key>NSHighResolutionCapable</key> <true/>
    <!-- Окно не нужно: программа показывает себя в браузере, а ход установки
         в Терминале. Значок в Dock при этом остаётся. -->
    <key>LSBackgroundOnly</key>        <false/>
</dict>
</plist>
PLIST

printf 'APPL????' > "$app/Contents/PkgInfo"

cat > "$app/Contents/MacOS/Директор" << LAUNCHER
#!/bin/bash
# ==========================================================================
#  «РублЪ Директор» — запуск на macOS.
#
#  Лежит внутри РублЪ Директор.app и вызывается двойным щелчком. Делает то
#  же, что установщик на Windows: раскладывает файлы, поднимает Docker,
#  собирает образ, накатывает миграции и открывает окно в браузере.
#
#  Рабочая копия живёт отдельно от программы:
#      ~/Library/Application Support/РублЪ Директор
#  Так сделано не для красоты: .app может лежать в /Applications, куда
#  обычному пользователю писать нельзя, а Директору нужно хранить рядом с
#  собой файл настроек и журнал обзвона. При обновлении программы рабочая
#  копия переписывается, но .env и output остаются нетронутыми.
# ==========================================================================
set -uo pipefail

VERSION="$VERSION"
APPFILES="\$(cd "\$(dirname "\$0")/../Resources/app" && pwd)"
WORKDIR="\$HOME/Library/Application Support/РублЪ Директор"

# Первый запуск дольше остальных, и человек должен видеть, что идёт работа,
# а не смотреть на неподвижный значок. Поэтому вся установка показывается в
# окне Терминала: .app сам по себе ничего на экран не выводит.
if [ "\${DIRECTOR_IN_TERMINAL:-}" != "1" ]; then
    osascript <<OSA >/dev/null 2>&1
tell application "Terminal"
    activate
    do script "DIRECTOR_IN_TERMINAL=1 '\$0'"
end tell
OSA
    exit 0
fi

echo "════════════════════════════════════════════════════"
echo "  РублЪ Директор \$VERSION"
echo "════════════════════════════════════════════════════"
echo ""

# ── Docker ────────────────────────────────────────────────────────────────
. "\$APPFILES/local/docker-path.sh" 2>/dev/null || true

if ! command -v docker >/dev/null 2>&1; then
    echo "  ✗ Docker Desktop не установлен."
    echo ""
    echo "    Без него Директор не работает — он в нём и живёт."
    echo "    Поставьте: https://www.docker.com/products/docker-desktop/"
    echo "    Потом запустите Директора ещё раз."
    echo ""
    read -r -p "  Нажмите Enter, чтобы закрыть окно. " _
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "  · Docker установлен, но не запущен — открываю…"
    open -a Docker 2>/dev/null || true
    for _ in \$(seq 1 120); do
        sleep 5
        docker info >/dev/null 2>&1 && break
    done
fi

if ! docker info >/dev/null 2>&1; then
    echo "  ✗ Docker не поднялся за десять минут."
    echo "    Откройте Docker Desktop вручную и запустите Директора снова."
    echo ""
    read -r -p "  Нажмите Enter, чтобы закрыть окно. " _
    exit 1
fi
echo "  ✓ Docker работает"

# ── Рабочая копия ─────────────────────────────────────────────────────────
FIRST_RUN=0
[ -d "\$WORKDIR/local" ] || FIRST_RUN=1
mkdir -p "\$WORKDIR"

# Код обновляем всегда, настройки и журнал обзвона — никогда: в них ключи и
# данные, которых больше нигде нет.
rsync -a --delete \\
    --exclude='.env' \\
    --exclude='output/' \\
    --exclude='log/' \\
    "\$APPFILES/" "\$WORKDIR/"
echo "  ✓ файлы на месте: \$WORKDIR"

# ── Настройки ─────────────────────────────────────────────────────────────
# Файл настроек создаётся сам, и человека ни о чём не спрашивают: в нём
# только адрес базы и пароль к ней, а это не его забота. Ключи YCLIENTS и
# Telegram задаются в самом Директоре, в разделе «Настройки → Интеграции».
if [ ! -f "\$WORKDIR/.env" ]; then
    PASS=\$(openssl rand -hex 24)
    cat > "\$WORKDIR/.env" <<ENVEOF
# Создан автоматически при установке. Ключи YCLIENTS и Telegram задаются
# в самом Директоре: «Настройки → Интеграции».
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rubl_director
POSTGRES_USER=rubl
POSTGRES_PASSWORD=\$PASS
APP_PORT=8000
DEBUG=false
ENVEOF
    chmod 600 "\$WORKDIR/.env"
    echo "  ✓ настройки созданы"
else
    if grep -qE '^[A-Z_]+=<' "\$WORKDIR/.env"; then
        sed -i.bak -E '/^[A-Z_]+=</d' "\$WORKDIR/.env"
        echo "  ✓ незаполненные заготовки убраны"
    fi
    if ! grep -qE '^POSTGRES_PASSWORD=.+' "\$WORKDIR/.env"; then
        PASS=\$(openssl rand -hex 24)
        sed -i.bak -E '/^POSTGRES_PASSWORD=/d' "\$WORKDIR/.env"
        printf 'POSTGRES_PASSWORD=%s\n' "\$PASS" >> "\$WORKDIR/.env"
        echo "  ✓ пароль базы сгенерирован"
    fi
    echo "  ✓ настройки на месте"
fi

# ── Запуск ────────────────────────────────────────────────────────────────
echo ""
if [ "\$FIRST_RUN" = "1" ]; then
    echo "  Первый запуск: Docker собирает образ. Это 5–15 минут,"
    echo "  дальше секунды. Окно можно не трогать."
else
    echo "  Запускаю…"
fi
echo ""

if bash "\$WORKDIR/local/start.sh"; then
    echo ""
    echo "  ✓ Директор работает."
    echo "    Окно откроется само. Если нет — http://localhost:8000"

    SETUP_CODE="\$WORKDIR/output/setup-code.txt"
    if [ -f "\$SETUP_CODE" ]; then
        echo ""
        echo "  ┌──────────────────────────────────────────────┐"
        echo "  │  Директор ещё не настроен.                   │"
        echo "  │  В окне попросят код — вот он:               │"
        echo "  │                                              │"
        printf "  │            %s                        │\n" "\$(cat "\$SETUP_CODE")"
        echo "  │                                              │"
        echo "  │  Дальше придумайте себе логин и пароль.      │"
        echo "  └──────────────────────────────────────────────┘"
    fi
    echo ""
    echo "  Это окно можно закрыть."
else
    echo ""
    echo "  ✗ Запуск не удался — что именно, видно выше."
    read -r -p "  Нажмите Enter, чтобы закрыть окно. " _
    exit 1
fi
LAUNCHER
chmod +x "$app/Contents/MacOS/Директор"

cat > "$pkg/Установка.command" << 'INSTALLCMD'
#!/bin/bash
# ==========================================================================
#  «РублЪ Директор» — установка на macOS.
#
#  Зачем этот файл. У сборки нет подписи Apple: она стоит 99 $ в год и к
#  работе программы отношения не имеет. Без подписи macOS вешает на всё
#  скачанное метку «карантин» и отказывается открывать — то самое окно
#  «Apple could not verify… is free of malware».
#
#  Метка снимается одной командой, и делает это данный файл: снимает
#  карантин с папки, кладёт программу в «Программы» и запускает её.
#
#  Запускается двумя способами — двойным щелчком либо из Терминала
#  («bash », перетащить файл, Enter). Второй способ работает всегда:
#  Терминал, запуская скрипт напрямую, карантин не проверяет.
# ==========================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/РублЪ Директор.app"
DEST="/Applications/РублЪ Директор.app"

echo "════════════════════════════════════════════════════"
echo "  РублЪ Директор — установка"
echo "════════════════════════════════════════════════════"
echo ""

if [ ! -d "$APP" ]; then
    echo "  ✗ Рядом нет «РублЪ Директор.app»."
    echo "    Распакуйте архив целиком и запустите файл из той же папки."
    echo ""
    read -r -p "  Нажмите Enter, чтобы закрыть окно. " _
    exit 1
fi

echo "  · снимаю метку карантина…"
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null || true

if [ -d "$DEST" ]; then
    echo "  · в «Программах» уже есть Директор — заменяю на новую версию"
    rm -rf "$DEST"
fi

if cp -R "$APP" "$DEST" 2>/dev/null; then
    xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
    echo "  ✓ программа в «Программах»"
    TARGET="$DEST"
else
    echo "  · в «Программы» скопировать не вышло — оставляю на месте"
    TARGET="$APP"
fi

if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "РублЪ Директор.app"; then
    defaults write com.apple.dock persistent-apps -array-add \
        "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$TARGET</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>" \
        2>/dev/null && killall Dock 2>/dev/null
    echo "  ✓ значок добавлен в Dock"
fi

if ! ls "$HOME/Desktop/"РублЪ\ Директор* >/dev/null 2>&1; then
    osascript -e "tell application \"Finder\" to make alias file to (POSIX file \"$TARGET\") at (path to desktop folder)" \
        >/dev/null 2>&1 && echo "  ✓ ярлык на рабочем столе"
fi

echo ""
echo "  Запускаю. Дальше Директор открывается ярлыком на рабочем"
echo "  столе или значком в Dock; этот файл больше не нужен."
echo ""

open "$TARGET"
sleep 2
INSTALLCMD
chmod +x "$pkg/Установка.command"

cat > "$pkg/ПРОЧТИ МЕНЯ.txt" << TXT
РублЪ Директор $VERSION — установка/обновление на macOS
═══════════════════════════════════════════════════════════

Что нового:
$NOTES

ШАГ 1. Docker Desktop

  Если его ещё нет — поставьте:
  https://www.docker.com/products/docker-desktop/
  Директор работает внутри него.


ШАГ 2. Запустите «Установка.command» из этой папки

  Двойным щелчком.

  Если macOS ответит, что не может проверить программу, —
  это не поломка. У сборки нет подписи Apple: она стоит
  99 \$ в год и к работе программы отношения не имеет.
  Обходится за десять секунд, любым из двух способов.

  Способ А — через Терминал (работает всегда)
    1. Launchpad → Другие → Терминал (или Cmd+Пробел, «Терминал»)
    2. Наберите «bash » (с пробелом в конце)
    3. Перетащите «Установка.command» в окно Терминала
    4. Enter

  Способ Б — через настройки системы
    Системные настройки → Конфиденциальность и безопасность →
    внизу «РублЪ Директор» заблокирован → «Открыть всё равно».


ШАГ 3. Готово

  Настройки, база и журнал обзвона с прошлой версии не
  тронутся — программа сама подхватывает их при запуске.
  Обновление делается так же: замените программу в
  «Программах» этой папкой.

  Где что лежит:
    ~/Library/Application Support/РублЪ Директор
TXT

out="$root/$name.zip"
rm -f "$out"
(cd "$stage" && zip -qr "$out" "$name")

echo "Груз: $(find "$app/Contents/Resources/app" -type f | wc -l) файлов приложения"
ls -lh "$out"
