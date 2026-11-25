"""Отчёты банка из почты: Пульт сам забирает вложения и грузит их в сверку.

Банк присылает отчёт по эквайрингу письмом каждый день. Раньше владелец
скачивал вложение и перетаскивал его в «Контроль финансов» руками; одно
пропущенное письмо — и день в сверке остаётся пустым. Теперь Пульт заходит
в ящик по IMAP, берёт из новых писем вложения .xlsx и .csv и прогоняет их
через тот же разбор, что и ручная загрузка (app.services.acquiring).

Почему IMAP, а не что-то умнее: это единственный способ забрать письмо из
Яндекса без их OAuth-приложения, и он работает стандартной библиотекой —
новых зависимостей не нужно. Яндекс не принимает обычный пароль от почты,
нужен пароль приложения из Яндекс ID.

Ящик открывается только на чтение (readonly=True): Пульт не трогает флаги
и не удаляет письма — владелец увидит их в почте в том же виде.

Что уже посмотрели, помним по UID последнего письма. Письмо с нечитаемым
вложением тоже считается просмотренным: иначе Пульт пытался бы разобрать
его каждые четверть часа и писал бы одну и ту же ошибку до скончания века.
Про такое письмо пишется в статусе, и файл всегда можно загрузить руками.
"""

from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import json
from datetime import datetime
from email.header import decode_header, make_header
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AppSetting
from app.services.monthly_report import MOSCOW

СОСТОЯНИЕ = "mail_acquiring_state"
РАСШИРЕНИЯ = (".xlsx", ".xlsm", ".csv", ".txt")
ПИСЕМ_ЗА_РАЗ = 20  # первый запуск не должен читать весь ящик разом
ПРЕДЕЛ_ФАЙЛА = 10 * 1024 * 1024
ТАЙМАУТ = 25


# ── Имена папок IMAP ──────────────────────────────────────────────────────
# Сервер хранит их в модифицированном UTF-7 (RFC 3501): «Банк» выглядит как
# «&BBEEMAQ9BDo-». В стандартной библиотеке такого кодека нет, а папки у
# русского ящика почти всегда русские — поэтому двадцать строк своих.


def в_utf7(имя: str) -> str:
    части: list[str] = []
    буфер: list[str] = []

    def слить() -> None:
        if буфер:
            сырьё = "".join(буфер).encode("utf-16-be")
            код = base64.b64encode(сырьё).decode("ascii").rstrip("=").replace("/", ",")
            части.append(f"&{код}-")
            буфер.clear()

    for знак in имя:
        if знак == "&":
            слить()
            части.append("&-")
        elif 0x20 <= ord(знак) <= 0x7E:
            слить()
            части.append(знак)
        else:
            буфер.append(знак)
    слить()
    return "".join(части)


def из_utf7(имя: str) -> str:
    части: list[str] = []
    i = 0
    while i < len(имя):
        if имя[i] != "&":
            части.append(имя[i])
            i += 1
            continue
        конец = имя.find("-", i)
        if конец < 0:
            части.append(имя[i:])
            break
        кусок = имя[i + 1 : конец]
        if not кусок:
            части.append("&")
        else:
            код = кусок.replace(",", "/")
            код += "=" * (-len(код) % 4)
            try:
                части.append(base64.b64decode(код).decode("utf-16-be"))
            except Exception:  # noqa: BLE001 — имя папки не повод падать
                части.append(кусок)
        i = конец + 1
    return "".join(части)


def _имя_вложения(часть: email.message.Message) -> str:
    сырое = часть.get_filename()
    if not сырое:
        return ""
    try:
        return str(make_header(decode_header(сырое)))
    except Exception:  # noqa: BLE001
        return сырое


def вложения(сырое_письмо: bytes) -> list[tuple[str, bytes]]:
    """Файлы отчётов из письма. Картинки подписи и прочий мусор отбрасываем."""
    письмо = email.message_from_bytes(сырое_письмо)
    итог: list[tuple[str, bytes]] = []
    for часть in письмо.walk():
        if часть.is_multipart():
            continue
        имя = _имя_вложения(часть)
        if not имя.lower().endswith(РАСШИРЕНИЯ):
            continue
        тело = часть.get_payload(decode=True)
        if тело and len(тело) <= ПРЕДЕЛ_ФАЙЛА:
            итог.append((имя, тело))
    return итог


# ── Разговор с сервером ───────────────────────────────────────────────────


