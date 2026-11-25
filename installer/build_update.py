"""Собрать пакет обновления Пульта для Windows-компьютера салона.

    python3 installer/build_update.py 9.25.6 installer/notes-9.25.6.txt

Результат: ../Rubl-Director-<версия>.zip рядом с репозиторием (в корне
рабочей копии). Внутри:

    Rubl-Director-<версия>/
        UPDATE.bat                — запускает владелец
        Собрать-Диагностику.bat   — если что-то пошло не так
        run-diagnostics.ps1
        README.txt
        app/                      — код из git: backend, frontend (с готовым dist),
                                    local, scripts, assets, docs + файлы корня

Почему так, а не build-win-update.sh (9.17.x):
  * Архив — Python zipfile: он ставит флаг UTF-8 у русских имён. Утилита zip
    этого не делает, и в Проводнике имена превращались в кракозябры
    (инцидент 19.10.2026 линии 9.25).
  * Папки кода копируются зеркально (robocopy /MIR), а не поверх: иначе на
    диске остаются файлы другой сборки. Ровно так файлы миграций 9.17.x легли
    рядом с 0013–0016 линии 9.25, и обновление базы встало с «Multiple head
    revisions» (25.11.2026). .env, output, база (том Docker) не затрагиваются.
  * Пакет не выпускается, если APP_VERSION в main.py не равна собираемой,
    если в frontend/dist нет index.html или если у истории миграций не одна
    голова.
"""

import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
КОД = ("backend", "frontend", "local", "scripts", "assets", "docs")
ФАЙЛЫ_КОРНЯ = (".dockerignore", ".env.example", "README.md")
МИГРАЦИИ_917 = ("0013_yclients_id_bigint.py", "0014_merge_foreign_heads.py")


def стоп(текст: str) -> None:
    sys.exit(f"ПАКЕТ НЕ СОБРАН: {текст}")


