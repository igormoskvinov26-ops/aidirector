"""Настройка Telegram прямо в интерфейсе — токен бота и чат для рассылки.

Решение владельца 27.09.2026. Раньше сменить бота или чат можно было только
через .env на сервере. Строка в базе (единственная, id всегда 1) главенствует
над TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID из .env; если владелец её ещё не
заводил, всё продолжает работать на значениях из .env — обратная
совместимость с уже развёрнутыми установками.

Токен нигде не возвращается целиком — ни в GET, ни в логах: это пароль от
бота, и тот, кто его увидит, сможет слать сообщения от его имени.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import TelegramSettings

ID = 1


async def получить(session: AsyncSession) -> TelegramSettings | None:
    строка = await session.execute(select(TelegramSettings).where(TelegramSettings.id == ID))
    return строка.scalars().first()


async def учётные_данные(
    session: AsyncSession, запасной_токен: str, запасной_чат: str
) -> tuple[str, str]:
    """Токен и chat_id для отправки: из базы, если владелец их настроил, иначе из .env."""
    настройки = await получить(session)
    if настройки is not None and настройки.bot_token and настройки.chat_id:
        return настройки.bot_token, настройки.chat_id
    return запасной_токен, запасной_чат


def _маска(токен: str) -> str:
    """Последние 4 символа — чтобы владелец узнал свой токен, не читая чужой."""
    return f"…{токен[-4:]}" if len(токен) > 4 else "…"


async def как_словарь(session: AsyncSession, запасной_токен: str, запасной_чат: str) -> dict:
    настройки = await получить(session)
    if настройки is not None and настройки.bot_token and настройки.chat_id:
        return {
            "configured": True,
            "source": "database",
            "bot_username": настройки.bot_username,
            "bot_token_masked": _маска(настройки.bot_token),
            "chat_id": настройки.chat_id,
            "chat_title": настройки.chat_title,
            "updated_at": настройки.updated_at.isoformat(),
        }
    if запасной_токен and запасной_чат:
        return {
            "configured": True,
            "source": "env",
            "bot_username": None,
            "bot_token_masked": _маска(запасной_токен),
            "chat_id": запасной_чат,
            "chat_title": None,
            "updated_at": None,
        }
    return {
        "configured": False,
        "source": "none",
        "bot_username": None,
        "bot_token_masked": None,
        "chat_id": None,
        "chat_title": None,
        "updated_at": None,
    }


async def сохранить(
    session: AsyncSession,
    *,
    bot_token: str,
    chat_id: str,
    bot_username: str | None,
    chat_title: str | None,
) -> None:
    настройки = await получить(session)
    if настройки is None:
        настройки = TelegramSettings(id=ID)
        session.add(настройки)
    настройки.bot_token = bot_token
    настройки.chat_id = chat_id
    настройки.bot_username = bot_username
    настройки.chat_title = chat_title
    await session.commit()
