"""Файл настроек: запись, восстановление в пустую базу, защита от затирания."""

import json
import os
import stat

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.models import AppSetting, Base, ReportSetting, TelegramSettings
from app.services import settings_file as sf


async def _db(tmp_path, name):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_запись_и_возврат_в_пустую_базу(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(sf, "_last_hash", "")
    old, fresh = await _db(tmp_path, "old"), await _db(tmp_path, "fresh")

    async with old() as s:
        s.add_all([AppSetting(key="YCLIENTS_USER_TOKEN", value="tok-user"),
                   AppSetting(key="HUB_TOKEN", value="hub-secret"),
                   AppSetting(key="random_other_key", value="не наша"),
                   ReportSetting(key="admins", value=[{"staff_id": 1, "name": "Виктор", "creator_values": ["42"]}]),
                   ReportSetting(key="extra_services", value=["Камуфляж"]),
                   TelegramSettings(id=1, bot_token="bot-tok", chat_id="-100")])
        await s.commit()
        assert await sf.записать(s) is True
        assert await sf.записать(s) is False  # без изменений файл не переписываем

    p = sf.путь()
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert "random_other_key" not in saved["app_settings"]  # только известные ключи

    async with fresh() as s:  # переустановка: база пустая
        assert await sf.записать(s) is False  # пустую базу поверх файла не пишем
        assert json.loads(p.read_text(encoding="utf-8"))["app_settings"]["HUB_TOKEN"] == "hub-secret"
        back = await sf.восстановить(s)
        assert {"YCLIENTS_USER_TOKEN", "HUB_TOKEN", "telegram", "отчёт:admins", "отчёт:extra_services"} <= set(back)
        assert (await s.get(ReportSetting, "admins")).value[0]["creator_values"] == ["42"]
        assert (await s.get(AppSetting, "YCLIENTS_USER_TOKEN")).value == "tok-user"


async def test_восстановление_не_перезаписывает_существующее(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(sf, "_last_hash", "")
    db = await _db(tmp_path, "db")
    async with db() as s:
        s.add(AppSetting(key="HUB_URL", value="https://один"))
        await s.commit()
        await sf.записать(s)
        (await s.get(AppSetting, "HUB_URL")).value = "https://два"
        await s.commit()
        assert await sf.восстановить(s) == []
        assert (await s.get(AppSetting, "HUB_URL")).value == "https://два"
