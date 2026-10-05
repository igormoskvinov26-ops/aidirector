import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import Base

from app.config import settings
from app.services import salon


def test_default_rules_kept_for_rubl(monkeypatch):
    monkeypatch.setattr(settings, "yclients_company_id", salon.RUBL_COMPANY)
    salon._применить(None, None, None)
    assert [b["staff_id"] for b in settings.barber_payroll_rules] == [5659614, 5659611, 5659617]
    assert salon.name == "РублЪ" and salon.booking_url == "n2387007.yclients.com"


def test_other_company_starts_empty(monkeypatch):
    monkeypatch.setattr(settings, "yclients_company_id", 777)
    salon._применить(None, "Борода", None)
    assert settings.barber_payroll_rules == [] and salon.name == "Борода" and salon.booking_url == ""
    salon._применить(None, None, None)
    monkeypatch.setattr(settings, "yclients_company_id", 0)
    salon._применить(None, None, None)


def test_validation():
    ok = salon._проверить_барберов([{"staff_id": "5", "name": "А", "service_rate": 0.5, "product_rate": 0.1}])
    assert ok[0]["staff_id"] == 5 and ok[0]["guarantee"] == 0
    with pytest.raises(ValueError):
        salon._проверить_барберов([{"staff_id": 1, "name": "А", "service_rate": 40, "product_rate": 0.1}])


def test_new_branch_never_inherits_rubl_values(monkeypatch):
    monkeypatch.setattr(settings, "yclients_company_id", 0)
    monkeypatch.setattr(salon, "главная", False)
    salon._применить(None, None, None)
    assert settings.barber_payroll_rules == [] and salon.booking_url == ""


def test_hub_keys_are_namespaced_for_branches(monkeypatch):
    from app.services import branches, configuration, hub

    monkeypatch.setattr(branches, "active", "main")
    assert hub._префикс() == "" and hub._свой_ключ("shift:1", "") == "shift:1"
    assert hub._свой_ключ("c7.shift:1", "") is None  # чужой филиал не попадает в главный
    monkeypatch.setattr(branches, "active", "b1")
    monkeypatch.setattr(configuration, "число", lambda _: 7)
    assert hub._префикс() == "c7." and hub._свой_ключ("c7.shift:1", "c7.") == "shift:1"
    assert hub._свой_ключ("shift:1", "c7.") is None


def test_branch_accounts_are_separate(monkeypatch):
    from app.services import credentials

    monkeypatch.setitem(credentials._ветка, "OWNER_LOGIN", "m")
    monkeypatch.setitem(credentials._ветка, "OWNER_PASSWORD_HASH", credentials._хеш("manager-pass-123"))
    assert credentials.проверить_пароль("owner", "m", "manager-pass-123", ветка=True)
    assert not credentials.проверить_пароль("owner", "m", "manager-pass-123")


def test_routes_with_path_params_are_reachable(monkeypatch):
    """Регрессия: кириллическое имя параметра пути делало маршрут недостижимым
    (на живой установке «Проверить подключение» отвечало 405)."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "owner_login", "owner-login-x")
    monkeypatch.setattr(settings, "owner_password", "owner-password-long-1")
    c = TestClient(app)
    auth = ("owner-login-x", "owner-password-long-1")
    r = c.post("/api/settings/test/hub", auth=auth)
    assert r.status_code == 200 and "ok" in r.json()


@pytest.mark.asyncio
async def test_barbers_detected_from_visits(session, monkeypatch):
    from datetime import UTC, datetime

    from app.models.models import Client, Employee, Visit

    monkeypatch.setattr(settings, "barber_payroll_rules",
                        [{"staff_id": 1, "name": "А", "service_rate": 0.5, "product_rate": 0.2, "guarantee": 0}])
    monkeypatch.setattr(salon, "главная", False)
    c = Client(yclients_id=1, name="К", phone="+79990000000"); session.add(c)
    a, b, w = (Employee(yclients_id=i, name=n) for i, n in ((1, "А"), (2, "Б"), (3, "Лист Ожидания")))
    session.add_all([a, b, w]); await session.flush()
    for k, e in enumerate((a, b, w)):
        session.add(Visit(yclients_id=100 + k, client_id=c.id, employee_id=e.id,
                          datetime=datetime.now(UTC), status="completed"))
    await session.commit()
    assert await salon.определить_барберов(session) == 1
    assert [x["staff_id"] for x in settings.barber_payroll_rules] == [1, 2]
    assert settings.barber_payroll_rules[1]["service_rate"] == 0.5  # ставки по образцу первого
    await salon.сохранить(session, barbers=[settings.barber_payroll_rules[0]])  # «Б» убрали вручную
    assert await salon.определить_барберов(session) == 0  # и он не возвращается


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


def test_waiting_list_is_never_a_barber(monkeypatch):
    for n in ("Лист Ожидания", "лист ожидания", "  Лист  ожидания ", "Лист Ожиданий"):
        assert salon.служебный(n)
    assert not salon.служебный("Ксения")
    salon._применить([{"staff_id": 9, "name": "лист ожидания", "service_rate": .4, "product_rate": .1, "guarantee": 4000},
                      {"staff_id": 1, "name": "Ксения", "service_rate": .4, "product_rate": .1, "guarantee": 4000}], None, None)
    assert [b["name"] for b in settings.barber_payroll_rules] == ["Ксения"]


@pytest.mark.asyncio
async def test_waiting_list_not_in_finance(session):
    from datetime import UTC, datetime, date

    from app.models.models import Client, Employee, Visit
    from app.services import finance

    c = Client(yclients_id=1, name="К", phone="+79990000000"); session.add(c)
    a, w = Employee(yclients_id=1, name="А"), Employee(yclients_id=3, name="Лист Ожидания")
    session.add_all([a, w]); await session.flush()
    for k, e in enumerate((a, w)):
        session.add(Visit(yclients_id=100 + k, client_id=c.id, employee_id=e.id,
                          datetime=datetime.now(UTC), total_amount=1000, status="completed"))
    await session.commit()
    day = datetime.now(UTC).date()
    assert [m["name"] for m in await finance._today_by_master(session, day)] == ["А"]
    assert await finance._get_masters_count(session, day) == 1
    rows = await finance.get_daily_finance(session, day, day)
    assert rows[0]["masters_count"] == 1
