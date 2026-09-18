; ==========================================================================
;  Установщик Директора для Windows.
;
;  Собирается из Linux командой installer/build.sh (makensis из пакета nsis).
;  Результат — один файл «РублЪ-Директор-Установка.exe».
;
;  Что он делает после двойного щелчка и одного подтверждения прав:
;    1. распаковывает исходники Директора в C:\ProgramData\RublDirector\app;
;    2. кладёт туда настройки (файл «настройки.env» рядом с установщиком);
;    3. ставит Docker Desktop в тихом режиме, если его нет;
;    4. собирает образ, поднимает контейнеры, обновляет структуру базы;
;    5. заводит задание планировщика, чтобы Директор поднимался при входе;
;    6. создаёт ярлык на рабочем столе и открывает браузер.
;
;  Прав администратора требует сам Docker Desktop: без них не установить
;  его службу и не включить WSL2. Одно окно UAC при запуске — это всё,
;  что требуется от человека.
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
RequestExecutionLevel admin
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
    ; ProgramData, а не Program Files: там лежит и код, и контекст сборки
    ; Docker, и журнал. SetShellVarContext all переводит $APPDATA именно туда.
    SetShellVarContext all
    StrCpy $INSTDIR "$APPDATA\RublDirector"
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
        CopyFiles /SILENT "$SettingsSource" "$INSTDIR\app\.env"
        Goto settings_copied
    no_settings:
        ; Без настроек Директор не стартует, но всё остальное поставить
        ; можно: человек заполнит файл и откроет ярлык.
        DetailPrint "Файл настроек не найден — кладу заготовку"
        IfFileExists "$INSTDIR\app\.env" settings_copied 0
        CopyFiles /SILENT "$INSTDIR\app\.env.example" "$INSTDIR\app\.env"
    settings_copied:

    ; ── Автозапуск при входе в систему ────────────────────────────────────
    ; Отдельный .cmd, а не прямой вызов powershell: так в /TR попадает путь
    ; без пробелов и без вложенных кавычек, на которых schtasks спотыкается.
    FileOpen $0 "$INSTDIR\autostart.cmd" w
    FileWrite $0 "@echo off$\r$\n"
    FileWrite $0 "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $\"%~dp0bootstrap.ps1$\" -Mode autostart$\r$\n"
    FileClose $0

    UserInfo::GetName
    Pop $1
    DetailPrint "Завожу задание планировщика для учётной записи $1"
    nsExec::ExecToLog 'schtasks /Create /F /TN "${TASK}" /SC ONLOGON /RU "$1" /RL HIGHEST /TR "$INSTDIR\autostart.cmd"'
    Pop $2

    ; ── Ярлыки ────────────────────────────────────────────────────────────
    ; Рабочий стол — того, кто ставит, а не общий: ярлык открывает Директора
    ; от его имени.
    SetShellVarContext current
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
    SetShellVarContext all

    ; ── Запись в «Программы и компоненты» ─────────────────────────────────
    WriteUninstaller "$INSTDIR\Удалить.exe"
    WriteRegStr   HKLM "${REGKEY}" "DisplayName"     "${NAME}"
    WriteRegStr   HKLM "${REGKEY}" "DisplayIcon"     "$INSTDIR\director.ico"
    WriteRegStr   HKLM "${REGKEY}" "DisplayVersion"  "1.0.0"
    WriteRegStr   HKLM "${REGKEY}" "Publisher"       "Барбершоп РублЪ"
    WriteRegStr   HKLM "${REGKEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr   HKLM "${REGKEY}" "UninstallString" '"$INSTDIR\Удалить.exe"'
    WriteRegDWORD HKLM "${REGKEY}" "NoModify" 1
    WriteRegDWORD HKLM "${REGKEY}" "NoRepair" 1

    ; ── Всё остальное делает bootstrap.ps1 ────────────────────────────────
    DetailPrint ""
    DetailPrint "Дальше всё происходит само. Это долго: если Docker ещё не"
    DetailPrint "установлен, его надо скачать (около 600 МБ) и поставить,"
    DetailPrint "а потом собрать сам Директор. Окно можно не трогать."
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
    StrCmp $3 "11" report_reboot
    Goto report_other

    report_ok:
        MessageBox MB_OK|MB_ICONINFORMATION \
            "Директор установлен и запущен.$\r$\n$\r$\nОн уже открыт в браузере: http://localhost:8000$\r$\nЗначок «Директор» есть на рабочем столе.$\r$\n$\r$\nПервая загрузка данных из YCLIENTS займёт несколько минут."
        Goto done

    report_no_settings:
        MessageBox MB_OK|MB_ICONEXCLAMATION \
            "Директор установлен, но не запущен: нет настроек.$\r$\n$\r$\nНужен файл .env с ключами YCLIENTS и паролями — тот же, что на рабочем компьютере. Положите его рядом с этим установщиком под именем «настройки.env» и запустите установку ещё раз.$\r$\n$\r$\nИли заполните его прямо здесь: Пуск → РублЪ Директор → Настройки, а потом откройте ярлык «Директор»."
        Goto done

    report_reboot:
        MessageBox MB_OK|MB_ICONINFORMATION \
            "Docker установлен, нужна перезагрузка компьютера.$\r$\n$\r$\nПерезагрузите — дальше всё произойдёт само: при входе в систему Директор соберётся и запустится. Это займёт несколько минут, значок «Директор» на рабочем столе покажет, готов ли он."
        Goto done

    report_other:
        MessageBox MB_OK|MB_ICONEXCLAMATION \
            "Директор установлен, но пока не запустился.$\r$\n$\r$\nОткройте ярлык «Директор» на рабочем столе: он продолжит с того же места и покажет, что мешает.$\r$\n$\r$\nПодробности: $INSTDIR\log\bootstrap.log"

    done:
SectionEnd

Section "Uninstall"
    SetShellVarContext all

    DetailPrint "Останавливаю Директора"
    nsExec::ExecToLog 'cmd /c cd /d "$INSTDIR\app\local" && docker compose --env-file "$INSTDIR\app\.env" down'
    Pop $0

    nsExec::ExecToLog 'schtasks /Delete /F /TN "${TASK}"'
    Pop $0

    SetShellVarContext current
    Delete "$DESKTOP\Директор.lnk"
    RMDir /r "$SMPROGRAMS\РублЪ Директор"
    SetShellVarContext all

    DeleteRegKey HKLM "${REGKEY}"
    RMDir /r "$INSTDIR"

    ; Данные Директора живут в томе Docker (rubl_data) и намеренно остаются:
    ; выгрузка из YCLIENTS занимает минуты, а удаление тома необратимо.
    ; Убрать его при необходимости: docker volume rm local_rubl_data
    MessageBox MB_OK|MB_ICONINFORMATION \
        "Директор удалён.$\r$\n$\r$\nБаза данных осталась в Docker — при повторной установке всё будет на месте. Docker Desktop не удалялся."
SectionEnd
