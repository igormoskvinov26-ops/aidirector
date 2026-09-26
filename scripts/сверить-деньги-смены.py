"""Сверка расчёта денег смены с панелью YCLIENTS справа от календаря записей.

Владелец прислал скриншот панели YCLIENTS за день с цифрами «Поступлений в
кассы», «Оплата наличными», «Оплата безналом», «Выполнено на сумму»,
«Записей на сумму», «Товаров на сумму». Наш расчёт в app/services/shift.py
должен приводить к тем же числам (или к объяснимому расхождению — деньги
могли поступить другим днём). Здесь считаем то же самое той же функцией,
что и настоящее закрытие смены, чтобы сравнить цифра к цифре, а не гадать.

Запуск из папки проекта:
    cd backend && uv run python "../scripts/сверить-деньги-смены.py" 2026-09-26
Без даты — берётся сегодняшний день.
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services import shift  # noqa: E402


def рубли(значение) -> str:
    return "нет данных" if значение is None else f"{значение:,.0f} ₽".replace(",", " ")


async def main() -> None:
    день = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else shift.moscow_today()

    открытие = await shift.собрать_открытие(день)
    закрытие = await shift.собрать_закрытие(день)
    деньги = закрытие["money"]

    выполнено = закрытие["services_revenue"] + (закрытие["products_revenue"] or 0)
    поступления = None
    if деньги["non_cash"] is not None and деньги["cash"] is not None:
        поступления = деньги["non_cash"] + деньги["cash"]

    print(f"Дата: {день}\n")
    print("Сверяйте построчно с панелью YCLIENTS за тот же день:")
    print(f"  «Записей на сумму»     ↔ план дня           : {рубли(открытие['plan'])}")
    print(f"  «Выполнено на сумму»   ↔ услуги + товары     : {рубли(выполнено)}")
    print(f"    из них услуги                              : {рубли(закрытие['services_revenue'])}")
    print(f"    из них товары       ↔ «Товаров на сумму»   : {рубли(закрытие['products_revenue'])}")
    print(f"  «Оплата безналом»      ↔ non_cash            : {рубли(деньги['non_cash'])}")
    print(f"  «Оплата наличными»     ↔ cash                : {рубли(деньги['cash'])}")
    print(f"  «Поступлений в кассы»  ↔ нал + безнал        : {рубли(поступления)}")
    print(f"  Потрачено (расход из кассы/счёта)             : {рубли(деньги['spent'])}")

    print("\nПредупреждения расчёта закрытия:")
    for w in закрытие["warnings"]:
        print(f"  - {w}")
    if закрытие["integrity_failures"]:
        print("\nПРОВЕРКИ ЦЕЛОСТНОСТИ НЕ ПРОШЛИ:")
        for f in закрытие["integrity_failures"]:
            print(f"  - {f}")


if __name__ == "__main__":
    asyncio.run(main())
