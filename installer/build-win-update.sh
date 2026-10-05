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
#  Запуск: installer/build-win-update.sh <версия> "<текст ПРОЧТИ МЕНЯ.txt>"
# ==========================================================================
set -euo pipefail

VERSION="${1:?укажите версию, например 9.17.1}"
NOTES="${2:?укажите текст «что нового» вторым аргументом}"

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

out="$root/$name.zip"
rm -f "$out"
(cd "$stage" && zip -qr "$out" "$name")

echo "Груз: $(find "$pkg/app" -type f | wc -l) файлов приложения"
ls -lh "$out"
