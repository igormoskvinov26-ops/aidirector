"""Уволенного администратора можно скрыть, нового — добавить до его первой
записи; найденный потом по записям, он не двоится (02.11.2026)."""

import pytest

from app.services import monthly_report as mr


@pytest.mark.asyncio
async def test_добавленный_вручную_не_двоится(monkeypatch):
    async def каталог():
        return {"77": "Дарья"}, {"77": {"staff_id": 555, "name": "Дарья"}}

    monkeypatch.setattr(mr, "_directory", каталог)
    mr.invalidate("")
    cfg = {**mr.ДЕФОЛТЫ, "admins": [{"staff_id": -1, "name": "Дарья", "creator_values": []}]}
    записи = [{"id": 1, "created_user_id": 77, "date": "2026-11-02 10:00:00"}]
    итог = await mr.auto_admins(cfg, записи)
    assert [a["name"] for a in итог] == ["Дарья"]
    assert итог[0]["creator_values"] == ["77"]


@pytest.mark.asyncio
async def test_скрытые_не_в_списке_звонящих(monkeypatch):
    async def все(session, cfg):
        return [{"staff_id": 1, "name": "Екатерина", "creator_values": []},
                {"staff_id": 2, "name": "Дарья", "creator_values": []}]

    async def настройки(session):
        return {**mr.ДЕФОЛТЫ, "hidden_admins": [1]}

    monkeypatch.setattr(mr, "_все_админы", все)
    monkeypatch.setattr(mr, "load_settings", настройки)
    assert [a["name"] for a in await mr.current_admins(None)] == ["Дарья"]
    assert len(await mr.current_admins(None, скрытых=True)) == 2


def test_скрытые_сохраняются_номерами():
    assert mr._clean_settings({"hidden_admins": ["3", 1, 3]}) == {"hidden_admins": [1, 3]}
