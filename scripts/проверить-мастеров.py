"""Показать учётные записи мастеров из .env. Пароли не печатаются.

Проверяются оба возможных места: папка проекта и папка первой установки.
Пустой список — такой же ответ, как отсутствие строки, и молчать о нём
нельзя: именно на этом проверка 17.09.2026 прошла впустую.
"""
import json
import re
from pathlib import Path

ОЖИДАЕТСЯ = {5659614: "Ксения", 5659611: "Арташ", 5659617: "Дима"}

for файл in (Path.home() / "aidirector/.env", Path.home() / "rubl-director/.env"):
    print(f"\n=== {файл} ===")
    if not файл.is_file():
        print("  файла нет")
        continue
    строка = re.search(
        r"^MASTER_ACCOUNTS=(.*)$", файл.read_text(encoding="utf-8"), re.M
    )
    if not строка:
        print("  строки MASTER_ACCOUNTS нет вовсе")
        continue
    try:
        записи = json.loads(строка.group(1))
    except ValueError as сбой:
        print(f"  строка есть, но не читается как список: {сбой}")
        continue
    if not записи:
        print("  список ПУСТ — мастера войти не смогут")
        continue
    for запись in записи:
        ид = запись.get("staff_id")
        кто = ОЖИДАЕТСЯ.get(ид, "НЕ СОВПАДАЕТ с подтверждённым списком")
        длина = len(str(запись.get("password", "")))
        пометка = "" if длина >= 12 else "  ← короче 12 символов, не запустится"
        print(f"  {запись.get('login', '?'):10} staff_id {ид}  {кто}"
              f"  пароль {длина} симв.{пометка}")
