"""Что YCLIENTS отдаёт по расходам.

Запускается один раз, настоящими ключами, чтобы понять форму ответа: какие
есть статьи, как они называются, чем расход отличается от прихода. Без этого
разбор ответа пишется вслепую.

Личные данные не печатаются: только названия статей, суммы и даты. Вывод
можно показывать кому угодно.

Запуск, из папки проекта:
    docker compose -f local/docker-compose.yml --env-file .env \
        exec -T director python /app/../scripts/показать-расходы.py

Или, если запускаете без Docker:
    cd backend && python ../scripts/показать-расходы.py
"""

import asyncio
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.api.yclients import YClientsClient  # noqa: E402

# Смотрим прошлый и текущий месяц: в текущем часть расходов может быть ещё
# не проведена, а в прошлом картина полная.
TODAY = date.today()
START = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)


def показать(заголовок: str, данные) -> None:
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
    if данные:
        print("  поля одной записи:", ", ".join(sorted(данные[0])))
        print("\n  пример записи:")
        print(json.dumps(данные[0], ensure_ascii=False, indent=2)[:1200])


async def main() -> None:
    async with YClientsClient() as client:
        print(f"Период: {START} — {TODAY}")

        try:
            отчёт = await client.get_financial_report(START.isoformat(), TODAY.isoformat())
            показать("ФИНАНСОВЫЙ ОТЧЁТ  /reports/finance/", отчёт)
        except Exception as e:
            print(f"\nФинансовый отчёт недоступен: {e}")

        try:
            # Тот же адрес, что используется для продаж косметики.
            сделки = await client._get_paginated(
                f"/transactions/{client.company_id}",
                params={"start_date": START.isoformat(), "end_date": TODAY.isoformat()},
            )
            показать("ТРАНЗАКЦИИ  /transactions/", сделки)

            if сделки:
                print("\n  --- что встречается в поле expense ---")
                статьи = Counter()
                for строка in сделки:
                    расход = строка.get("expense") or {}
                    название = расход.get("title") if isinstance(расход, dict) else расход
                    if название:
                        статьи[str(название)] += 1
                for название, сколько in статьи.most_common(30):
                    print(f"    {название}: {сколько} операций")
                if not статьи:
                    print("    поля expense в ответе нет — ищите статью в других полях выше")
        except Exception as e:
            print(f"\nТранзакции недоступны: {e}")


if __name__ == "__main__":
    asyncio.run(main())
