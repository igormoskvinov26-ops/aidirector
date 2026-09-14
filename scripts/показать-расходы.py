"""Что YCLIENTS отдаёт по расходам.

Запускается один раз, настоящими ключами, чтобы понять форму ответа: какие
есть статьи, как они называются и на какие суммы. Без этого разбор ответа
пишется вслепую.

Личные данные не печатаются: только названия статей, суммы и даты. Вывод
можно показывать кому угодно.

Запуск — из папки проекта, скрипт скармливается контейнеру на вход, потому
что внутрь образа папка scripts не попадает:

    docker compose -f local/docker-compose.yml --env-file .env \
        exec -T director python - < "scripts/показать-расходы.py"

Без Docker:
    cd backend && python "../scripts/показать-расходы.py"
"""

import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# В контейнере приложение лежит в /app и путь уже верный. Снаружи скрипт
# лежит в scripts/, и backend нужно добавить руками. При запуске через
# стандартный ввод __file__ отсутствует — поэтому через try.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
except NameError:
    pass

from app.api.yclients import YClientsClient  # noqa: E402

# Смотрим прошлый месяц целиком и текущий по сегодня. Прошлый — главный: в нём
# картина полная, и по нему видно, попала ли аренда в выгрузку.
TODAY = date.today()
ПРОШЛЫЙ_НАЧАЛО = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)
ПРОШЛЫЙ_КОНЕЦ = TODAY.replace(day=1) - timedelta(days=1)

# Статьи, ради которых всё затевается. Аренда ведётся отдельной статьёй,
# всё остальное постоянное — в бизнес-расходах.
ОЖИДАЕМЫЕ = ("Аренда", "Бизнес Расходы")


def деньги(значение) -> Decimal:
    try:
        return Decimal(str(значение or 0))
    except Exception:
        return Decimal(0)


def показать_форму(заголовок: str, данные) -> None:
    print("\n" + "=" * 70)
    print(заголовок)
    print("=" * 70)
    if not данные:
        print("  пусто")
        return
    if isinstance(данные, dict):
        print("  ключи ответа:", ", ".join(sorted(данные)[:20]))
        print("\n  первые 2000 знаков:")
        print(json.dumps(данные, ensure_ascii=False, indent=2)[:2000])
        return
    print(f"  записей: {len(данные)}")
    print("  поля одной записи:", ", ".join(sorted(данные[0])))
    print("\n  пример записи:")
    print(json.dumps(данные[0], ensure_ascii=False, indent=2)[:1500])


def статья(строка: dict) -> str | None:
    """Название статьи расхода. Где именно оно лежит — это и выясняем."""
    расход = строка.get("expense")
    if isinstance(расход, dict):
        return расход.get("title") or расход.get("name")
    if isinstance(расход, str) and расход:
        return расход
    for ключ in ("expense_title", "expense_name", "account_title", "comment"):
        значение = строка.get(ключ)
        if isinstance(значение, str) and значение:
            return значение
    return None


def разобрать(заголовок: str, строки: list[dict]) -> None:
    print("\n" + "-" * 70)
    print(заголовок)
    print("-" * 70)

    суммы: dict[str, Decimal] = defaultdict(Decimal)
    количество: dict[str, int] = defaultdict(int)
    без_статьи = 0

    for строка in строки:
        название = статья(строка)
        if not название:
            без_статьи += 1
            continue
        суммы[название] += деньги(строка.get("amount"))
        количество[название] += 1

    if not суммы:
        print(f"  Статей не нашлось. Строк всего: {len(строки)}, без статьи: {без_статьи}.")
        print("  Смотрите пример записи выше — поле называется как-то иначе.")
        return

    print(f"  {'статья':<34}{'сумма':>14}{'операций':>10}")
    for название in sorted(суммы, key=lambda н: abs(суммы[н]), reverse=True)[:30]:
        print(f"  {название[:33]:<34}{суммы[название]:>14,.0f}{количество[название]:>10}")
    if без_статьи:
        print(f"\n  строк без статьи: {без_статьи}")

    print("\n  --- что мы ищем ---")
    for ожидаемая in ОЖИДАЕМЫЕ:
        совпало = [н for н in суммы if ожидаемая.lower() in н.lower()]
        if совпало:
            for н in совпало:
                print(f"    ✓ «{н}»: {суммы[н]:,.0f}")
        else:
            print(f"    ✗ «{ожидаемая}» — не нашлось")


async def выгрузить(client, начало: date, конец: date) -> list[dict]:
    # Имена параметров у этого адреса отличаются от /records/, поэтому
    # пробуем оба написания: какое сработает, то и пойдёт в разбор.
    for параметры in (
        {"start_date": начало.isoformat(), "end_date": конец.isoformat()},
        {"date_from": начало.isoformat(), "date_to": конец.isoformat()},
    ):
        строки = await client._get_paginated(
            f"/transactions/{client.company_id}", params=параметры
        )
        if строки:
            print(f"  сработали параметры: {', '.join(параметры)}")
            return строки
    return []


async def main() -> None:
    async with YClientsClient() as client:
        print(f"Компания: {client.company_id}")
        print(f"Прошлый месяц: {ПРОШЛЫЙ_НАЧАЛО} — {ПРОШЛЫЙ_КОНЕЦ}")
        print(f"Текущий месяц: {TODAY.replace(day=1)} — {TODAY}")

        try:
            отчёт = await client.get_financial_report(
                ПРОШЛЫЙ_НАЧАЛО.isoformat(), ПРОШЛЫЙ_КОНЕЦ.isoformat()
            )
            показать_форму("ФИНАНСОВЫЙ ОТЧЁТ  /reports/finance/  за прошлый месяц", отчёт)
        except Exception as e:
            print(f"\nФинансовый отчёт недоступен: {e}")

        for подпись, начало, конец in (
            ("ПРОШЛЫЙ МЕСЯЦ (в нём картина полная)", ПРОШЛЫЙ_НАЧАЛО, ПРОШЛЫЙ_КОНЕЦ),
            ("ТЕКУЩИЙ МЕСЯЦ (часть расходов может быть не проведена)",
             TODAY.replace(day=1), TODAY),
        ):
            try:
                строки = await выгрузить(client, начало, конец)
                показать_форму(f"ТРАНЗАКЦИИ  /transactions/  {подпись}", строки)
                if строки:
                    разобрать(f"СТАТЬИ РАСХОДА — {подпись}", строки)
            except Exception as e:
                print(f"\nТранзакции за {подпись} недоступны: {e}")


if __name__ == "__main__":
    asyncio.run(main())
