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

# Как в YCLIENTS может называться способ оплаты и признак расхода. Первый
# прогон 26.09.2026 на живом филиале показал: верхнего уровня полей из этого
# списка нет ни одного — зато есть вложенные словари account и expense,
# которые этот список и должен был найти. Их разворачиваем отдельно ниже.
КАНДИДАТЫ_ОПЛАТЫ = [
    "account_id", "expense_id", "payment_type", "payment_method",
    "is_cash", "cash", "kassa_id", "type", "type_id",
]

# Вложенные словари транзакции, где, судя по всему, и живёт способ оплаты
# (account) и категория операции (expense).
ВЛОЖЕННЫЕ = ("account", "expense", "client", "master", "supplier")


def значение(ключ: str, знач: object) -> str:
    if ключ.lower() in ЛИЧНОЕ:
        return "***" if знач else "(пусто)"
    if isinstance(знач, (dict, list)):
        return f"<{type(знач).__name__}, {len(знач)} элементов>"
    return repr(знач)


async def main() -> None:
    сегодня = date.today()
    # Окно шире первого прогона: за 7 дней попались только продажи услуг и
    # товаров — ни одной настоящей траты из кассы. Расход может случаться
    # реже продаж, и его проще поймать на месяце.
    с, по = сегодня - timedelta(days=30), сегодня

    async with YClientsClient() as client:
        print(f"Филиал {client.company_id}, транзакции с {с} по {по}\n")

        ответ = await client._get(
            f"/transactions/{client.company_id}",
            {"start_date": с.isoformat(), "end_date": по.isoformat(), "count": 200, "page": 1},
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

            print("\n── ПОХОЖЕЕ НА СПОСОБ ОПЛАТЫ ИЛИ РАСХОД (ВЕРХНИЙ УРОВЕНЬ) ─")
            найдено = [к for к in КАНДИДАТЫ_ОПЛАТЫ if к in строка]
            if найдено:
                for к in найдено:
                    print(f"  ЕСТЬ  {к} = {значение(к, строка[к])}")
            else:
                print("  Ни одного из ожидаемых имён нет:")
                print("  " + ", ".join(КАНДИДАТЫ_ОПЛАТЫ))

            # Главное: то, что верхний уровень не показал, может лежать
            # внутри вложенных словарей — их и разворачиваем целиком.
            for ключ_словаря in ВЛОЖЕННЫЕ:
                вложенный = строка.get(ключ_словаря)
                if isinstance(вложенный, dict) and вложенный:
                    print(f"\n── ПОЛЯ ВНУТРИ «{ключ_словаря}» ────────────────")
                    for под_ключ in sorted(вложенный):
                        print(f"  {под_ключ:24} = {значение(под_ключ, вложенный[под_ключ])}")
                elif isinstance(вложенный, list) and вложенный and isinstance(вложенный[0], dict):
                    print(f"\n── ПОЛЯ ВНУТРИ «{ключ_словаря}[0]» ──────────────")
                    for под_ключ in sorted(вложенный[0]):
                        print(f"  {под_ключ:24} = {значение(под_ключ, вложенный[0][под_ключ])}")

            print("\n── РАЗНООБРАЗИЕ ПО ВСЕМ ТРАНЗАКЦИЯМ ──────────────")
            сводка: dict[object, int] = {}
            for т in транзакции:
                счёт = т.get("account") or {}
                расход = т.get("expense") or {}
                ключ = (
                    т.get("sold_item_type"),
                    счёт.get("title") or счёт.get("id"),
                    расход.get("title") or расход.get("id"),
                )
                сводка[ключ] = сводка.get(ключ, 0) + 1
            print("  (sold_item_type, account, expense) → сколько транзакций")
            for ключ, сколько in sorted(сводка.items(), key=lambda p: -p[1]):
                print(f"  {ключ} → {сколько}")

            # Расход — это трата из кассы, а не продажа. Ищем то, что на
            # продажу не похоже: отрицательную сумму или sold_item_type вне
            # уже известных «service» и «goods_transaction».
            расходная = next(
                (
                    т
                    for т in транзакции
                    if float(т.get("amount") or 0) < 0
                    or т.get("sold_item_type") not in ("service", "goods_transaction")
                ),
                None,
            )
            print("\n── ПОХОЖЕ НА НАСТОЯЩИЙ РАСХОД ─────────────────────")
            if расходная is None:
                print("  За это окно ни одной такой транзакции не нашлось.")
            else:
                for ключ in sorted(расходная):
                    print(f"  {ключ:24} = {значение(ключ, расходная[ключ])}")
                for ключ_словаря in ВЛОЖЕННЫЕ:
                    вложенный = расходная.get(ключ_словаря)
                    if isinstance(вложенный, dict) and вложенный:
                        print(f"  ── внутри «{ключ_словаря}» ──")
                        for под_ключ in sorted(вложенный):
                            print(f"    {под_ключ:22} = {значение(под_ключ, вложенный[под_ключ])}")

        # Список касс/счетов компании — если YCLIENTS вообще отдаёт такой
        # адрес. 404 здесь — это ответ, а не сбой: значит, остатки в кассе и
        # на счёте взять неоткуда, кроме собственного расчёта проекта.
        print("\n── СПИСОК КАСС/СЧЕТОВ КОМПАНИИ ───────────────────")
        for путь in (f"/accounts/{client.company_id}", f"/company/{client.company_id}/accounts"):
            try:
                ответ_счетов = await client._get(путь)
            except Exception as сбой:  # noqa: BLE001
                print(f"  {путь} → недоступен: {type(сбой).__name__}: {сбой}")
                continue
            счета = ответ_счетов.get("data") if isinstance(ответ_счетов, dict) else ответ_счетов
            if not isinstance(счета, list) or not счета:
                print(f"  {путь} → ответ без списка: {значение('ответ', ответ_счетов)}")
                continue
            print(f"  {путь} → {len(счета)} счёт(ов)")
            for счёт in счета:
                print("    ── один счёт ──")
                for под_ключ in sorted(счёт):
                    print(f"      {под_ключ:22} = {значение(под_ключ, счёт[под_ключ])}")

    print("\nГотово. Пришлите этот вывод целиком.")


if __name__ == "__main__":
    asyncio.run(main())
