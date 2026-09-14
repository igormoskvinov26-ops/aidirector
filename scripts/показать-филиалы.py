"""Какой у салона company_id.

Спрашивает YCLIENTS, к каким филиалам подходят ваши ключи, и печатает их
номера. Нужен, когда YCLIENTS_COMPANY_ID ещё не заполнен: остальные скрипты
без него не запускаются.

Приложение здесь не используется вовсе — читаются только два токена из .env,
поэтому скрипт работает на наполовину заполненном файле настроек.

Запуск из папки проекта:
    cd backend && uv run python "../scripts/показать-филиалы.py"
"""

import asyncio
import sys
from pathlib import Path

import httpx

BASE_URL = "https://api.yclients.com/api/v1"


def найти_env() -> Path | None:
    """Файл .env лежит в корне проекта, рядом с папками backend и scripts."""
    кандидаты = []
    try:
        кандидаты.append(Path(__file__).resolve().parent.parent / ".env")
    except NameError:
        pass
    кандидаты += [Path.cwd() / ".env", Path.cwd().parent / ".env"]
    return next((p for p in кандидаты if p.is_file()), None)


def прочитать_токены(путь: Path) -> tuple[str, str]:
    """Разбор .env вручную: настройки приложения требуют company_id, а его-то
    мы и ищем."""
    значения: dict[str, str] = {}
    for строка in путь.read_text(encoding="utf-8").splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("#") or "=" not in строка:
            continue
        ключ, _, значение = строка.partition("=")
        значения[ключ.strip()] = значение.strip().strip('"').strip("'")
    return (
        значения.get("YCLIENTS_PARTNER_TOKEN", ""),
        значения.get("YCLIENTS_USER_TOKEN", ""),
    )


async def main() -> None:
    путь = найти_env()
    if путь is None:
        print("Файл .env не найден. Запускайте из папки проекта:")
        print('    cd backend && uv run python "../scripts/показать-филиалы.py"')
        sys.exit(1)

    партнёр, пользователь = прочитать_токены(путь)
    незаполнены = [
        имя
        for имя, значение in (
            ("YCLIENTS_PARTNER_TOKEN", партнёр),
            ("YCLIENTS_USER_TOKEN", пользователь),
        )
        if not значение or значение.startswith("<")
    ]
    if незаполнены:
        print(f"В файле {путь} не заполнены:")
        for имя in незаполнены:
            print(f"    {имя}")
        print("\nБез этих двух токенов спросить номер филиала не у кого.")
        print("Угловые скобки из шаблона уберите: это пометка «сюда вписать».")
        sys.exit(1)

    заголовки = {
        "Authorization": f"Bearer {партнёр}, User {пользователь}",
        "Accept": "application/vnd.yclients.v2+json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # my=1 — только те филиалы, к которым подходит пользовательский токен.
        ответ = await client.get("/companies", params={"my": 1}, headers=заголовки)
        if ответ.status_code == 401:
            print("YCLIENTS не принял ключи (401). Проверьте оба токена в .env.")
            sys.exit(1)
        ответ.raise_for_status()
        филиалы = ответ.json().get("data") or []

    if not филиалы:
        print("Ключи приняты, но ни одного филиала не вернулось.")
        print("Возможно, пользовательский токен выдан под другой аккаунт.")
        sys.exit(1)

    print("Филиалы, доступные вашим ключам:\n")
    for филиал in филиалы:
        название = филиал.get("title") or филиал.get("short_descr") or "без названия"
        print(f"    YCLIENTS_COMPANY_ID={филиал.get('id')}    {название}")

    if len(филиалы) == 1:
        print("\nФилиал один — впишите эту строку в .env.")
    else:
        print("\nВыберите нужный филиал и впишите его строку в .env.")


if __name__ == "__main__":
    asyncio.run(main())
