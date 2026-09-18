; ==========================================================================
;  Установщик Директора для Windows.
;
;  Собирается из Linux командой installer/build.sh (makensis из пакета nsis).
;  Результат — один файл «РублЪ-Директор-Установка.exe».
;
;  Что он делает после двойного щелчка — и больше ничего от человека не
;  требуется, окна прав в том числе:
;    1. распаковывает исходники Директора в %LOCALAPPDATA%\RublDirector\app;
;    2. кладёт туда настройки (файл «настройки.env» рядом с установщиком);
;    3. запускает уже установленный Docker Desktop и ждёт, пока тот поднимется;
;    4. собирает образ, поднимает контейнеры, обновляет структуру базы;
;    5. заводит задание планировщика, чтобы Директор поднимался при входе;
;    6. создаёт ярлык на рабочем столе и открывает браузер.
;
;  Docker Desktop ставится отдельно и заранее: в нём проходят регистрацию,
;  которую всё равно делают руками. Ровно поэтому установщику и не нужны
;  права администратора — ставить службы и включать WSL2 больше не его дело.
;  Всё живёт в профиле пользователя, и там же остаётся закрытым от чужих
;  учётных записей: в .env лежат ключи YCLIENTS и все пароли.
;
;  Имена меток и переменных латиницей: NSIS не принимает кириллицу в
;  идентификаторах. Всё, что видит человек, — по-русски.
; ==========================================================================

Unicode true
SetCompressor /SOLID lzma

!define NAME    "РублЪ Директор"
!define REGKEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\RublDirector"
!define TASK    "РублЪ Директор"

Name "${NAME}"
OutFile "..\РублЪ-Директор-Установка.exe"
Icon "director.ico"
UninstallIcon "director.ico"
; user, а не admin: поднимать права больше незачем, а лишнее окно UAC —
; это ровно тот шаг, которого быть не должно.
RequestExecutionLevel user
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=1049 "ProductName"     "${NAME}"
VIAddVersionKey /LANG=1049 "FileDescription" "Установка Директора барбершопа РублЪ"
VIAddVersionKey /LANG=1049 "FileVersion"     "1.0.0.0"
VIAddVersionKey /LANG=1049 "LegalCopyright"  "Барбершоп РублЪ"

; Единственная страница — ход работы. Ни выбора папки, ни компонентов:
; всё решено заранее, спрашивать нечего.
Page instfiles
UninstPage instfiles

Var SettingsSource   ; откуда взяли настройки; пусто — не нашли

Function .onInit
    ; Профиль пользователя, а не Program Files и не ProgramData: туда можно
    ; писать без прав администратора, там же лежит контекст сборки Docker и
    ; журнал. И главное — эта папка по умолчанию закрыта от других учётных
    ; записей компьютера, а в .env лежат ключи YCLIENTS и все пароли.
    SetShellVarContext current
    StrCpy $INSTDIR "$LOCALAPPDATA\RublDirector"
FunctionEnd