# Две причины отказа у Яндекса неразличимы по ответу сервера, он отвечает
# одной строкой на обе, — поэтому в подсказке названы обе сразу.
ПОДСКАЗКА_ВХОДА = (
    "Почта не пустила. У Яндекса этот ответ значит одно из двух. "
    "Первое: нужен пароль приложения из Яндекс ID → Безопасность → Пароли "
    "приложений → Почта; обычный пароль от почты по IMAP не принимается. "
    "Второе: в Почте не включён доступ — Все настройки → Почтовые программы → "
    "«С сервера imap.yandex.ru по протоколу IMAP» и «Пароли приложений и "
    "OAuth-токены»."
)


def _текст_сбоя(сбой: BaseException) -> str:
    """Человеческая строка из ошибки imaplib.

    imaplib кладёт в исключение байты, и без этого в интерфейс попадало
    b'[AUTHENTICATIONFAILED] LOGIN invalid credentials...' — с кавычками,
    буквой b и без единого намёка, что делать.
    """
    аргумент = сбой.args[0] if сбой.args else ""
    текст = (аргумент.decode("utf-8", "replace") if isinstance(аргумент, bytes)
             else str(аргумент) or str(сбой)).strip()
    if "AUTHENTICATIONFAILED" in текст or "invalid credentials" in текст.lower():
        return ПОДСКАЗКА_ВХОДА
    return текст or "Почтовый сервер не ответил"


def _подключиться(хост: str, логин: str, пароль: str) -> imaplib.IMAP4_SSL:
    связь = imaplib.IMAP4_SSL(хост, 993, timeout=ТАЙМАУТ)
    связь.login(логин, пароль)
    return связь


def папки(связь: imaplib.IMAP4) -> list[str]:
    """Список папок человеческими именами — чтобы подсказать, если ошиблись."""
    вид, строки = связь.list()
    если_что: list[str] = []
    if вид != "OK":
        return если_что
    for строка in строки or []:
        текст = строка.decode("ascii", "replace") if isinstance(строка, bytes) else str(строка)
        кавычки = текст.split(' "')
        имя = кавычки[-1].strip('"') if len(кавычки) > 1 else текст.rsplit(" ", 1)[-1]
        если_что.append(из_utf7(имя.strip('"')))
    return если_что


def собрать(связь: imaplib.IMAP4, папка: str, состояние: dict) -> tuple[list[bytes], dict]:
    """Сырые письма, которых мы ещё не видели, и новое состояние просмотра."""
    вид, _ = связь.select(в_utf7(папка), readonly=True)
    if вид != "OK":
        доступные = ", ".join(папки(связь)) or "список не получен"
        raise RuntimeError(f"Папки «{папка}» в ящике нет. Есть такие: {доступные}")

    ответ = связь.response("UIDVALIDITY")[1]
    валидность = int(ответ[0]) if ответ and ответ[0] else 0
    прошлая = состояние.get("uidvalidity")
    последний = int(состояние.get("last_uid") or 0)
    if прошлая is not None and валидность != прошлая:
        # Папку пересоздали: прежние UID больше ничего не значат.
        последний = 0

    вид, данные = связь.uid("search", None, f"UID {последний + 1}:*")
    if вид != "OK":
        raise RuntimeError("Сервер не ответил на поиск писем")
    номера = [int(x) for x in (данные[0] or b"").split()]
    # «UID n:*» сервер понимает вольно и возвращает последнее письмо, даже
    # если его номер меньше n. Отбираем сами.
    номера = sorted(n for n in номера if n > последний)[:ПИСЕМ_ЗА_РАЗ]

    письма: list[bytes] = []
    for номер in номера:
        вид, кусок = связь.uid("fetch", str(номер), "(RFC822)")
        if вид != "OK" or not кусок:
            continue
        for элемент in кусок:
            if isinstance(элемент, tuple) and элемент[1]:
                письма.append(элемент[1])
                break
    новое = {"uidvalidity": валидность, "last_uid": max(номера) if номера else последний}
    return письма, новое


# ── Состояние и запуск ────────────────────────────────────────────────────


async def состояние(session: AsyncSession) -> dict[str, Any]:
    from app.services import configuration

    строка = await session.get(AppSetting, СОСТОЯНИЕ)
    итог: dict[str, Any] = {}
    if строка and строка.value:
        try:
            итог = json.loads(строка.value)
        except ValueError:
            итог = {}
    итог["configured"] = configuration.настроена("mail")
    итог["mailbox"] = configuration.значение("MAIL_LOGIN")
    итог["folder"] = configuration.значение("MAIL_FOLDER") or "INBOX"
    return итог


