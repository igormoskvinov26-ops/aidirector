"""Какие поля на самом деле приходят в записи YCLIENTS.

Нужен для модуля «Открытие/закрытие смены»: в ТЗ сказано не угадывать имена
полей API, а подтвердить их на реальных ответах. Главный вопрос — есть ли у
записи дата СОЗДАНИЯ (не дата визита). От неё зависит показатель «создано
сегодня на будущие даты»: без такого поля его нельзя посчитать честно.

Персональные данные не печатаются. Имя, телефон, почта и комментарии
заменяются на «***»: вывод этого скрипта отправляется в переписку.

Запуск из папки проекта:
    cd backend && uv run python "../scripts/показать-поля-записи.py"
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.api.yclients import YClientsClient  # noqa: E402

# Ключи, значения которых не показываем никогда.
ЛИЧНОЕ = {
    "name", "phone", "email", "comment", "client_comment", "surname",
    "patronymic", "full_name", "display_name", "text", "notes",
}

# Что ищем: как в YCLIENTS может называться дата создания записи.
КАНДИДАТЫ_СОЗДАНИЯ = [
    "create_date", "created_at", "created", "datetime_create", "date_create",
    "creation_date", "created_date", "record_created", "add_date",
]


def значение(ключ: str, знач: object) -> str:
    if ключ.lower() in ЛИЧНОЕ:
        return "***" if знач else "(пусто)"
    if isinstance(знач, (dict, list)):
        return f"<{type(знач).__name__}, {len(знач)} элементов>"
    return repr(знач)


async def main() -> None:
    сегодня = date.today()
    # Окно захватывает и прошедшие визиты, и будущие записи: нужны оба вида.
    с, по = сегодня - timedelta(days=7), сегодня + timedelta(days=7)

    async with YClientsClient() as client:
        print(f"Филиал {client.company_id}, записи с {с} по {по}\n")
        # Тот же вызов, которым каждый день ходят «Записи за месяц»
        # (barber_month.pages). Метод get_records() из клиента намеренно НЕ
        # используется: его не вызывает ни один модуль проекта, и имена
        # параметров у него другие (date_from вместо start_date) — проверять
        # поля непроверенным путём значит проверять не то.
        ответ = await client._get(
            f"/records/{client.company_id}",
            {"start_date": с.isoformat(), "end_date": по.isoformat(),
             "count": 50, "page": 1},
        )

    записи = ответ.get("data") if isinstance(ответ, dict) else ответ
    if not isinstance(записи, list) or not записи:
        print("YCLIENTS не вернул ни одной записи за это окно.")
        print("Ответ целиком (без личных данных):", значение("ответ", ответ))
        sys.exit(1)

    print(f"Получено записей: {len(записи)}\n")

    # 1. Все поля записи — это и есть ответ на «не угадывать имена полей».
    запись = записи[0]
    print("── ПОЛЯ ОДНОЙ ЗАПИСИ ─────────────────────────────")
    for ключ in sorted(запись):
        print(f"  {ключ:24} = {значение(ключ, запись[ключ])}")

    # 2. Главный вопрос: есть ли дата создания.
    print("\n── ДАТА СОЗДАНИЯ ЗАПИСИ ──────────────────────────")
    найдено = [к for к in КАНДИДАТЫ_СОЗДАНИЯ if к in запись]
    if найдено:
        for к in найдено:
            print(f"  ЕСТЬ  {к} = {запись[к]!r}")
    else:
        print("  НЕТ ни одного из ожидаемых имён:")
        print("  " + ", ".join(КАНДИДАТЫ_СОЗДАНИЯ))
        похожие = [к for к in запись if "creat" in к.lower() or "add" in к.lower()]
        print(f"  Похожие по названию поля: {похожие or 'нет'}")

    # 3. Состав услуг и стоимость: подтверждаем cost_to_pay.
    print("\n── ПОЛЯ УСЛУГИ ВНУТРИ ЗАПИСИ ─────────────────────")
    услуги = запись.get("services") or []
    с_услугами = запись if услуги else next(
        (з for з in записи if з.get("services")), None
    )
    if с_услугами and с_услугами.get("services"):
        услуга = с_услугами["services"][0]
        for ключ in sorted(услуга):
            print(f"  {ключ:24} = {значение(ключ, услуга[ключ])}")
    else:
        print("  Ни в одной записи окна нет услуг — показать нечего.")

    # 4. Клиент внутри записи: нужен только стабильный id.
    print("\n── ПОЛЯ КЛИЕНТА ВНУТРИ ЗАПИСИ ────────────────────")
    клиент = запись.get("client")
    if isinstance(клиент, dict):
        for ключ in sorted(клиент):
            print(f"  {ключ:24} = {значение(ключ, клиент[ключ])}")
    else:
        print(f"  client = {значение('client', клиент)}")

    # 5. Статусы посещения: по ним считаются «выполнено» и «не пришёл».
    print("\n── КАКИЕ ВСТРЕЧАЮТСЯ ПРИЗНАКИ ПОСЕЩЕНИЯ ──────────")
    сводка: dict[object, int] = {}
    for з in записи:
        ключ = (з.get("visit_attendance"), з.get("attendance"), з.get("deleted"))
        сводка[ключ] = сводка.get(ключ, 0) + 1
    print("  (visit_attendance, attendance, deleted) → сколько записей")
    for ключ, сколько in sorted(сводка.items(), key=lambda p: -p[1]):
        print(f"  {ключ} → {сколько}")

    print("\nГотово. Пришлите этот вывод целиком — по нему настрою расчёты.")


if __name__ == "__main__":
    asyncio.run(main())
