# ==========================================================================
#  Запуск Директора на Windows.
#
#  Запускается двойным щелчком по «Запустить.bat» — он вызывает этот файл.
#  Отдельный скрипт на PowerShell, а не на bat, потому что проверок много,
#  а bat для них не приспособлен: ни нормальных условий, ни ожидания в цикле.
#  PowerShell есть в любой Windows начиная с седьмой, ставить нечего.
#
#  Имена переменных латиницей намеренно: штатный PowerShell 5.1 читает .ps1
#  без метки кодировки как ANSI, и кириллица в именах превратилась бы в мусор,
#  а скрипт не запустился бы вовсе. Метку мы ставим, но если её однажды
#  срежет редактор или git — поедут только надписи, а не работа.
#
#  Остановить: «Остановить.bat»
# ==========================================================================
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
Set-Location $here

function Bad($text) {
    Write-Host "  x $text" -ForegroundColor Red
}
function Ok($text) {
    Write-Host "  v $text" -ForegroundColor Green
}

Write-Host "-- Проверки --------------------------------------"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Bad "Docker не установлен."
    Write-Host "    Скачайте Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
}

# docker info возвращает ненулевой код, когда служба не запущена. Проверяем
# именно так, а не наличием файла: установленный, но не запущенный Docker —
# самая частая причина «ничего не работает».
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Bad "Docker установлен, но не запущен."
    Write-Host "    Откройте Docker Desktop и дождитесь, пока он загрузится."
    exit 1
}
Ok "Docker работает"

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host ""
    Write-Host "  Создан файл настроек: $envFile"
    Write-Host "  Откройте его в Блокноте и заполните значения в угловых скобках:"
    Write-Host "    ключи YCLIENTS, пароль базы, логины и пароли для входа."
    Write-Host "  Потом запустите этот файл ещё раз."
    exit 1
}
Ok "Файл настроек на месте"

# Незаполненные заготовки вида КЛЮЧ=<что-то> — частая причина «оно не
# запускается»: приложение падает на разборе настроек, а человек видит
# невнятную ошибку вместо понятной подсказки.
$blanks = Select-String -Path $envFile -Pattern '^[A-Z_]+=<' -ErrorAction SilentlyContinue
if ($blanks) {
    Bad "В .env остались незаполненные значения:"
    foreach ($line in $blanks) { Write-Host "      $($line.Line)" }
    Write-Host "    Угловые скобки нужно убрать вместе с текстом внутри."
    exit 1
}
Ok "Настройки заполнены"

$outDir = Join-Path $root "output"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
Ok "папка для журнала обзвона готова"

Write-Host ""
Write-Host "-- Запуск ----------------------------------------"
Write-Host "   Первый раз это долго: Docker собирает образ."
docker compose --env-file $envFile up -d --build
if ($LASTEXITCODE -ne 0) {
    Bad "Docker не смог собрать или запустить контейнеры."
    exit 1
}

Write-Host ""
Write-Host "-- Подготовка базы -------------------------------"

# Ждём, пока контейнер приложения действительно поднимется. Без этого
# миграция уходит в перезапускающийся контейнер и тихо не выполняется.
$ready = $false
foreach ($attempt in 1..60) {
    $state = docker inspect -f '{{.State.Status}}' rubl_director 2>$null
    if ($state -eq 'running') {
        docker compose --env-file $envFile exec -T director `
            python -c "import socket;socket.create_connection(('postgres',5432),3)" *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    }
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    Bad "Приложение не запустилось. Что случилось:"
    docker compose --env-file $envFile logs --tail 20 director
    exit 1
}

docker compose --env-file $envFile exec -T director alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Bad "Не удалось обновить структуру базы. Директор запущен не будет."
    exit 1
}
Ok "структура базы обновлена"

# Последняя проверка: приложение должно отвечать. Печатать «запущен», не
# убедившись в этом, — значит отправить человека искать несуществующий адрес.
docker compose --env-file $envFile exec -T director `
    python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')" *> $null
if ($LASTEXITCODE -ne 0) {
    Bad "Приложение не отвечает на проверку здоровья."
    docker compose --env-file $envFile logs --tail 20 director
    exit 1
}
Ok "приложение отвечает"

$port = (Select-String -Path $envFile -Pattern '^APP_PORT=(\d+)' |
         Select-Object -First 1).Matches.Groups[1].Value
if (-not $port) { $port = "8000" }

Write-Host ""
Write-Host "=================================================="
Write-Host "  Директор запущен: http://localhost:$port"
if (Select-String -Path $envFile -Pattern '^BIND_HOST=0\.0\.0\.0' -Quiet) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
              Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
              Select-Object -First 1).IPAddress
    if ($ip) { Write-Host "  Из салона по сети:  http://${ip}:$port" }
}
Write-Host ""
Write-Host "  Первая загрузка данных из YCLIENTS начнётся через"
Write-Host "  десять секунд и займёт несколько минут."
Write-Host "=================================================="
