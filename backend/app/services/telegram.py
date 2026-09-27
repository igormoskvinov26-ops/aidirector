"""Отправка текстового сообщения в Telegram.

Отдельно от сторис: те шлют картинку через sendPhoto и живут в своём
маршруте, здесь нужен обычный текст. Общее у них одно правило, и оно
важнее удобства: **тело ответа Telegram в журнал не попадает никогда** —
в нём может оказаться токен бота.
"""

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import telegram_settings

ТАЙМАУТ = 30


class TelegramNotConfiguredError(RuntimeError):
    """Нет токена бота или чата ни в базе, ни в .env — отправлять некуда."""


class TelegramSendError(RuntimeError):
    """Telegram не принял сообщение."""


async def отправить_сообщение(текст: str, session: AsyncSession | None = None) -> int | None:
    """Шлёт текст в чат из настроек. Возвращает message_id, если Telegram его дал.

    Настройки берутся из базы (страница «Смена» → «Настройка ТГ»), если
    владелец их там завёл; иначе — из .env, как было раньше.
    """
    token, chat_id = settings.telegram_bot_token, settings.telegram_chat_id
    if session is not None:
        token, chat_id = await telegram_settings.учётные_данные(session, token, chat_id)
    if not token or not chat_id:
        raise TelegramNotConfiguredError(
            "Telegram не настроен — заполните «Настройка ТГ» на странице «Смена» "
            "или TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID в .env"
        )

    try:
        async with httpx.AsyncClient(timeout=ТАЙМАУТ) as http:
            ответ = await http.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": текст, "disable_web_page_preview": "true"},
            )
    except httpx.TimeoutException as сбой:
        logger.error(f"telegram sendMessage timeout: {сбой}")
        raise TelegramSendError("Telegram не ответил вовремя — попробуйте ещё раз") from сбой
    except httpx.TransportError as сбой:
        # Сюда попадают обрыв сети, отказ DNS, недоступный прокси — то, что
        # раньше всплывало наверх нераспознанной ошибкой 500 и с точки зрения
        # кнопки в интерфейсе выглядело как «просто не работает».
        logger.error(f"telegram sendMessage: сеть недоступна: {сбой}")
        raise TelegramSendError(
            "Не удалось связаться с Telegram — проверьте интернет-соединение"
        ) from сбой

    if ответ.status_code != 200:
        # Только код: в теле ответа может быть токен бота.
        logger.error(f"telegram sendMessage failed: {ответ.status_code}")
        raise TelegramSendError("Telegram отклонил отправку")

    try:
        данные = ответ.json().get("result") or {}
        ident = данные.get("message_id")
        return int(ident) if ident is not None else None
    except Exception:  # noqa: BLE001 — сообщение уже ушло, номер не критичен
        logger.warning("telegram: сообщение отправлено, но message_id не разобран")
        return None


async def _запрос(метод: str, token: str, **параметры: str) -> dict | list:
    """Общая обвязка для discovery-запросов формы «Настройка ТГ» (не sendMessage)."""
    try:
        async with httpx.AsyncClient(timeout=ТАЙМАУТ) as http:
            ответ = await http.get(f"https://api.telegram.org/bot{token}/{метод}", params=параметры)
    except httpx.TimeoutException as сбой:
        raise TelegramSendError("Telegram не ответил вовремя — попробуйте ещё раз") from сбой
    except httpx.TransportError as сбой:
        raise TelegramSendError(
            "Не удалось связаться с Telegram — проверьте интернет-соединение"
        ) from сбой
    if ответ.status_code != 200:
        # Только код: в теле ответа Telegram при ошибке может мелькнуть токен.
        logger.warning(f"telegram {метод} failed: {ответ.status_code}")
        raise TelegramSendError(
            "Telegram отклонил запрос — проверьте, что токен скопирован целиком"
        )
    return ответ.json().get("result")


async def узнать_бота(token: str) -> dict:
    """getMe — подтверждает, что токен рабочий, и называет бота."""
    данные = await _запрос("getMe", token) or {}
    return {"username": данные.get("username"), "id": данные.get("id")}


async def найти_чаты(token: str) -> list[dict]:
    """getUpdates — чаты, куда бот уже что-то видел.

    Работает, только если после добавления бота в чат туда пришло хотя бы
    одно сообщение: Telegram не отдаёт историю чатов сам по себе, только
    последние необработанные обновления.
    """
    обновления = await _запрос("getUpdates", token) or []
    чаты: dict[int, str] = {}
    for обновление in обновления:
        сообщение = обновление.get("message") or обновление.get("channel_post") or {}
        чат = сообщение.get("chat") or {}
        if чат.get("id") is not None:
            чаты[чат["id"]] = (
                чат.get("title") or чат.get("username") or чат.get("first_name") or "Без названия"
            )
    return [{"chat_id": ид, "title": имя} for ид, имя in чаты.items()]


async def проверить_чат(token: str, chat_id: str) -> dict:
    """getChat — подтверждает, что бот действительно видит именно этот chat_id."""
    try:
        данные = await _запрос("getChat", token, chat_id=chat_id) or {}
    except TelegramSendError:
        raise TelegramSendError(
            "Telegram не нашёл этот чат — проверьте chat_id и что бот в него добавлен"
        ) from None
    return {"title": данные.get("title") or данные.get("username") or данные.get("first_name")}