def файлы_из_git() -> list[str]:
    вывод = subprocess.run(
        ["git", "ls-files", "-z", *КОД, *ФАЙЛЫ_КОРНЯ],
        cwd=REPO, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [f for f in вывод.split("\0") if f]


def проверки(версия: str, файлы: list[str]) -> None:
    main_py = (REPO / "backend/app/main.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION = "([^"]+)"', main_py, re.MULTILINE)
    if not m or m.group(1) != версия:
        стоп(f"APP_VERSION в main.py = {m.group(1) if m else '?'}, а собираем {версия}")
    for нужно in ("frontend/dist/index.html", "local/Dockerfile", "local/docker-compose.yml",
                  "backend/alembic.ini", "backend/uv.lock", ".dockerignore"):
        if нужно not in файлы:
            стоп(f"нет {нужно} среди файлов git")
    # Всё, на что ссылается index.html, должно ехать в пакете: иначе Пульт
    # откроется пустой страницей. Ловит пересобранный, но не добавленный в git
    # интерфейс (так и вышло бы с 9.25.6, если бы не эта проверка).
    index = (REPO / "frontend/dist/index.html").read_text(encoding="utf-8")
    for ссылка in re.findall(r'(?:src|href)="/?(assets/[^"]+)"', index):
        if f"frontend/dist/{ссылка}" not in файлы:
            стоп(f"index.html ссылается на frontend/dist/{ссылка}, а в git его нет")
    for f in файлы:
        имя = Path(f).name
        if имя == ".env" or (имя.startswith(".env.") and имя != ".env.example"):
            стоп(f"в пакет попал бы файл настроек: {f}")
    for имя in МИГРАЦИИ_917:
        if f"backend/alembic/versions/{имя}" in файлы:
            стоп(f"в репозитории лежит миграция 9.17.x {имя}")
    головы = subprocess.run(
        [sys.executable, "-c",
         ("from alembic.config import Config; from alembic.script import ScriptDirectory;"
          "c=Config(); c.set_main_option('script_location','alembic');"
          "print(' '.join(ScriptDirectory.from_config(c).get_heads()))")],
        cwd=REPO / "backend", capture_output=True, text=True, check=False,
    )
    if головы.returncode != 0 or len(головы.stdout.split()) != 1:
        стоп(f"у истории миграций не одна голова: {головы.stdout.strip()} {головы.stderr[-300:]}")


def crlf(текст: str) -> bytes:
    return текст.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


UPDATE_BAT = r"""@echo off
chcp 65001 >nul
rem RublDirector update to {VERSION}. Built by installer/build_update.py.
rem Comments are ASCII only; the file is CRLF so Cyrillic echo lines parse correctly.

echo %~dp0 | findstr /i "Temp\\" >nul
if %ERRORLEVEL%==0 (
  echo.
  echo  Сначала распакуйте архив целиком, потом запускайте этот файл.
  echo.
  pause
  exit /b 1
)

set "TARGET=%LOCALAPPDATA%\RublDirector"
set "APP=%TARGET%\app"
set "BACKUPS=%TARGET%\backups"
if not exist "%TARGET%\bootstrap.ps1" (
  echo Пульт не найден в %TARGET%.
  echo Сначала поставьте полный установщик, потом это обновление.
  pause
  exit /b 1
)
if not exist "%BACKUPS%" mkdir "%BACKUPS%"

rem Step 1: put back the vendor bootstrap.ps1 if 9.17.7-9.17.11 replaced it
rem (their copy contains the string rubl-backup.dump).
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

rem Step 2: backup of the current code (batch only, no PowerShell).
echo Делаю резервную копию текущей версии ...
robocopy "%APP%" "%BACKUPS%\app-previous" /MIR /XD node_modules .venv __pycache__ output .git /XF .env /NFL /NDL /NJH /NJS /NP >nul

rem Step 3: code folders are mirrored, so files of other builds are removed.
rem .env, output and the database (a Docker volume) are outside these folders.
echo Копирую файлы ...
for %%d in (backend frontend local scripts assets docs) do (
  robocopy "%~dp0app\%%d" "%APP%\%%d" /MIR /XD node_modules .venv __pycache__ output .git /XF .env /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 goto copy_failed
)
robocopy "%~dp0app" "%APP%" /XF .env /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto copy_failed
del /f /q "%APP%\backend\alembic\versions\0013_yclients_id_bigint.py" >nul 2>&1
del /f /q "%APP%\backend\alembic\versions\0014_merge_foreign_heads.py" >nul 2>&1
if exist "%~dp0run-diagnostics.ps1" copy /y "%~dp0run-diagnostics.ps1" "%TARGET%\run-diagnostics.ps1" >nul
if exist "%~dp0Собрать-Диагностику.bat" copy /y "%~dp0Собрать-Диагностику.bat" "%TARGET%\Собрать-Диагностику.bat" >nul

rem Step 4: plain-text progress for docker compose and buildx (no console UI);
rem without it compose up failed at once with "failed to get console".
set "COMPOSE_PROGRESS=plain"
set "BUILDKIT_PROGRESS=plain"
set "COMPOSE_ANSI=never"
set "COMPOSE_MENU=false"
setx COMPOSE_PROGRESS plain >nul 2>&1
setx BUILDKIT_PROGRESS plain >nul 2>&1
setx COMPOSE_ANSI never >nul 2>&1
setx COMPOSE_MENU false >nul 2>&1

rem Step 5: build and start, one automatic retry.
echo Собираю и запускаю Пульт. Это займёт 5-10 минут ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%\bootstrap.ps1" -Mode install
set "BOOTSTRAP_CODE=%ERRORLEVEL%"
if "%BOOTSTRAP_CODE%"=="0" goto finish
echo.
echo Первая попытка не удалась, код %BOOTSTRAP_CODE%. Пробую ещё раз через 20 секунд ...
ping -n 21 127.0.0.1 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%\bootstrap.ps1" -Mode install
set "BOOTSTRAP_CODE=%ERRORLEVEL%"
goto finish

:copy_failed
echo ОШИБКА: не удалось скопировать файлы. Пульт не изменён, кроме уже скопированного.
echo Сделайте снимок этого окна и пришлите.
pause
exit /b 1

:finish
echo.
if "%BOOTSTRAP_CODE%"=="0" (
  echo Готово. Откройте Пульт как обычно: внизу справа должно быть «Пульт v{VERSION}».
) else (
  echo ОШИБКА: обновление завершилось не полностью, код %BOOTSTRAP_CODE%.
  echo Сделайте снимок этого окна, запустите Собрать-Диагностику.bat
  echo из этой папки и пришлите снимок и файл с Рабочего стола.
)
pause
"""


def main(версия: str, заметки: Path) -> Path:
    файлы = файлы_из_git()
    проверки(версия, файлы)
    имя = f"Rubl-Director-{версия}"
    readme = (
        f"РублЪ Пульт {версия} — обновление для Windows\n\n"
        "1. Распакуйте архив целиком (правая кнопка — «Извлечь все»).\n"
        "2. Дважды щёлкните UPDATE.bat. Дождитесь «Готово» (5–10 минут: собирается новый образ).\n"
        f"3. Откройте Пульт как обычно. Внизу справа должно быть «Пульт v{версия}».\n\n"
        "Если в конце «ОШИБКА» — снимок окна и файл от Собрать-Диагностику.bat.\n\n"
        f"Что нового в {версия}:\n"
        + заметки.read_text(encoding="utf-8").rstrip() + "\n\n"
        + (HERE / "changelog-9.25.txt").read_text(encoding="utf-8").rstrip() + "\n\n"
        "Данные не затрагиваются: .env, база и журнал обзвона остаются на месте.\n"
    )
    выход = REPO / f"{имя}.zip"
    выход.unlink(missing_ok=True)
    with zipfile.ZipFile(выход, "w", zipfile.ZIP_DEFLATED) as z:
        for f in файлы:
            z.write(REPO / f, f"{имя}/app/{f}")
        z.writestr(f"{имя}/UPDATE.bat", crlf(UPDATE_BAT.replace("{VERSION}", версия)))
        z.writestr(f"{имя}/README.txt", crlf(readme))
        z.write(HERE / "run-diagnostics.ps1", f"{имя}/run-diagnostics.ps1")
        z.write(HERE / "Собрать-Диагностику.bat", f"{имя}/Собрать-Диагностику.bat")

    with zipfile.ZipFile(выход) as z:
        имена = z.namelist()
        for info in z.infolist():
            if not info.filename.isascii() and not info.flag_bits & 0x800:
                стоп(f"у {info.filename} нет флага UTF-8")
        bat = z.read(f"{имя}/UPDATE.bat")
        if bat.startswith(b"\xef\xbb\xbf") or bat.count(b"\n") != bat.count(b"\r\n"):
            стоп("UPDATE.bat должен быть CRLF и без BOM")
        for строка in bat.decode("utf-8").splitlines():
            if строка.lstrip().lower().startswith("rem") and not строка.isascii():
                стоп(f"кириллица в комментарии .bat: {строка}")
    print(f"{выход.name}: {len(имена)} файлов, {выход.stat().st_size // 1024} КБ")
    return выход


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], Path(sys.argv[2]))
