# ==========================================================================
#  Собирает диагностику Директора (логи запуска, состояние Docker, журнал
#  контейнеров) в один файл на Рабочем столе и открывает его.
#
#  Работает независимо от того, запускается ли Директор вообще — именно
#  поэтому это отдельный скрипт, а не часть bootstrap.ps1: если Директор
#  в цикле падает, тот же PowerShell должен суметь снять с него диагностику.
#
#  Имена переменных латиницей — по той же причине, что и в bootstrap.ps1:
#  штатный PowerShell 5.1 без метки кодировки читает .ps1 как ANSI.
# ==========================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Target = Join-Path $env:LOCALAPPDATA 'RublDirector'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) "диагностика-пульт-$stamp.txt"

function Add-Section {
    param([string]$Title, [scriptblock]$Body)
    Add-Content -Path $out -Value "`r`n==================== $Title ====================" -Encoding UTF8
    # Строки, которые docker и alembic пишут в поток ошибок, PowerShell 5.1
    # заворачивает в NativeCommandError с «At C:\...» на пол-экрана. Берём
    # только их текст.
    $ErrorActionPreference = 'Continue'
    try {
        $text = & $Body 2>&1 | ForEach-Object { "$_" } | Out-String
        if ([string]::IsNullOrWhiteSpace($text)) { $text = '(пусто)' }
        Add-Content -Path $out -Value $text -Encoding UTF8
    } catch {
        Add-Content -Path $out -Value "не удалось получить: $($_.Exception.Message)" -Encoding UTF8
    }
}

Set-Content -Path $out -Value "Диагностика Директора — $(Get-Date -Format 'dd.MM.yyyy HH:mm:ss')" -Encoding UTF8

Add-Section 'bootstrap.log (последние 200 строк)' {
    Get-Content (Join-Path $Target 'log\bootstrap.log') -Tail 200 -ErrorAction Stop
}
Add-Section 'status.txt (последнее известное состояние)' {
    Get-Content (Join-Path $Target 'status.txt') -ErrorAction Stop
}
Add-Section 'docker ps -a (все контейнеры, включая упавшие)' {
    docker ps -a
}
Add-Section 'docker logs rubl_director (последние 300 строк)' {
    docker logs rubl_director --tail 300
}
Add-Section 'docker logs rubl_db (последние 100 строк)' {
    docker logs rubl_db --tail 100
}
$Versions = Join-Path $Target 'app\backend\alembic\versions'
# Миграции этой сборки. Всё остальное в папке — от другой сборки Директора.
$OurMigrations = @(
    '0001_initial_schema.py', '0002_cost_model.py', '0003_fixed_monthly.py',
    '0004_sync_runs.py', '0005_client_admin_note.py', '0006_shifts.py',
    '0007_cash_balances.py', '0008_telegram_settings.py', '0009_app_settings.py',
    '0010_monthly_report.py', '0011_acquiring_rows.py', '0012_client_do_not_call.py',
    '0013_yclients_id_bigint.py', '0014_merge_foreign_heads.py'
)
Add-Section 'миграции: ревизия базы и головы' {
    'alembic current:'
    docker exec rubl_director alembic current
    'alembic heads:'
    docker exec rubl_director alembic heads
}
Add-Section 'миграции: файлы на диске' {
    Get-ChildItem $Versions -Filter *.py -ErrorAction Stop |
        Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize | Out-String -Width 200
}
Add-Section 'миграции: чужие файлы (содержимое)' {
    Get-ChildItem $Versions -Filter *.py -ErrorAction Stop |
        Where-Object { $OurMigrations -notcontains $_.Name } |
        ForEach-Object { "----- $($_.Name)"; Get-Content $_.FullName -Encoding UTF8 }
}
Add-Section 'docker images' {
    docker images
}
Add-Section 'свободное место на диске' {
    Get-PSDrive -PSProvider FileSystem |
        Select-Object Name,
            @{n = 'Свободно, ГБ'; e = { [math]::Round($_.Free / 1GB, 1) } },
            @{n = 'Занято, ГБ'; e = { [math]::Round($_.Used / 1GB, 1) } } |
        Format-Table -AutoSize | Out-String
}

Write-Host ""
Write-Host "Готово: $out"
Write-Host "Пришлите этот файл разработчику."
Write-Host ""
notepad $out
