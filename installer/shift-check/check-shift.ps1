# ==========================================================================
#  Состав смены: что Пульт знает о мастерах на сегодня. Только имена мастеров
#  и цифры — без клиентов. Файл кладётся на Рабочий стол и открывается.
#  Переменные латиницей: PowerShell 5.1 без BOM читает .ps1 как ANSI.
# ==========================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$Target = Join-Path $env:LOCALAPPDATA 'RublDirector'
$EnvFile = Join-Path $Target 'app\.env'
$DbUser = 'rubl'; $DbName = 'rubl_director'
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile -Encoding UTF8) {
        if ($line -match '^\s*POSTGRES_USER\s*=\s*(.+?)\s*$') { $DbUser = $Matches[1].Trim('"') }
        if ($line -match '^\s*POSTGRES_DB\s*=\s*(.+?)\s*$') { $DbName = $Matches[1].Trim('"') }
    }
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) "состав-смены-$stamp.txt"
Set-Content -Path $out -Value "Состав смены — $(Get-Date -Format 'dd.MM.yyyy HH:mm:ss')" -Encoding UTF8

function Add-Query {
    param([string]$Title, [string]$Sql)
    Add-Content -Path $out -Value "`r`n==================== $Title ====================" -Encoding UTF8
    $text = docker exec rubl_db psql -U $DbUser -d $DbName -P pager=off -c $Sql 2>&1 | ForEach-Object { "$_" } | Out-String
    if ([string]::IsNullOrWhiteSpace($text)) { $text = '(пусто)' }
    Add-Content -Path $out -Value $text -Encoding UTF8
}

$Today = "(now() at time zone 'Europe/Moscow')::date"
Add-Query 'Версия Пульта' "select version_num as migration from alembic_version"
Add-Query 'Записи на сегодня по мастерам (статус, сколько, сумма)' @"
select e.name as master, e.yclients_id as staff_id, v.status, count(*) as records, sum(v.total_amount) as amount
from visits v join employees e on e.id = v.employee_id
where (v.datetime at time zone 'Europe/Moscow')::date = $Today
group by e.name, e.yclients_id, v.status order by 1, 3
"@
Add-Query 'Смена сегодня в Пульте (кто в составе)' @"
select s.shift_date, s.opened_at at time zone 'Europe/Moscow' as opened, se.staff_name_snapshot as master,
       se.staff_id, se.arrival_time, se.departure_time
from shifts s left join shift_employees se on se.shift_id = s.id
where s.shift_date = $Today
"@
Add-Query 'Мастера в настройках (barbers)' "select key, value from report_settings where key in ('barbers', 'barbers_excluded')"
Add-Query 'Сотрудники из YCLIENTS в базе Пульта' "select id, yclients_id as staff_id, name, is_active from employees order by name"
Add-Query 'Последние выгрузки из YCLIENTS' @"
select started_at at time zone 'Europe/Moscow' as started, ok, visits_count, left(error, 300) as error
from sync_runs order by id desc limit 8
"@
Add-Query 'Самая свежая запись в базе' "select max(datetime at time zone 'Europe/Moscow') as latest_record from visits"
try {
    $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 5
    Add-Content -Path $out -Value "`r`n==================== /health ====================`r`n$($health.Content)" -Encoding UTF8
} catch {
    Add-Content -Path $out -Value "`r`n/health не ответил: $($_.Exception.Message)" -Encoding UTF8
}
Write-Host "Готово: $out"
notepad $out
