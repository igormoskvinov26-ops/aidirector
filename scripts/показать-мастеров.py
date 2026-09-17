"""Кто работает в салоне по данным YCLIENTS и какие у них идентификаторы.

Идентификаторы мастеров привязывают учётную запись к человеку: по ним Директор
решает, чью зарплату показать вошедшему. Ошибка в одном числе означает, что
мастер видит чужие деньги. Поэтому числа берутся из YCLIENTS, а не из памяти.

Личные данные не печатаются: только имена сотрудников, их должности и
идентификаторы. Телефонов и клиентов здесь нет.

Запуск из папки проекта:
    cd backend && uv run python "../scripts/показать-мастеров.py"

Если Директор уже работает, проще через его контейнер — там и библиотеки, и
ключи уже на месте, ставить ничего не нужно:
    docker cp scripts/показать-мастеров.py rubl_director:/app/masters.py
    docker exec rubl_director python /app/masters.py

Копировать нужно именно в /app: оттуда Python находит модули приложения.
"""

import asyncio
import os
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
except NameError:
    pass

# Настройки требуют пароль базы и логины входа, а скрипту нужны только ключи
# YCLIENTS. Подставляем заглушки, чтобы хватило трёх ключей.
for имя, заглушка in (
    ("POSTGRES_PASSWORD", "этим-скриптом-база-не-используется"),
    ("OWNER_LOGIN", "не-используется"),
    ("OWNER_PASSWORD", "этим-скриптом-вход-не-используется"),
    ("OPERATOR_LOGIN", "не-используется"),
    ("OPERATOR_PASSWORD", "этим-скриптом-вход-не-используется"),
    ("MASTER_ACCOUNTS", "[]"),
):
    os.environ[имя] = заглушка

try:
    from app.api.yclients import YClientsClient
    from app.config import settings
except Exception as ошибка:
    print("Не удалось прочитать настройки. Заполните в .env три строки:")
    print("    YCLIENTS_PARTNER_TOKEN, YCLIENTS_COMPANY_ID, YCLIENTS_USER_TOKEN")
    print("Угловые скобки из шаблона нужно убрать вместе с текстом внутри.")
    print(f"\nЧто именно не понравилось:\n{ошибка}")
    sys.exit(1)


async def main() -> None:
    async with YClientsClient() as client:
        сотрудники = await client.get_staff()
        работают = await client.get_active_staff()

    if not сотрудники:
        print("YCLIENTS не вернул ни одного сотрудника. Проверьте ключи.")
        sys.exit(1)

    работают_ид = {с.get("id") for с in работают}

    print(f"Филиал {settings.yclients_company_id}, сотрудников всего: {len(сотрудники)}\n")
    print(f"  {'staff_id':<12}{'имя':<24}{'должность':<28}состояние")
    print("  " + "-" * 74)
    for с in сотрудники:
        состояние = "работает" if с.get("id") in работают_ид else "скрыт или уволен"
        print(f"  {с.get('id'):<12}{str(с.get('name') or '')[:23]:<24}"
              f"{str(с.get('specialization') or '')[:27]:<28}{состояние}")

    print("\nДля настроек нужны только строки со состоянием «работает».")
    print("Готовые записи для MASTER_ACCOUNTS в .env, пароли впишите свои:\n")
    записи = ", ".join(
        '{"login":"<логин>","password":"<пароль>","staff_id":' + str(с["id"]) + '}'
        for с in работают
    )
    print(f"  MASTER_ACCOUNTS=[{записи}]")


if __name__ == "__main__":
    asyncio.run(main())
