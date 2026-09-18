# ==========================================================================
#  Фоновая часть установки Директора на Windows.
#
#  Запускается тремя способами:
#    -Mode install   — из установщика, сразу после распаковки файлов;
#    -Mode autostart — заданием планировщика при входе в систему;
#    -Mode open      — из ярлыка «Директор» через open.ps1.
#
#  Делает всё, что человек иначе делал бы руками: ставит Docker, запускает
#  его, собирает образ, обновляет структуру базы и открывает браузер.
#
#  Имена переменных латиницей намеренно — по той же причине, что и в
#  local/start.ps1: штатный PowerShell 5.1 читает .ps1 без метки кодировки
#  как ANSI. Метку (BOM) мы ставим, но если её срежет редактор или git,
#  поедут только надписи, а не работа.
# ==========================================================================
param(
    [ValidateSet('install', 'autostart', 'open')]
    [string]$Mode = 'autostart'
)

$ErrorActionPreference = 'Stop'
# Без этого Invoke-WebRequest рисует полосу прогресса и качает 600 МБ часами.
$ProgressPreference = 'SilentlyContinue'
# PowerShell 5.1 по умолчанию ходит по TLS 1.0, который серверы уже не принимают.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Base       = Split-Path -Parent $PSCommandPath
$App        = Join-Path $Base 'app'
$ComposeDir = Join-Path $App 'local'
$EnvFile    = Join-Path $App '.env'
$LogDir     = Join-Path $Base 'log'
$LogFile    = Join-Path $LogDir 'bootstrap.log'
$StatusFile = Join-Path $Base 'status.txt'
$TaskName   = 'РублЪ Директор'

# Чем закончилась работа. Установщик на NSIS читает это числом, а не текстом:
# текст пришлось бы отдавать в какой-то кодировке, и на этом всё бы и село.
#   0  — Директор поднят и отвечает
#   10 — нет настроек (не заполнен .env)
#   11 — Docker поставлен, нужна перезагрузка
#   12 — не поднялся по другой причине
#   1  — исключение (подробности в журнале)
$script:Outcome = 12

# Проверено 18.09.2026: адрес отдаёт 200 и файл на 628 МБ.
$DockerUrl  = 'https://desktop.docker.com/win/main/amd64/Docker Desktop Installer.exe'
# Требование Docker Desktop из его документации: Windows 10 22H2 (19045)
# или Windows 11 23H2 (22631). Ниже — ставить бессмысленно, WSL2 не поднимется.
$MinBuild   = 19045

# ── Журнал и состояние ────────────────────────────────────────────────────

function Write-Log {
    param([string]$Text)
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    # Журнал не должен расти бесконечно: задание планировщика пишет в него
    # при каждом входе в систему.
    if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 1MB) {
        Move-Item $LogFile "$LogFile.old" -Force
    }
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Set-Status {
    param([string]$Text)
    Set-Content -Path $StatusFile -Value $Text -Encoding UTF8
    Write-Log "состояние: $Text"
}

function Get-AppPort {
    if (Test-Path $EnvFile) {
        $hit = Select-String -Path $EnvFile -Pattern '^APP_PORT=(\d+)' | Select-Object -First 1
        if ($hit) { return $hit.Matches.Groups[1].Value }
    }
    return '8000'
}

# ── Docker ────────────────────────────────────────────────────────────────