async def _запомнить(session: AsyncSession, данные: dict) -> None:
    строка = await session.get(AppSetting, СОСТОЯНИЕ)
    текст = json.dumps(данные, ensure_ascii=False)
    if строка is None:
        session.add(AppSetting(key=СОСТОЯНИЕ, value=текст, updated_by="mail"))
    else:
        строка.value = текст
        строка.updated_by = "mail"
    await session.commit()


async def проверить_связь() -> str:
    """Для кнопки «Проверить связь» в настройках: войти и найти папку."""
    from app.services import configuration

    хост = configuration.значение("MAIL_IMAP_HOST") or "imap.yandex.ru"
    логин = configuration.значение("MAIL_LOGIN")
    пароль = configuration.значение("MAIL_PASSWORD")
    папка = configuration.значение("MAIL_FOLDER") or "INBOX"

    def работа() -> str:
        связь = _подключиться(хост, логин, пароль)
        try:
            вид, данные = связь.select(в_utf7(папка), readonly=True)
            if вид != "OK":
                доступные = ", ".join(папки(связь)) or "список не получен"
                raise RuntimeError(f"Вход принят, но папки «{папка}» нет. Есть такие: {доступные}")
            писем = int((данные[0] or b"0").decode() or 0)
            return f"Ящик открыт, в папке «{папка}» писем: {писем}"
        finally:
            try:
                связь.logout()
            except Exception:  # noqa: BLE001
                pass

    try:
        return await asyncio.to_thread(работа)
    except Exception as сбой:  # noqa: BLE001 — ответ показывается человеку
        raise RuntimeError(_текст_сбоя(сбой)) from None


async def забрать(session: AsyncSession) -> dict[str, Any]:
    """Прочитать новые письма и загрузить из них отчёты. Ошибки не бросает:
    это фоновая задача, её сбой не должен ронять ни цикл, ни страницу."""
    from app.services import acquiring, configuration

    если = await состояние(session)
    если_настроено = если.get("configured")
    когда = datetime.now(MOSCOW).isoformat()
    if not если_настроено:
        return если

    хост = configuration.значение("MAIL_IMAP_HOST") or "imap.yandex.ru"
    логин = configuration.значение("MAIL_LOGIN")
    пароль = configuration.значение("MAIL_PASSWORD")
    папка = configuration.значение("MAIL_FOLDER") or "INBOX"
    прошлое = {"uidvalidity": если.get("uidvalidity"), "last_uid": если.get("last_uid")}

    def работа() -> tuple[list[bytes], dict]:
        связь = _подключиться(хост, логин, пароль)
        try:
            return собрать(связь, папка, прошлое)
        finally:
            try:
                связь.logout()
            except Exception:  # noqa: BLE001
                pass

    try:
        письма, новое = await asyncio.to_thread(работа)
    except Exception as сбой:  # noqa: BLE001 — показываем человеку, не роняем
        logger.warning(f"почта: не удалось забрать письма: {сбой}")
        итог = {**прошлое, "checked_at": когда, "ok": False, "message": _текст_сбоя(сбой)[:400]}
        await _запомнить(session, итог)
        return await состояние(session)

    загружено, дней, беды = 0, 0, []
    for сырое in письма:
        for имя, тело in вложения(сырое):
            try:
                отчёт = await acquiring.сохранить(session, тело, имя)
                загружено += 1
                дней += int(отчёт.get("days") or 0)
            except Exception as сбой:  # noqa: BLE001
                logger.warning(f"почта: вложение «{имя}» не разобрано: {сбой}")
                беды.append(f"«{имя}»: {сбой}")

    if беды:
        сообщение = (
            f"Писем просмотрено: {len(письма)}, загружено отчётов: {загружено}. "
            f"Не разобрал: {'; '.join(беды)[:220]} — такой файл загрузите кнопкой."
        )
    elif загружено:
        сообщение = f"Загружено отчётов: {загружено}, дней: {дней}."
    elif письма:
        сообщение = f"Новых писем: {len(письма)}, отчётов во вложениях не было."
    else:
        сообщение = "Новых писем нет."

    await _запомнить(session, {
        **новое, "checked_at": когда, "ok": not беды, "message": сообщение,
        "loaded": загружено, "days": дней,
    })
    return await состояние(session)
