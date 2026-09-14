"""Получить YCLIENTS_USER_TOKEN по логину и паролю.

Партнёрский токен виден в настройках YCLIENTS, а пользовательский — нет: его
выдают в обмен на логин и пароль сотрудника. Это разные вещи, и одну за другую
принять легко: запросы с чужим пользовательским токеном отвечают не «неверный
ключ», а пустым списком филиалов.

Пароль спрашивается при запуске, никуда не пишется и на экране не виден.
Полученный токен нужно вписать в .env одной строкой.

Запуск из папки проекта:
    cd backend && uv run python "../scripts/получить-токен.py"
"""

import asyncio
import getpass
import json
import sys
from pathlib import Path

import httpx

BASE_URL = "https://api.yclients.com/api/v1"


def найти_env() -> Path | None:
    кандидаты = []
    try:
        кандидаты.append(Path(__file__).resolve().parent.parent / ".env")
    except NameError:
        pass
    кандидаты += [Path.cwd() / ".env", Path.cwd().parent / ".env"]
    return next((p for p in кандидаты if p.is_file()), None)


def прочитать_партнёрский(путь: Path) -> str:
    for строка in путь.read_text(encoding="utf-8").splitlines():
        строка = строка.strip()
        if строка.startswith("YCLIENTS_PARTNER_TOKEN="):
            return строка.partition("=")[2].strip().strip('"').strip("'")
    return ""


async def main() -> None:
    путь = найти_env()
    if путь is None:
        print("Файл .env не найден. Запускайте из папки проекта:")
        print('    cd backend && uv run python "../scripts/получить-токен.py"')
        sys.exit(1)

    партнёр = прочитать_партнёрский(путь)
    if not партнёр or партнёр.startswith("<"):
        print(f"В файле {путь} не заполнен YCLIENTS_PARTNER_TOKEN.")
        print("Он есть в настройках YCLIENTS, в разделе для партнёров.")
        sys.exit(1)

    print("Вход в YCLIENTS — те же логин и пароль, что и на сайте.")
    print("Пароль при вводе не отображается, это нормально.\n")
    # Скрипт спрашивает вживую. Если ввод подставлен из файла или конвейера,
    # он кончится молча — лучше сказать об этом, чем упасть трейсбеком.
    try:
        логин = input("Логин (телефон или почта): ").strip()
        пароль = getpass.getpass("Пароль: ") if логин else ""
    except EOFError:
        print("\nВвод закончился. Запускайте скрипт вручную в терминале.")
        sys.exit(1)

    if not логин or not пароль:
        print("Логин и пароль нужны оба.")
        sys.exit(1)

    заголовки = {
        "Authorization": f"Bearer {партнёр}",
        "Accept": "application/vnd.yclients.v2+json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        ответ = await client.post(
            "/auth", json={"login": логин, "password": пароль}, headers=заголовки
        )

    if ответ.status_code in (401, 403):
        print("\nYCLIENTS не принял логин или пароль.")
        print("Если вход на сайт работает, проверьте партнёрский токен в .env.")
        sys.exit(1)

    тело = ответ.json() if ответ.headers.get("content-type", "").startswith(
        "application/json"
    ) else {}
    токен = (тело.get("data") or {}).get("user_token")

    if not токен:
        print(f"\nТокен не пришёл. Ответ YCLIENTS (код {ответ.status_code}):")
        print(json.dumps(тело, ensure_ascii=False, indent=2)[:1200] or ответ.text[:600])
        sys.exit(1)

    имя = (тело.get("data") or {}).get("name") or "сотрудник"
    print(f"\nГотово. Токен выдан для: {имя}\n")
    print("Впишите эту строку в .env, заменив прежнюю:\n")
    print(f"    YCLIENTS_USER_TOKEN={токен}\n")
    print("Токен — такой же секрет, как пароль: никому не пересылайте.")
    print("Дальше: uv run python \"../scripts/показать-филиалы.py\"")


if __name__ == "__main__":
    asyncio.run(main())
