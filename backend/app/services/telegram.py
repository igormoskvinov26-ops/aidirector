"""Отправка текстового сообщения в Telegram.

Отдельно от сторис: те шлют картинку через sendPhoto и живут в своём
маршруте, здесь нужен обычный текст. Общее у них одно правило, и оно
важнее удобства: **тело ответа Telegram в журнал не попадает никогда** —
в нём может оказаться токен бота.
"""

import httpx
from loguru import logger

from app.config import settings

ТАЙМАУТ = 30


class TelegramNotConfiguredError(RuntimeError):
    """Нет токена бота или чата в .env — отправлять некуда."""


class TelegramSendError(RuntimeError):
    """Telegram не принял сообщение."""


async def отправить_сообщение(текст: str) -> int | None:
    """Шлёт текст в чат из настроек. Возвращает message_id, если Telegram его дал."""
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        raise TelegramNotConfiguredError(
            "TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не настроены в .env"
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
