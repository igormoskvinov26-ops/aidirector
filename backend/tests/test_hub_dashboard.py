"""Витрина владельца на телефоне: отдельный редкий пуш, не часть обмен().

Выделена из test_hub.py: обмен() не должен знать о витрине — её расчёт
дёргает YCLIENTS, и к обычному протоколу синхронизации отношения не имеет.
"""

import importlib.util
import sys
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import Base
from app.services import hub

HUB_FILE = Path(__file__).resolve().parents[2] / "hub" / "app.py"


def _server(tmp_path, monkeypatch, suffix=""):
    monkeypatch.setenv("HUB_TOKEN", "k")
    monkeypatch.setenv("HUB_DB", str(tmp_path / "hub.db"))
    spec = importlib.util.spec_from_file_location(f"hub_app_dashboard{suffix}", HUB_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"hub_app_dashboard{suffix}"] = mod
    spec.loader.exec_module(mod)
    return mod.app


async def _install(tmp_path, name):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://hub",
        headers={"Authorization": "Bearer k"},
    )


async def test_витрина_пушится_отдельно_и_не_повторяется(tmp_path, monkeypatch):
    app = _server(tmp_path, monkeypatch)
    install = await _install(tmp_path, "a")

    async def fake_finance(session, today=None):
        return {"profit": {"value": 1000.0}}

    async def fake_pulse(session):
        return {"base_total": 42}

    async def fake_flow(session):
        return {"total": 5}

    monkeypatch.setattr("app.services.owner_overview.построить", fake_finance)
    monkeypatch.setattr("app.services.client_base.build_base_pulse", fake_pulse)
    monkeypatch.setattr("app.services.client_base.build_base_flow", fake_flow)
    monkeypatch.setattr("app.services.configuration.настроена", lambda ид: True)

    async with install() as session, _client(app) as c:
        assert await hub.протолкнуть_витрину(session, c) is True
        assert await hub.протолкнуть_витрину(session, c) is False  # не изменилось — не пушим

        r = await c.get("/v1/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["finance"]["profit"]["value"] == 1000.0
        assert body["base_pulse"]["base_total"] == 42
        assert body["base_flow"]["total"] == 5
        assert "updated_at" in body

        fake_pulse_updated = {"base_total": 43}

        async def fake_pulse2(session):
            return fake_pulse_updated

        monkeypatch.setattr("app.services.client_base.build_base_pulse", fake_pulse2)
        assert await hub.протолкнуть_витрину(session, c) is True
        assert (await c.get("/v1/dashboard")).json()["base_pulse"]["base_total"] == 43


async def test_витрина_пропускается_если_ничего_не_посчиталось(tmp_path, monkeypatch):
    app = _server(tmp_path, monkeypatch, suffix="2")
    install = await _install(tmp_path, "b")

    async def none_finance(session, today=None):
        raise RuntimeError("YCLIENTS недоступен")

    async def none_pulse(session):
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr("app.services.owner_overview.построить", none_finance)
    monkeypatch.setattr("app.services.client_base.build_base_pulse", none_pulse)
    monkeypatch.setattr("app.services.configuration.настроена", lambda ид: True)

    async with install() as session, _client(app) as c:
        assert await hub.протолкнуть_витрину(session, c) is False
        assert (await c.get("/v1/dashboard")).status_code == 404


async def test_без_ключа_дашборд_закрыт(tmp_path, monkeypatch):
    app = _server(tmp_path, monkeypatch, suffix="3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub") as c:
        assert (await c.get("/v1/dashboard")).status_code == 401
