"""Филиалы на одном компьютере: у каждого своя база PostgreSQL.

Реестр лежит в output/branches.json (переживает обновление). Главный филиал
("main") — база, с которой Пульт работал всегда, его данные не трогаются.
Остальные создаются кнопкой «Добавить филиал»: новая база, миграции, учётные
записи управляющего и администратора этого филиала.

Переключение глобальное для процесса: активный филиал один на всех, кто сейчас
в Пульте. Управляет им только главный владелец (вход под .env/мастером).
"""

import asyncio
import json
import secrets
from pathlib import Path

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import database
from app.config import settings
from app.main_roles import ROLE_OPERATOR, ROLE_OWNER
from app.services import configuration, credentials, salon
from app.services.cache import invalidate

MAIN = "main"
_lock = asyncio.Lock()
active: str = MAIN


def _файл() -> Path:
    return Path(settings.output_dir) / "branches.json"


def _читать() -> dict:
    try:
        d = json.loads(_файл().read_text(encoding="utf-8"))
        return {"active": d.get("active", MAIN), "branches": list(d.get("branches", []))}
    except (OSError, ValueError):
        return {"active": MAIN, "branches": []}


def _писать(d: dict) -> None:
    _файл().parent.mkdir(parents=True, exist_ok=True)
    tmp = _файл().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_файл())


def главный() -> bool:
    return active == MAIN


def имя_базы(ид: str) -> str:
    if ид == MAIN:
        return settings.postgres_db
    for b in _читать()["branches"]:
        if b["id"] == ид:
            return b["db"]
    raise KeyError(ид)


def список() -> dict:
    d = _читать()
    return {
        "active": active,
        "branches": [{"id": MAIN, "name": salon.главное_имя}]
        + [{"id": b["id"], "name": b["name"]} for b in d["branches"]],
    }


async def _применить_ветку(ид: str) -> None:
    """Прочитать настройки, учётные записи и название активной базы."""
    global active
    from app.database import async_session

    active = ид
    configuration.изолирован = ид != MAIN
    salon.главная = ид == MAIN
    invalidate("")
    async with async_session() as s:
        await configuration.загрузить(s)
        await credentials.загрузить_ветку(None if ид == MAIN else s)
        await salon.загрузить(s)
    from app.services import hub, settings_file

    settings_file.сбросить()
    hub.status.update(ok=None, at=None, error=None, pushed=0, pulled=0)


async def переключить(ид: str) -> None:
    async with _lock:
        if ид == active:
            return
        from app.services import sync

        if sync._sync_in_progress:
            raise RuntimeError("Идёт выгрузка из YCLIENTS — повторите через минуту")
        if ид == MAIN:
            db = settings.postgres_db
        else:
            db = next((b["db"] for b in _читать()["branches"] if b["id"] == ид), None)
            if db is None:
                raise KeyError(ид)
        if active == MAIN:  # запомнить название главного, пока оно в его базе
            salon.главное_имя = salon.name
        await database.use_database(db)
        await _применить_ветку(ид)
        d = _читать()
        d["active"] = ид
        _писать(d)
        logger.info(f"активный филиал: {ид}")


async def восстановить_активный() -> None:
    """При старте: открыть тот филиал, на котором закончили."""
    d = _читать()
    if d["active"] != MAIN and any(b["id"] == d["active"] for b in d["branches"]):
        try:
            salon.главное_имя = salon.name
            db = next(b["db"] for b in d["branches"] if b["id"] == d["active"])
            await database.use_database(db)
            await _применить_ветку(d["active"])
        except Exception as e:  # noqa: BLE001 — не уронить запуск: останемся на главном
            logger.warning(f"филиал не открылся, работаю на главном: {type(e).__name__}: {e}")
            await database.use_database(settings.postgres_db)
            await _применить_ветку(MAIN)


def _миграции(db: str) -> None:
    from alembic import command
    from alembic.config import Config

    корень = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(корень / "alembic.ini"))
    cfg.set_main_option("script_location", str(корень / "alembic"))
    прежний = settings.postgres_db
    settings.postgres_db = db  # alembic/env.py берёт адрес из settings
    try:
        command.upgrade(cfg, "head")
    finally:
        settings.postgres_db = прежний


async def создать(
    название: str, админ: tuple[str, str], управляющий: tuple[str, str]
) -> dict:
    название = название.strip()[:60]
    if not название:
        raise ValueError("Укажите название филиала")
    for логин, пароль in (админ, управляющий):
        credentials.проверить_требования(логин, пароль)
    if админ[0].strip() == управляющий[0].strip():
        raise ValueError("Логины администратора и управляющего должны различаться")
    async with _lock:
        d = _читать()
        if any(b["name"].lower() == название.lower() for b in d["branches"]) or (
            название.lower() == salon.главное_имя.lower()
        ):
            raise ValueError("Филиал с таким названием уже есть")
        ид = "b" + secrets.token_hex(3)
        db = "rubl_" + ид
        admin_engine = create_async_engine(
            database.url_for("postgres"), isolation_level="AUTOCOMMIT"
        )
        try:
            async with admin_engine.connect() as c:
                await c.execute(text(f'CREATE DATABASE "{db}"'))
        finally:
            await admin_engine.dispose()
        try:
            await asyncio.to_thread(_миграции, db)
        except Exception:
            admin_engine = create_async_engine(database.url_for("postgres"), isolation_level="AUTOCOMMIT")
            async with admin_engine.connect() as c:
                await c.execute(text(f'DROP DATABASE IF EXISTS "{db}"'))
            await admin_engine.dispose()
            raise
        d["branches"].append({"id": ид, "name": название, "db": db})
        _писать(d)
    await переключить(ид)
    from app.database import async_session

    async with async_session() as s:
        await credentials.завести(s, ROLE_OWNER, *управляющий, ветка=True)
        await credentials.завести(s, ROLE_OPERATOR, *админ, ветка=True)
        await salon.сохранить(s, salon_name=название)
    return список()
