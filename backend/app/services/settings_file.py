"""Файл настроек на компьютере: зеркало настроек из базы, переживает обновление.

Решение владельца 04.10.2026. Всё, что настроили в Пульте (ключи YCLIENTS,
Telegram, общий сервер, ID администраторов, допуслуги, нормативы, точка отсчёта
пульса), раз в полминуты записывается в ``output/director-settings.json``.
Папка output лежит на самом компьютере рядом с программой и обновлением не
затрагивается. Если база пропала (переустановка, удалённый том Docker), при
старте недостающее возвращается из файла: поверх существующего оно ничего не
меняет.

Файл содержит секреты, как и .env: права 600, в архив и репозиторий не попадает.
На общий сервер секреты не уходят никогда: туда идут только несекретные
настройки, и делает это hub.py отдельно.
"""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import AppSetting, ReportSetting, TelegramSettings
from app.services import configuration

FILE_NAME = "director-settings.json"
PULSE_KEY = "pulse_start_date"
INTERVAL_SECONDS = 30
_last_hash = ""


def сбросить() -> None:
    """После переключения филиала: хеш прежнего файла к новому не относится."""
    global _last_hash
    _last_hash = ""


def путь() -> Path:
    from app.services import branches

    имя = FILE_NAME if branches.главный() else f"director-settings-{branches.active}.json"
    return Path(settings.output_dir) / имя


async def снимок(session: AsyncSession) -> dict:
    """Текущее состояние настроек из базы."""
    managed = (await session.execute(select(AppSetting))).scalars().all()
    wanted = set(configuration.ВСЕ_КЛЮЧИ) | {PULSE_KEY}
    tg = (await session.execute(select(TelegramSettings).where(TelegramSettings.id == 1))).scalars().first()
    return {
        "app_settings": {r.key: r.value for r in managed if r.key in wanted and r.value},
        "telegram": {"bot_token": tg.bot_token, "chat_id": tg.chat_id,
                     "bot_username": tg.bot_username, "chat_title": tg.chat_title} if tg and tg.bot_token else None,
        "report_settings": {r.key: r.value for r in (await session.execute(select(ReportSetting))).scalars()},
    }


def _пусто(s: dict) -> bool:
    return not (s["app_settings"] or s["telegram"] or s["report_settings"])


async def записать(session: AsyncSession) -> bool:
    """Обновить файл, если настройки изменились. Пустую базу поверх файла не пишем."""
    global _last_hash
    s = await снимок(session)
    p = путь()
    if _пусто(s) and p.exists():
        return False  # база пуста, файл хранит прежнее: сначала восстановление
    body = json.dumps(s, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha256(body.encode()).hexdigest()
    if h == _last_hash:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"saved_at": datetime.now(UTC).isoformat(), **s}, indent=2,
                              ensure_ascii=False, default=str), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    _last_hash = h
    return True


async def восстановить(session: AsyncSession) -> list[str]:
    """Вернуть из файла то, чего нет в базе. Существующее не трогаем."""
    p = путь()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning(f"файл настроек не прочитан: {e}")
        return []
    back: list[str] = []
    for key, value in (data.get("app_settings") or {}).items():
        row = await session.get(AppSetting, key)
        if row is None or not row.value:
            if row is None:
                session.add(AppSetting(key=key, value=str(value), updated_by="файл настроек"))
            else:
                row.value = str(value)
            back.append(key)
    for key, value in (data.get("report_settings") or {}).items():
        if await session.get(ReportSetting, key) is None:
            session.add(ReportSetting(key=key, value=value))
            back.append(f"отчёт:{key}")
    tg = data.get("telegram")
    if tg and (await session.execute(select(TelegramSettings).where(TelegramSettings.id == 1))).scalars().first() is None:
        session.add(TelegramSettings(id=1, bot_token=tg["bot_token"], chat_id=tg["chat_id"],
                                     bot_username=tg.get("bot_username"), chat_title=tg.get("chat_title")))
        back.append("telegram")
    if back:
        await session.commit()
        await configuration.загрузить(session)
        from app.services import salon

        await salon.загрузить(session)
        logger.info(f"настройки возвращены из файла: {len(back)}")
    return back


async def run_settings_file_loop() -> None:
    from app.database import async_session

    await asyncio.sleep(5)
    try:
        async with async_session() as session:
            await восстановить(session)
    except Exception as e:  # noqa: BLE001 — таблиц может ещё не быть: миграция накатится позже
        logger.warning(f"восстановление настроек из файла отложено: {type(e).__name__}")
    while True:
        try:
            async with async_session() as session:
                await записать(session)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"файл настроек не обновлён: {type(e).__name__}")
        await asyncio.sleep(INTERVAL_SECONDS)
