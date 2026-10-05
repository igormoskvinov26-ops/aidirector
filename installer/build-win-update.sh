#!/usr/bin/env bash
# ==========================================================================
#  Лёгкий пакет обновления для Windows — не установщик, а то, чем вендор
#  распространяет патчи на уже установленного «Директора» (программа в
#  окне называется «Пульт»): app/ + Обновить-Директор.bat + ПРОЧТИ МЕНЯ.txt.
#
#  Обновить-Директор.bat копирует app/ поверх %LOCALAPPDATA%\RublDirector\app
#  через robocopy с /XF .env — файл настроек, база и output не трогаются.
#
#  Результат: ../РублЪ-Директор-<версия>-обновление.zip
#
#  Запуск: installer/build-win-update.sh <версия> "<текст ПРОЧТИ МЕНЯ.txt>" \
#              [top-логин] [top-пароль]
#
#  Последние два аргумента — по желанию. Если заданы, в пакет кладётся
#  временный файл app/backend/top-seed.env: приложение при первом же старте
#  после обновления само заводит отдельную учётную запись top (Владельца) и
#  стирает файл изнутри контейнера; .bat дочищает его копию на диске. Если
#  top на этой установке уже заведён — файл просто игнорируется и удаляется.
# ==========================================================================
set -euo pipefail

VERSION="${1:?укажите версию, например 9.17.1}"
NOTES="${2:?укажите текст «что нового» вторым аргументом}"
TOP_LOGIN="${3:-}"
TOP_PASSWORD="${4:-}"

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(dirname "$here")
name="РублЪ-Директор-$VERSION-обновление"
stage=$(mktemp -d)
pkg="$stage/$name"
trap 'rm -rf "$stage"' EXIT

mkdir -p "$pkg/app"

cd "$root"
git ls-files -z backend frontend local scripts assets .env.example .dockerignore \
    | tar --null -cf - -T - \
    | tar -xf - -C "$pkg/app"

if find "$pkg/app" -name '.env' -o -name '.env.*' ! -name '.env.example' | grep -q .; then
    echo "В payloadе оказался файл настроек — сборка остановлена." >&2
    exit 1
fi

if [ -n "$TOP_LOGIN" ] && [ -n "$TOP_PASSWORD" ]; then
    printf 'LOGIN=%s\nPASSWORD=%s\n' "$TOP_LOGIN" "$TOP_PASSWORD" > "$pkg/app/backend/top-seed.env"
    echo "Добавлен top-seed.env для автозаведения top ($TOP_LOGIN)."
fi

cat > "$pkg/Обновить-Директор.bat" << BAT
@echo off
chcp 65001 >nul
rem ========================================================================
rem  Обновление РублЪ Директор до $VERSION (программа в окне называется «Пульт»).
rem  Копирует новые файлы поверх установленных. Ваш .env, база, логины и
rem  папка output не затрагиваются. Затем запускает ту же фоновую сборку,
rem  что и установщик.
rem ========================================================================
set "TARGET=%LOCALAPPDATA%\RublDirector"
if not exist "%TARGET%\bootstrap.ps1" (
  echo Директор не найден в %TARGET%.
  echo Сначала поставьте полный установщик, потом запустите это обновление.
  pause
  exit /b 1
)
echo Копирую файлы в %TARGET%\app ...
robocopy "%~dp0app" "%TARGET%\app" /E /XD node_modules .venv __pycache__ output .git /XF .env /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 (
  echo Не удалось скопировать файлы. Код %ERRORLEVEL%.
  pause
  exit /b 1
)
echo Собираю и запускаю Директора. Первый раз это занимает несколько минут ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%\bootstrap.ps1" -Mode install
rem top-seed.env приложение уже прочитало и стёрло внутри контейнера при
rem старте — эта копия на диске здесь больше не нужна.
if exist "%TARGET%\app\backend\top-seed.env" del /f /q "%TARGET%\app\backend\top-seed.env"
echo.
echo Готово, если выше нет ошибок. Откройте Директор ярлыком как обычно.
echo Журнал: %TARGET%\log\bootstrap.log
pause
BAT

cat > "$pkg/ПРОЧТИ МЕНЯ.txt" << TXT
Обновление до $VERSION

1. Распакуйте архив.
2. Дважды щёлкните «Обновить-Директор.bat».
3. Дождитесь «Готово».

Что нового:
$NOTES

Ваш .env, логины и база не меняются.
TXT

if [ -n "$TOP_LOGIN" ] && [ -n "$TOP_PASSWORD" ]; then
    cat >> "$pkg/ПРОЧТИ МЕНЯ.txt" << TXT2

Прежний вход владельца станет Управляющим (логин/пароль те же, доступ
ограничен). Полный доступ — по отдельной учётной записи, заведётся сама
при этом обновлении.
TXT2
fi

out="$root/$name.zip"
rm -f "$out"
(cd "$stage" && zip -qr "$out" "$name")

echo "Груз: $(find "$pkg/app" -type f | wc -l) файлов приложения"
ls -lh "$out"
