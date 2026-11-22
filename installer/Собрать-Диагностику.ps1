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
    try {
        $text = & $Body 2>&1 | Out-String
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
