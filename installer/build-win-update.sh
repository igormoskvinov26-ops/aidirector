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

# bootstrap.ps1 в пакет НЕ кладётся. На машинах стоит версия поставщика из
# полного установщика — она новее той, что в этом репозитории (в ней есть,
# например, согласование пароля базы с .env, которое отрабатывает на каждой
# установке). 9.17.7–9.17.11 затирали её здешней копией, и обновление
# перестало проходить (журнал владельца, 25.11.2026). Пока здешний
# bootstrap.ps1 не сверен с поставщицким, обновление его не трогает, а .bat
# ниже возвращает оригинал из резервной копии, если его успели заменить.

# Снятие диагностики — тоже рядом с app/, тоже обновляется каждый раз.
# Работает независимо от того, запускается ли сам Директор.
cp "$here/run-diagnostics.ps1" "$pkg/run-diagnostics.ps1"
cp "$here/Собрать-Диагностику.bat" "$pkg/Собрать-Диагностику.bat"

if find "$pkg/app" -name '.env' -o -name '.env.*' ! -name '.env.example' | grep -q .; then
    echo "В payloadе оказался файл настроек — сборка остановлена." >&2
    exit 1
fi

if [ -n "$TOP_LOGIN" ] && [ -n "$TOP_PASSWORD" ]; then
    printf 'LOGIN=%s\nPASSWORD=%s\n' "$TOP_LOGIN" "$TOP_PASSWORD" > "$pkg/app/backend/top-seed.env"
    echo "Добавлен top-seed.env для автозаведения top ($TOP_LOGIN)."
fi

# Обновить-Директор.bat. Устроен по образцу того, что два месяца работало
# (до 9.17.7): robocopy файлов и РОВНО ОДИН вызов PowerShell — bootstrap.ps1
# -Mode install. Всё, что добавлено сверху, — чистый batch, без PowerShell:
#
#  1. Возврат bootstrap.ps1 поставщика. 9.17.7–9.17.11 подменяли его здешним
#     (узнаётся по строке rubl-backup.dump — она есть только в здешнем).
#     Оригинал 9.17.10 успел сохранить в backups\bootstrap-*.ps1; берём
#     копию без этой строки и не короче 5 КБ (защита от обрывка).
#  2. Резервная копия текущей app\ — robocopy /MIR в один слот app-previous.
#     Без меток времени: метку в batch не получить без for /f (команда) или
#     PowerShell, а оба варианта перед docker compose уже ломали установку.
#  3. Простой текстовый прогресс docker compose/buildx. На машине владельца
#     docker compose up начал мгновенно падать с «failed to get console: The
#     handle is invalid» — он пытается рисовать интерактивный прогресс в
#     консоли, которой у него нет. COMPOSE_PROGRESS/BUILDKIT_PROGRESS=plain
#     это отключают; старые версии неизвестные переменные просто игнорируют.
#     setx — чтобы и автозапуск при входе в систему шёл тем же путём.
#  4. Одна повторная попытка: в журнале владельца сбои docker compose up
#     (18.09, 30.09) проходили со второго раза.
#
# Комментарии внутри .bat — только ASCII: кириллица в rem сразу после
# chcp 65001 уже ломалась у cmd.exe (Собрать-Диагностику.bat, 25.11.2026).
cat > "$pkg/Обновить-Директор.bat" << BAT
@echo off
chcp 65001 >nul
rem Director update to $VERSION. See installer/build-win-update.sh for details.
set "TARGET=%LOCALAPPDATA%\RublDirector"
set "BACKUPS=%TARGET%\backups"
if not exist "%TARGET%\bootstrap.ps1" (
  echo Директор не найден в %TARGET%.
  echo Сначала поставьте полный установщик, потом запустите это обновление.
  pause
  exit /b 1
)
if not exist "%BACKUPS%" mkdir "%BACKUPS%"

rem Step 1: put back the vendor bootstrap.ps1 if an earlier update replaced it.
findstr /c:"rubl-backup.dump" "%TARGET%\bootstrap.ps1" >nul 2>&1
if errorlevel 1 goto bootstrap_ok
set "VENDOR_BS="
for %%f in ("%BACKUPS%\bootstrap-*.ps1") do (
  if %%~zf GTR 5000 (
    findstr /c:"rubl-backup.dump" "%%~f" >nul 2>&1 || set "VENDOR_BS=%%~f"
  )
)
if not defined VENDOR_BS goto bootstrap_ok
echo Возвращаю штатный bootstrap.ps1 из резервной копии ...
copy /y "%VENDOR_BS%" "%TARGET%\bootstrap.ps1" >nul
:bootstrap_ok

rem Step 2: backup of the current app folder (batch only, no PowerShell).
echo Делаю резервную копию текущей версии ...
robocopy "%TARGET%\app" "%BACKUPS%\app-previous" /MIR /XD node_modules .venv __pycache__ output .git /XF .env /NFL /NDL /NJH /NJS /NP >nul

echo Копирую файлы в %TARGET%\app ...
robocopy "%~dp0app" "%TARGET%\app" /E /XD node_modules .venv __pycache__ output .git /XF .env /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 (
  echo Не удалось скопировать файлы. Код %ERRORLEVEL%.
  pause
  exit /b 1
)
if exist "%~dp0run-diagnostics.ps1" copy /y "%~dp0run-diagnostics.ps1" "%TARGET%\run-diagnostics.ps1" >nul
if exist "%~dp0Собрать-Диагностику.bat" copy /y "%~dp0Собрать-Диагностику.bat" "%TARGET%\Собрать-Диагностику.bat" >nul

rem Step 3: plain-text progress for docker compose and buildx (no console UI).
set "COMPOSE_PROGRESS=plain"
set "BUILDKIT_PROGRESS=plain"
set "COMPOSE_ANSI=never"
set "COMPOSE_MENU=false"
setx COMPOSE_PROGRESS plain >nul 2>&1
setx BUILDKIT_PROGRESS plain >nul 2>&1
setx COMPOSE_ANSI never >nul 2>&1
setx COMPOSE_MENU false >nul 2>&1

rem Step 4: build and start, one automatic retry.
echo Собираю и запускаю Директора. Это может занять несколько минут ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%\bootstrap.ps1" -Mode install
set "BOOTSTRAP_CODE=%ERRORLEVEL%"
if "%BOOTSTRAP_CODE%"=="0" goto finish
echo.
echo Первая попытка не удалась, код %BOOTSTRAP_CODE%. Пробую ещё раз через 20 секунд ...
ping -n 21 127.0.0.1 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%\bootstrap.ps1" -Mode install
set "BOOTSTRAP_CODE=%ERRORLEVEL%"
:finish
if exist "%TARGET%\app\backend\top-seed.env" del /f /q "%TARGET%\app\backend\top-seed.env"
echo.
if "%BOOTSTRAP_CODE%"=="0" (
  echo Готово. Откройте Директор ярлыком как обычно.
) else (
  echo ОШИБКА: обновление не применилось, код %BOOTSTRAP_CODE%.
  echo Старая версия Директора продолжает работать.
  echo Запустите Собрать-Диагностику.bat из этой папки и пришлите файл.
)
pause
BAT

# CRLF, не LF: cmd.exe читает .bat блоками и иногда путает многобайтовые
# символы кириллицы в комментариях сразу после chcp 65001, если файл в
# Unix-окончаниях строк — воспроизведено на реальной машине 22.11.2026
# (слетела отдельная Собрать-Диагностику.bat ровно по этой причине).
sed -i 's/$/\r/' "$pkg/Обновить-Директор.bat"

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
