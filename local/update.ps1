# ==========================================================================
#  Обновление Директора до последней версии кода и перезапуск (Windows).
#
#  Запускается двойным щелчком по «Обновить.bat» — он вызывает этот файл.
#  Тянет текущую ветку из origin и перезапускает через start.ps1 — тот же
#  docker compose up -d --build, что подхватывает новый код и применяет
#  миграции базы. Ровно то же самое, что делает update.sh на Mac/Linux.
#
#  Имена переменных латиницей намеренно — по той же причине, что в start.ps1:
#  штатный PowerShell 5.1 без метки кодировки прочитал бы кириллицу в именах
#  как мусор, и скрипт не запустился бы вовсе.
#
#  Остановить: «Остановить.bat»
# ==========================================================================
$ErrorActionPreference = 'Stop'
# git пишет обычный прогресс (например, при fetch) в stderr — в PowerShell 7.3+
# это по умолчанию превращается в завершающую ошибку из-за строки выше.
# Переменная ничего не делает в более старых версиях, кроме как тихо создаётся.
$PSNativeCommandUseErrorActionPreference = $false
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
Set-Location $root

function Bad($text) {
    Write-Host "  x $text" -ForegroundColor Red
}
function Ok($text) {
    Write-Host "  v $text" -ForegroundColor Green
}

Write-Host "-- Обновление -------------------------------------"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Bad "Git не установлен — обновление скриптом здесь невозможно."
    Write-Host "    Скачайте: https://git-scm.com/downloads/win"
    exit 1
}

git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) {
    Bad "Это не git-репозиторий. Обновление скриптом здесь невозможно."
    exit 1
}

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -eq 'HEAD') {
    Bad "Репозиторий не на ветке (отсоединённый HEAD)."
    Write-Host "    Обратитесь к разработчику."
    exit 1
}
Write-Host "  Ветка: $branch"

# Незакоммиченные правки в уже отслеживаемых файлах — останавливаемся, чтобы
# их не затереть слиянием. Неотслеживаемые файлы pull не трогает, не в счёт.
$dirty = git status --porcelain --untracked-files=no
if ($dirty) {
    Bad "В отслеживаемых файлах есть несохранённые правки — обновление"
    Write-Host "    остановлено, чтобы их не потерять. Обратитесь к разработчику."
    exit 1
}

git fetch origin $branch
if ($LASTEXITCODE -ne 0) {
    Bad "Не удалось получить обновления. Проверьте интернет."
    exit 1
}

$local = (git rev-parse HEAD).Trim()
$remote = (git rev-parse "origin/$branch").Trim()

if ($local -eq $remote) {
    Ok "Уже последняя версия ($(git rev-parse --short HEAD))"
} else {
    git merge --ff-only "origin/$branch"
    if ($LASTEXITCODE -ne 0) {
        Bad "Обновить одним движением не вышло — история разошлась."
        Write-Host "    Обратитесь к разработчику."
        exit 1
    }
    Ok "Обновлено, теперь $(git rev-parse --short HEAD)"
}

Write-Host ""
& (Join-Path $here "start.ps1")