Section "Директор"

    ; ── Настройки ─────────────────────────────────────────────────────────
    ; Ключи YCLIENTS и пароли установщик придумать не может. Их приносит
    ; файл «настройки.env» — это обычный .env с рабочего компьютера.
    StrCpy $SettingsSource ""
    IfFileExists "$EXEDIR\настройки.env" 0 try_env
        StrCpy $SettingsSource "$EXEDIR\настройки.env"
        Goto settings_done
    try_env:
    IfFileExists "$EXEDIR\.env" 0 try_downloads
        StrCpy $SettingsSource "$EXEDIR\.env"
        Goto settings_done
    try_downloads:
    IfFileExists "$PROFILE\Downloads\настройки.env" 0 settings_done
        StrCpy $SettingsSource "$PROFILE\Downloads\настройки.env"
    settings_done:

    ; ── Файлы ─────────────────────────────────────────────────────────────
    DetailPrint "Распаковываю Директора в $INSTDIR"
    SetOutPath "$INSTDIR"
    File "bootstrap.ps1"
    File "director.ico"

    SetOutPath "$INSTDIR\app"
    File /r "payload\*.*"

    CreateDirectory "$INSTDIR\app\output"
    CreateDirectory "$INSTDIR\log"

    StrCmp $SettingsSource "" no_settings 0
        DetailPrint "Беру настройки из $SettingsSource"
        ; Прежний файл сносим до копирования. Повторный запуск установщика —
        ; это основной способ заменить настройки: сначала поставили, потом
        ; нашли и положили рядом .env. Полагаться на то, как CopyFiles
        ; поступит с уже существующим файлом, в этом месте нельзя.
        Delete "$INSTDIR\app\.env"
        CopyFiles /SILENT "$SettingsSource" "$INSTDIR\app\.env"
        ; Молча пройти мимо неудавшегося копирования нельзя: человек увидел
        ; бы «нет настроек» и пошёл искать ошибку в файле, которого на месте
        ; просто нет.
        IfFileExists "$INSTDIR\app\.env" settings_copied 0
        DetailPrint "Скопировать настройки не удалось"
    no_settings:
        ; Без настроек Директор не стартует, но всё остальное поставить
        ; можно: человек заполнит файл и откроет ярлык.
        DetailPrint "Настроек нет — кладу заготовку"
        IfFileExists "$INSTDIR\app\.env" settings_copied 0
        CopyFiles /SILENT "$INSTDIR\app\.env.example" "$INSTDIR\app\.env"
    settings_copied:

    ; ── Автозапуск при входе в систему ────────────────────────────────────
    ; Отдельный .cmd, а не прямой вызов powershell: иначе в /TR пришлось бы
    ; складывать вложенные кавычки вокруг аргументов, а на них schtasks
    ; спотыкается.
    FileOpen $0 "$INSTDIR\autostart.cmd" w
    FileWrite $0 "@echo off$\r$\n"
    FileWrite $0 "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $\"%~dp0bootstrap.ps1$\" -Mode autostart$\r$\n"
    FileClose $0

    ; Путь лежит в профиле пользователя, а в имени учётной записи бывает
    ; пробел — «C:\Users\Игорь Москвинов\...». Поэтому кавычки внутри
    ; значения /TR обязательны: без них планировщик при запуске обрежет
    ; команду по первому пробелу.
    ;
    ; /RU не задаём: по умолчанию это текущая учётная запись, а с явным /RU
    ; без пароля schtasks в части случаев требует его ввести. /RL HIGHEST
    ; тоже ни к чему — поднимать права больше незачем.
    DetailPrint "Завожу задание планировщика"
    nsExec::ExecToLog 'schtasks /Create /F /TN "${TASK}" /SC ONLOGON /TR "\"$INSTDIR\autostart.cmd\""'
    Pop $2

    ; ── Ярлыки ────────────────────────────────────────────────────────────
    ; Рабочий стол и меню «Пуск» — того, кто ставит, а не общие: Директор
    ; поставлен в его профиль и работает от его имени.
    CreateShortCut "$DESKTOP\Директор.lnk" \
        "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" \
        '-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\bootstrap.ps1" -Mode open' \
        "$INSTDIR\director.ico" 0 SW_SHOWNORMAL "" "Открыть Директора барбершопа РублЪ"
    CreateDirectory "$SMPROGRAMS\РублЪ Директор"
    CreateShortCut "$SMPROGRAMS\РублЪ Директор\Директор.lnk" \
        "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" \
        '-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\bootstrap.ps1" -Mode open' \
        "$INSTDIR\director.ico" 0
    CreateShortCut "$SMPROGRAMS\РублЪ Директор\Настройки.lnk" \
        "$WINDIR\system32\notepad.exe" '"$INSTDIR\app\.env"'
    CreateShortCut "$SMPROGRAMS\РублЪ Директор\Журнал установки.lnk" \
        "$WINDIR\system32\notepad.exe" '"$INSTDIR\log\bootstrap.log"'

    ; ── Запись в «Программы и компоненты» ─────────────────────────────────
    ; HKCU, а не HKLM: установка пользовательская, и в список программ она
    ; попадает только у того, кто ставил. Права администратора для HKLM у
    ; нас всё равно нет — и не нужны.
    WriteUninstaller "$INSTDIR\Удалить.exe"
    WriteRegStr   HKCU "${REGKEY}" "DisplayName"     "${NAME}"
    WriteRegStr   HKCU "${REGKEY}" "DisplayIcon"     "$INSTDIR\director.ico"
    WriteRegStr   HKCU "${REGKEY}" "DisplayVersion"  "1.0.0"
    WriteRegStr   HKCU "${REGKEY}" "Publisher"       "Барбершоп РублЪ"
    WriteRegStr   HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr   HKCU "${REGKEY}" "UninstallString" '"$INSTDIR\Удалить.exe"'
    WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
    WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1

    ; ── Всё остальное делает bootstrap.ps1 ────────────────────────────────
    DetailPrint ""
    DetailPrint "Дальше всё происходит само: запускается Docker, собирается"
    DetailPrint "Директор, готовится база. Первый раз это несколько минут —"
    DetailPrint "сборка идёт из интернета. Окно можно не трогать."
    DetailPrint ""
    ; /OEM — вывод PowerShell приходит в кодировке консоли, без этого ключа
    ; русские строки в журнале превратились бы в мусор.
    nsExec::ExecToLog /OEM 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\bootstrap.ps1" -Mode install'
    Pop $3

    ; Что получилось — разбираем по коду возврата bootstrap.ps1. Не по тексту:
    ; текст пришлось бы читать из файла в какой-то кодировке, и ради одного
    ; сообщения появилась бы ещё одна поломка.
    StrCmp $3 "0"  report_ok
    StrCmp $3 "10" report_no_settings
    StrCmp $3 "13" report_no_docker
    Goto report_other

    report_ok:
        MessageBox MB_OK|MB_ICONINFORMATION \
            "Директор установлен и запущен.$\r$\n$\r$\nОн уже открыт в браузере: http://localhost:8000$\r$\nЗначок «Директор» есть на рабочем столе.$\r$\n$\r$\nПервая загрузка данных из YCLIENTS займёт несколько минут."
        Goto done

    report_no_settings:
        MessageBox MB_OK|MB_ICONEXCLAMATION \
            "Директор установлен, но не запущен: нет настроек.$\r$\n$\r$\nНужен файл .env с ключами YCLIENTS и паролями — тот же, что на рабочем компьютере. Положите его рядом с этим установщиком под именем «настройки.env» и запустите установку ещё раз.$\r$\n$\r$\nИли заполните его прямо здесь: Пуск → РублЪ Директор → Настройки, а потом откройте ярлык «Директор»."
        Goto done

    report_no_docker:
        MessageBox MB_OK|MB_ICONEXCLAMATION \
            "Директор установлен, но не запущен: на компьютере нет Docker Desktop.$\r$\n$\r$\nПоставьте его — https://www.docker.com/products/docker-desktop/ — и откройте ярлык «Директор» на рабочем столе. Он продолжит с того же места."
        Goto done

    report_other:
        MessageBox MB_OK|MB_ICONEXCLAMATION \
            "Директор установлен, но пока не запустился.$\r$\n$\r$\nОткройте ярлык «Директор» на рабочем столе: он продолжит с того же места и покажет, что мешает.$\r$\n$\r$\nПодробности: $INSTDIR\log\bootstrap.log"

    done:
SectionEnd

Section "Uninstall"
    ; Всё лежит в профиле того, кто ставил, — общий контекст тут не нужен.
    SetShellVarContext current

    DetailPrint "Останавливаю Директора"
    nsExec::ExecToLog 'cmd /c cd /d "$INSTDIR\app\local" && docker compose --env-file "$INSTDIR\app\.env" down'
    Pop $0

    nsExec::ExecToLog 'schtasks /Delete /F /TN "${TASK}"'
    Pop $0

    Delete "$DESKTOP\Директор.lnk"
    RMDir /r "$SMPROGRAMS\РублЪ Директор"

    DeleteRegKey HKCU "${REGKEY}"
    RMDir /r "$INSTDIR"

    ; Данные Директора живут в томе Docker (rubl_data) и намеренно остаются:
    ; выгрузка из YCLIENTS занимает минуты, а удаление тома необратимо.
    ; Убрать его при необходимости: docker volume rm local_rubl_data
    MessageBox MB_OK|MB_ICONINFORMATION \
        "Директор удалён.$\r$\n$\r$\nБаза данных осталась в Docker — при повторной установке всё будет на месте. Docker Desktop не удалялся."
SectionEnd
