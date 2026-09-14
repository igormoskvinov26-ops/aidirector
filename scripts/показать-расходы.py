"""Что YCLIENTS отдаёт по расходам.

Запускается один раз, настоящими ключами, чтобы понять форму ответа: какие
есть статьи, как они называются и на какие суммы. Без этого разбор ответа
пишется вслепую.

Личные данные не печатаются: только названия статей, суммы и даты. Вывод
можно показывать кому угодно.

Docker не нужен: скрипту хватает трёх ключей YCLIENTS из .env, база и вход
он не трогает. Запуск из папки проекта:

    cd backend && uv run python "../scripts/показать-расходы.py"

Если Директор уже работает в контейнере, можно и через него — папка scripts
внутрь образа не попадает, поэтому файл подаётся на вход:

    docker compose -f local/docker-compose.yml --env-file .env \
        exec -T director python - < "scripts/показать-расходы.py"
"""

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

# В контейнере приложение лежит в /app и путь уже верный. Снаружи скрипт
# лежит в scripts/, и backend нужно добавить руками. При запуске через
# стандартный ввод __file__ отсутствует — поэтому через try.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
except NameError:
    pass

# Настройки приложения требуют пароли к базе, логины входа и учётные записи
# мастеров. Скрипту не нужно ничего из этого: он только спрашивает YCLIENTS.
# Подставляем заглушки, чтобы для запуска хватило трёх ключей, а не всего
# .env целиком. Ключи YCLIENTS здесь не трогаются — они читаются как обычно.
for имя, заглушка in (
    ("POSTGRES_PASSWORD", "этим-скриптом-база-не-используется"),
    ("OWNER_LOGIN", "не-используется"),
    ("OWNER_PASSWORD", "этим-скриптом-вход-не-используется"),
    ("OPERATOR_LOGIN", "не-используется"),
    ("OPERATOR_PASSWORD", "этим-скриптом-вход-не-используется"),
    ("MASTER_ACCOUNTS", "[]"),
):
    os.environ[имя] = заглушка

ПОДСКАЗКА = (
    "Заполните в файле .env три строки:\n"
    "    YCLIENTS_PARTNER_TOKEN=\n"
    "    YCLIENTS_COMPANY_ID=\n"
    "    YCLIENTS_USER_TOKEN=\n"
    "\n"
    "Угловые скобки из шаблона нужно убрать — это пометка «сюда вписать»,\n"
    "а не часть значения. Должно получиться YCLIENTS_COMPANY_ID=2387007,\n"
    "а не YCLIENTS_COMPANY_ID=<2387007>.\n"
    "\n"
    "Остальное этому скрипту не нужно: базу и вход он не трогает.\n"
    "Ключи лежат в настройках YCLIENTS или в .env работающей установки."
)

# Настройки проверяются при загрузке, и незаполненный .env роняет импорт
# ещё до первой строки main. Трейсбек pydantic человеку ничего не говорит,
# поэтому ошибку перехватываем здесь и объясняем словами.
try:
    from app.api.yclients import YClientsClient
    from app.config import settings
except Exception as ошибка:  # noqa: BLE001 — причина печатается целиком
    print("Не удалось прочитать настройки.\n")
    print(ПОДСКАЗКА)
    print(f"\nЧто именно не понравилось:\n{ошибка}")
    sys.exit(1)


def проверить_ключи() -> bool:
    """Сказать прямо, каких ключей не хватает, вместо невнятной ошибки."""
    пусто = [
        имя
        for имя, значение in (
            ("YCLIENTS_PARTNER_TOKEN", settings.yclients_partner_token),
            ("YCLIENTS_USER_TOKEN", settings.yclients_user_token),
        )
        if not значение or значение.startswith("<")
    ]
    if not settings.yclients_company_id:
        пусто.append("YCLIENTS_COMPANY_ID")
    if пусто:
        print("В файле .env не заполнены ключи YCLIENTS:")
        for имя in пусто:
            print(f"    {имя}")
        print("\n" + ПОДСКАЗКА)
        return False
    return True

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


# В коде живут два написания адреса транзакций, и какое из них настоящее —
# выясняется здесь, а не гаданием. Имена параметров дат у разных адресов тоже
# расходятся, поэтому перебираются оба.
АДРЕСА = (
    "/transactions/{id}",
    "/storages/transactions/{id}",
    "/company/{id}/transactions",
)
ПАРАМЕТРЫ = ("start_date/end_date", "date_from/date_to")


def _даты(вид: str, начало: date, конец: date) -> dict:
    если_первый = вид.startswith("start")
    return {
        ("start_date" if если_первый else "date_from"): начало.isoformat(),
        ("end_date" if если_первый else "date_to"): конец.isoformat(),
    }


async def проверить_доступ(client) -> None:
    """Видит ли ключ этот филиал вообще.

    Без этого 404 читается двусмысленно: то ли адрес не тот, то ли у ключа нет
    прав на филиал. Разница решающая — во втором случае не заработает и сам
    Директор, а не только этот скрипт.
    """
    print("\n" + "=" * 70)
    print("ДОСТУП: какие филиалы видит ключ")
    print("=" * 70)
    try:
        ответ = await client._get("/companies", params={"my": 1})
    except Exception as e:
        print(f"  спросить не удалось: {e}")
        return

    филиалы = ответ.get("data") or []
    if not филиалы:
        print("  Ключ не видит НИ ОДНОГО филиала.")
        print("  Значит дело в пользовательском токене, а не в адресах ниже.")
        print("  С таким токеном не заработает и сам Директор: он ходит теми же")
        print("  ключами. Возьмите рабочую тройку из .env установки на сервере.")
        return

    print(f"  доступно филиалов: {len(филиалы)}")
    for филиал in филиалы:
        отметка = "  <-- указан в .env" if филиал.get("id") == client.company_id else ""
        print(f"    {филиал.get('id')}  {филиал.get('title') or ''}{отметка}")

    if not any(ф.get("id") == client.company_id for ф in филиалы):
        print(f"\n  Филиала {client.company_id} среди них нет — впишите в .env один")
        print("  из перечисленных выше, иначе все запросы ниже отвечают 404.")


async def выгрузить(client, начало: date, конец: date) -> list[dict]:
    """Перебрать адреса и наборы параметров, показав, что ответил каждый."""
    print(f"  выгружаю {начало} — {конец}, это может занять до минуты...", flush=True)
    for шаблон in АДРЕСА:
        путь = шаблон.format(id=client.company_id)
        for вид in ПАРАМЕТРЫ:
            try:
                строки = await client._get_paginated(путь, params=_даты(вид, начало, конец))
            except httpx.HTTPStatusError as e:
                print(f"  {путь}  ({вид}): код {e.response.status_code}")
                # Код одинаков для обоих наборов параметров, если адреса нет.
                if e.response.status_code == 404:
                    break
                continue
            except Exception as e:
                print(f"  {путь}  ({вид}): {type(e).__name__}")
                continue

            if строки:
                print(f"  {путь}  ({вид}): записей {len(строки)}  <-- рабочий")
                return строки
            print(f"  {путь}  ({вид}): пусто")
    return []


async def main() -> None:
    async with YClientsClient() as client:
        print(f"Компания: {client.company_id}")
        print(f"Прошлый месяц: {ПРОШЛЫЙ_НАЧАЛО} — {ПРОШЛЫЙ_КОНЕЦ}")
        print(f"Текущий месяц: {TODAY.replace(day=1)} — {TODAY}")

        await проверить_доступ(client)

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
    if проверить_ключи():
        asyncio.run(main())