function Find-Docker {
    # Сразу после установки Docker его каталог ещё не попал в PATH текущего
    # процесса, поэтому одного Get-Command мало — проверяем и обычные места.
    $cmd = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($path in @(
            (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'))) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Find-DockerDesktop {
    foreach ($path in @(
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'))) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-Docker {
    # Ярлык «Директор» запускается без повышения прав. Если Docker с него
    # ставить, установка провалится где-то в середине и оставит мусор —
    # честнее отказаться сразу и сказать, что делать.
    if (-not (Test-Elevated)) {
        throw 'Docker не установлен, а прав на установку нет. Запустите установщик Директора ещё раз — он спросит права.'
    }
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt $MinBuild) {
        throw "Windows слишком старая (сборка $build). Docker Desktop требует 22H2 (19045) или новее."
    }

    Set-Status 'Скачиваю Docker (около 600 МБ)'
    $installer = Join-Path $env:TEMP 'DockerDesktopInstaller.exe'
    # curl.exe входит в Windows 10 начиная с 1803 и качает большие файлы
    # заметно надёжнее Invoke-WebRequest. Если его нет — запасной путь.
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --fail --silent --show-error -o $installer $DockerUrl
        if ($LASTEXITCODE -ne 0) { throw "не удалось скачать Docker Desktop (код $LASTEXITCODE)" }
    } else {
        Invoke-WebRequest -Uri $DockerUrl -OutFile $installer -UseBasicParsing
    }

    Set-Status 'Устанавливаю Docker'
    Write-Log 'запускаю установщик Docker Desktop в тихом режиме'
    # Ключи взяты из документации Docker дословно. --accept-license снимает
    # вопрос о лицензии при первом запуске, --always-run-service переводит
    # службу в автозапуск, иначе контейнеры не поднимутся после перезагрузки.
    $run = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
        'install', '--quiet', '--accept-license', '--backend=wsl-2', '--always-run-service')
    Write-Log "установщик Docker завершился с кодом $($run.ExitCode)"

    # 3010 — «установлено, нужна перезагрузка». Это не ошибка: после
    # перезагрузки работу продолжит задание планировщика.
    # Шестьсот мегабайт во временной папке ни к чему — убираем в любом исходе.
    Remove-Item $installer -Force -ErrorAction SilentlyContinue

    if ($run.ExitCode -eq 3010) {
        Set-Status 'Docker установлен, нужна перезагрузка компьютера'
        return $false
    }
    if ($run.ExitCode -ne 0) {
        throw "установщик Docker Desktop вернул код $($run.ExitCode)"
    }
    return $true
}

function Start-DockerEngine {
    param([int]$TimeoutSec = 600)

    $docker = Find-Docker
    if (-not $docker) { throw 'docker.exe не найден после установки' }

    & $docker info *> $null
    if ($LASTEXITCODE -eq 0) { return $docker }

    $desktop = Find-DockerDesktop
    if ($desktop) {
        Write-Log 'запускаю Docker Desktop'
        Start-Process -FilePath $desktop | Out-Null
    }

    Set-Status 'Запускаю Docker'
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        & $docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Log 'Docker отвечает'
            return $docker
        }
    }
    throw "Docker не ответил за $TimeoutSec секунд"
}

# ── Настройки ─────────────────────────────────────────────────────────────

function Test-Settings {
    if (-not (Test-Path $EnvFile)) { return $false }
    # Незаполненные заготовки вида КЛЮЧ=<что-то> приложение не примет:
    # оно упадёт на разборе настроек, а человек увидит невнятную ошибку.
    $blanks = Select-String -Path $EnvFile -Pattern '^[A-Z_]+=<' -ErrorAction SilentlyContinue
    return -not $blanks
}

# ── Права на файлы ────────────────────────────────────────────────────────

function Protect-Files {
    # В .env лежат ключи YCLIENTS и все пароли. По умолчанию всё, что создано
    # в ProgramData, доступно на чтение любой учётной записи компьютера —
    # для этого файла это недопустимо.
    #
    # Снимаем наследование и оставляем троих: систему, администраторов и того,
    # кто ставил Директора (под UAC это тот же человек — повышение прав не
    # меняет учётную запись). Группу «Пользователи» не даём: у обычного
    # сотрудника, севшего за этот компьютер, доступа к ключам быть не должно.
    #
    # Ярлык «Директор» работает без повышения прав, поэтому учётная запись
    # нужна в списке именно поимённо: в непривилегированном токене членство
    # в администраторах не действует.
    $account = "$env:USERDOMAIN\$env:USERNAME"
    try {
        & icacls.exe $Base /inheritance:r /grant:r `
            '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "${account}:(OI)(CI)F" /T /C /Q
        if ($LASTEXITCODE -ne 0) { throw "icacls вернул код $LASTEXITCODE" }
        Write-Log "права на $Base ограничены: SYSTEM, администраторы, $account"
    } catch {
        # Не повод останавливать установку: Директор будет работать, но об
        # ослабленных правах должно остаться внятное упоминание в журнале.
        Write-Log "ВНИМАНИЕ: не удалось ограничить права на $Base — $($_.Exception.Message)"
    }
}

# ── Запуск приложения ─────────────────────────────────────────────────────

function Start-Stack {
    param([string]$Docker, [switch]$Build)

    Push-Location $ComposeDir
    try {
        $arguments = @('compose', '--env-file', $EnvFile, 'up', '-d')
        if ($Build) {
            $arguments += '--build'
            Set-Status 'Собираю Директора (первый раз это долго)'
        } else {
            Set-Status 'Запускаю Директора'
        }
        & $Docker @arguments
        if ($LASTEXITCODE -ne 0) { throw "docker compose up вернул код $LASTEXITCODE" }

        # Ждём, пока контейнер действительно поднимется. Без этого миграция
        # уходит в перезапускающийся контейнер и тихо не выполняется.
        Set-Status 'Готовлю базу данных'
        $ready = $false
        foreach ($attempt in 1..90) {
            $state = & $Docker inspect -f '{{.State.Status}}' rubl_director 2>$null
            if ($state -eq 'running') {
                & $Docker compose --env-file $EnvFile exec -T director `
                    python -c "import socket;socket.create_connection(('postgres',5432),3)" *> $null
                if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            }
            Start-Sleep -Seconds 2
        }
        if (-not $ready) {
            & $Docker compose --env-file $EnvFile logs --tail 30 director | ForEach-Object { Write-Log $_ }
            throw 'приложение не запустилось'
        }

        & $Docker compose --env-file $EnvFile exec -T director alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'не удалось обновить структуру базы' }
        Write-Log 'структура базы обновлена'
    } finally {
        Pop-Location
    }
}

