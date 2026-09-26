"""Какие поля YCLIENTS отвечают за способ оплаты и расходы из кассы.

Нужен для блока «Деньги» в закрытии смены: «безнал / наличка» и «потрачено»
там сейчас стоят как «данные недоступны», потому что имя нужного поля не
подтверждено на живом API — а угадывать его ТЗ смены запрещает (§39).

Смотрим на /transactions/ — тот же адрес, которым уже пользуется проект для
подсчёта продажи товаров (app/services/barber_month.py:load_products), и на
список касс/счетов компании, если YCLIENTS вообще его отдаёт.

Персональные данные не печатаются.

Запуск из папки проекта:
    cd backend && uv run python "../scripts/показать-поля-денег.py"
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.api.yclients import YClientsClient  # noqa: E402

ЛИЧНОЕ = {"name", "phone", "email", "comment", "client_comment", "full_name", "text"}

# Как в YCLIENTS может называться способ оплаты и признак расхода.
КАНДИДАТЫ_ОПЛАТЫ = [
    "account_id", "expense_id", "payment_type", "payment_method",
    "is_cash", "cash", "kassa_id", "type", "type_id",
]


def значение(ключ: str, знач: object) -> str:
    if ключ.lower() in ЛИЧНОЕ:
        return "***" if знач else "(пусто)"
    if isinstance(знач, (dict, list)):
        return f"<{type(знач).__name__}, {len(знач)} элементов>"
    return repr(знач)


async def main() -> None:
    сегодня = date.today()
    с, по = сегодня - timedelta(days=7), сегодня

    async with YClientsClient() as client:
        print(f"Филиал {client.company_id}, транзакции с {с} по {по}\n")

        ответ = await client._get(
            f"/transactions/{client.company_id}",
            {"start_date": с.isoformat(), "end_date": по.isoformat(), "count": 50, "page": 1},
        )
        транзакции = ответ.get("data") if isinstance(ответ, dict) else ответ
        if not isinstance(транзакции, list) or not транзакции:
            print("YCLIENTS не вернул ни одной транзакции за это окно.")
            print("Ответ целиком (без личных данных):", значение("ответ", ответ))
        else:
            print(f"Получено транзакций: {len(транзакции)}\n")
            print("── ПОЛЯ ОДНОЙ ТРАНЗАКЦИИ ─────────────────────────")
            строка = транзакции[0]
            for ключ in sorted(строка):
                print(f"  {ключ:24} = {значение(ключ, строка[ключ])}")

            print("\n── ПОХОЖЕЕ НА СПОСОБ ОПЛАТЫ ИЛИ РАСХОД ───────────")
            найдено = [к for к in КАНДИДАТЫ_ОПЛАТЫ if к in строка]
            if найдено:
                for к in найдено:
                    print(f"  ЕСТЬ  {к} = {значение(к, строка[к])}")
            else:
                print("  Ни одного из ожидаемых имён нет:")
                print("  " + ", ".join(КАНДИДАТЫ_ОПЛАТЫ))

            print("\n── РАЗНООБРАЗИЕ ПОЛЕЙ TYPE_ID / EXPENSE ПО ВСЕМ ──")
            сводка: dict[object, int] = {}
            for т in транзакции:
                ключ = (т.get("type_id"), т.get("expense_id"), т.get("account_id"))
                сводка[ключ] = сводка.get(ключ, 0) + 1
            print("  (type_id, expense_id, account_id) → сколько транзакций")
            for ключ, сколько in sorted(сводка.items(), key=lambda p: -p[1]):
                print(f"  {ключ} → {сколько}")

        # Список касс/счетов компании — если YCLIENTS вообще отдаёт такой
        # адрес. 404 здесь — это ответ, а не сбой: значит, остатки в кассе и
        # на счёте взять неоткуда, кроме собственного расчёта проекта.
        print("\n── СПИСОК КАСС/СЧЕТОВ КОМПАНИИ ───────────────────")
        for путь in (f"/accounts/{client.company_id}", f"/company/{client.company_id}/accounts"):
            try:
                счета = await client._get(путь)
                print(f"  {путь} → {значение('accounts', счета)}")
            except Exception as сбой:  # noqa: BLE001
                print(f"  {путь} → недоступен: {type(сбой).__name__}: {сбой}")

    print("\nГотово. Пришлите этот вывод целиком.")


if __name__ == "__main__":
    asyncio.run(main())