function Wait-Health {
    param([int]$TimeoutSec = 120)
    $port = Get-AppPort
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    return $false
}

function Open-Director {
    $port = Get-AppPort
    Start-Process "http://localhost:$port"
}

# ── Общий ход работы ──────────────────────────────────────────────────────

function Invoke-Bringup {
    param([switch]$AllowInstall, [switch]$Build)

    if (-not (Test-Settings)) {
        Set-Status 'Нужны настройки: заполните файл .env'
        Write-Log "не заполнен $EnvFile"
        $script:Outcome = 10
        return $false
    }

    $docker = Find-Docker
    if (-not $docker) {
        if (-not $AllowInstall) {
            Set-Status 'Docker не установлен'
            $script:Outcome = 12
            return $false
        }
        if (-not (Install-Docker)) {
            # Нужна перезагрузка: продолжит задание планировщика при входе.
            $script:Outcome = 11
            return $false
        }
    }

    $docker = Start-DockerEngine
    Start-Stack -Docker $docker -Build:$Build

    if (Wait-Health) {
        Set-Status 'Готов'
        $script:Outcome = 0
        return $true
    }
    Set-Status 'Приложение не отвечает'
    $script:Outcome = 12
    return $false
}

try {
    Write-Log "== запуск, режим $Mode =="
    switch ($Mode) {

        'install' {
            Protect-Files
            # Первый раз образ надо собрать: без --build контейнер поднимать
            # не из чего.
            if (Invoke-Bringup -AllowInstall -Build) { Open-Director }
        }

        'autostart' {
            # При входе в систему. --build тоже нужен: если предыдущий заход
            # оборвался на перезагрузке, образа ещё нет, а если есть —
            # сборка займёт секунду и ничего не пересоберёт.
            Invoke-Bringup -AllowInstall -Build | Out-Null
        }

        'open' {
            $port = Get-AppPort
            try {
                Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
                Open-Director
            } catch {
                Write-Host ''
                Write-Host '  Директор ещё не готов. Поднимаю его — это может занять'
                Write-Host '  несколько минут, окно закроется само.'
                Write-Host ''
                if (Invoke-Bringup -AllowInstall -Build) {
                    Open-Director
                } else {
                    $state = if (Test-Path $StatusFile) { Get-Content $StatusFile -Raw } else { 'неизвестно' }
                    Write-Host ''
                    Write-Host "  Не получилось. Состояние: $state"
                    Write-Host "  Подробности: $LogFile"
                    Write-Host ''
                    Read-Host '  Нажмите Enter, чтобы закрыть'
                }
            }
        }
    }
    Write-Log "== готово, код $script:Outcome =="
    exit $script:Outcome
} catch {
    Set-Status "Ошибка: $($_.Exception.Message)"
    Write-Log "ОШИБКА: $($_.Exception.Message)"
    Write-Log $_.ScriptStackTrace
    exit 1
}
