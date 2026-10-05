"""Месячный отчёт: сценарии A–R из ТЗ плюс граничные случаи."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, ContactAttempt, ContactTask
from app.services import monthly_report as mr

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=MSK)
SEP = mr.parse_month("2026-09")
OCT = mr.parse_month("2026-10")
RULE = {"staff_id": 7, "name": "Ксения"}

CFG = {
    "targets": {"extra_services_norm": 35, "sales_ratio_norm_pct": 10},
    "extra_service_ids": [900],
    "admins": [{"staff_id": 50, "name": "Евгения", "creator_values": ["501"]}],
    "attribution_window_days": 3,
    "record_created_field": "create_date",
    "record_creator_field": "created_user_id",
    "horizon_days": 60,
}


def rec(rid, *, staff=7, client=1, visit="2026-09-10T12:00:00+0300", attendance=1,
        services=None, deleted=False, created=None, creator=None):
    services = services if services is not None else [{"id": 1, "title": "Стрижка", "amount": 1, "cost": 2000}]
    r = {"id": rid, "staff_id": staff, "client": {"id": client} if client else None,
         "datetime": visit, "visit_attendance": attendance, "services": services, "deleted": deleted}
    if created:
        r["create_date"] = created
    if creator is not None:
        r["created_user_id"] = creator
    return r


def master(records, products=None, cfg=CFG, period=SEP):
    return mr.master_month(records, products, None, RULE, *period, NOW, cfg)


# ── Мастера ───────────────────────────────────────────────────────────────


def test_A_одна_выполненная_запись():
    m = master([rec(1)])
    assert m["revenue"] == 2000 and m["visits"] == 1 and m["avg_check"] == 2000


def test_B_несколько_услуг_один_визит():
    lines = [{"id": 1, "amount": 1, "cost": 1500}, {"id": 2, "amount": 1, "cost": 500}]
    m = master([rec(1, services=lines), rec(2, visit="2026-09-11T12:00:00+0300")])
    assert m["visits"] == 2 and m["revenue"] == 4000 and m["avg_check"] == 2000


def test_C_отмена_не_входит():
    m = master([rec(1), rec(2, attendance=-1), rec(3, deleted=True), rec(4, attendance=0)])
    assert m["visits"] == 1 and m["revenue"] == 2000


def test_C2_блокировка_без_клиента_и_будущая_запись_не_входят():
    future = rec(5, visit="2026-10-25T12:00:00+0300")
    m = master([rec(1), rec(2, client=None), future], period=OCT)
    assert m["visits"] == 0
    assert master([rec(1), rec(2, client=None)])["visits"] == 1


def test_D_товар_не_услуги():
    products = [{"staff_id": 7, "date": "2026-09-12", "amount": "300", "title": "Воск"}]
    m = master([rec(1)], products)
    assert m["product_sales"] == 300 and m["revenue"] == 2000


def test_D2_продажи_недоступны_не_ноль():
    m = master([rec(1)], None)
    assert m["product_sales"] is None and m["sales_ratio_pct"] is None and m["sales_met"] is None


def test_E_продажи_ровно_10_процентов():
    m = master([rec(1)], [{"staff_id": 7, "date": "2026-09-12", "amount": "200"}])
    assert m["sales_ratio_pct"] == 10.0 and m["sales_met"] is True and m["sales_missing"] == 0


def test_E2_недостающая_сумма():
    m = master([rec(1)], [{"staff_id": 7, "date": "2026-09-12", "amount": "50"}])
    assert m["sales_met"] is False and m["sales_missing"] == 150


def test_E3_услуг_нет_доля_прочерк():
    m = master([], [{"staff_id": 7, "date": "2026-09-12", "amount": "50"}])
    assert m["revenue"] == 0 and m["sales_ratio_pct"] is None


def _extra(n):
    return rec(1, services=[{"id": 900, "title": "Камуфляж", "amount": n, "cost": 500}])


def test_F_34_допуслуги_не_выполнена():
    e = master([_extra(34)])["extra_services"]
    assert e["count"] == 34 and e["met"] is False and e["pct"] == 97.14


def test_G_35_допуслуг_выполнена():
    e = master([_extra(35)])["extra_services"]
    assert e["count"] == 35 and e["met"] is True


def test_G2_список_допуслуг_пуст_не_ноль():
    e = master([_extra(40)], cfg={**CFG, "extra_service_ids": []})["extra_services"]
    assert e["configured"] is False and e["count"] is None and e["met"] is None


def test_H_нет_прошлого_месяца():
    cur = mr.add_master_deltas(master([rec(1)]), None)
    assert cur["avg_check_delta"] is None and cur["hour_cost_delta"] is None


def test_I_прошлый_ноль_без_деления():
    assert mr.delta_pct(100, 0) is None
    assert mr.delta_pct(None, 100) is None
    assert mr.delta_pct(110, 100) == 10.0
    assert mr.delta_pct(90, 100) == -10.0


def test_часы_из_графика_и_нераспознанный_формат():
    sched = [{"staff_id": 7, "date": "2026-09-10", "slots": [{"from": "10:00", "to": "18:00"}]}]
    hours, note = mr.parse_hours(sched, 7, *SEP, NOW)
    assert hours == 8.0 and note is None
    m = mr.master_month([rec(1)], None, sched, RULE, *SEP, NOW, CFG)
    assert m["hour_cost"] == 250.0
    hours, note = mr.parse_hours([{"staff_id": 7, "date": "2026-09-10", "slots": ["10:00"]}], 7, *SEP, NOW)
    assert hours is None and "не распознан" in note
    assert mr.parse_hours(None, 7, *SEP, NOW)[0] is None


def test_другой_мастер_не_попадает():
    assert master([rec(1, staff=8)])["visits"] == 0


# ── Администраторы: записи ────────────────────────────────────────────────


def test_J_запись_создана_30_09_на_15_10_относится_к_сентябрю():
    r = rec(1, visit="2026-10-15T12:00:00+0300", attendance=0,
            created="2026-09-30T18:00:00+0300", creator=501)
    sep = mr.admin_records([r], CFG, *SEP, NOW)
    octo = mr.admin_records([r], CFG, *OCT, NOW)
    assert sep["by_admin"][50]["made"]["count"] == 1
    assert sep["by_admin"][50]["made"]["sum"] == 2000
    assert 50 not in octo["by_admin"] or octo["by_admin"][50]["made"]["count"] == 0


def test_K_отмена_не_входит_в_закрыто():
    ok = rec(1, created="2026-09-01T10:00:00+0300", creator=501)
    cancelled = rec(2, attendance=-1, created="2026-09-02T10:00:00+0300", creator=501)
    out = mr.admin_records([ok, cancelled], CFG, *SEP, NOW)["by_admin"][50]
    assert out["closed"]["count"] == 1
    assert out["made"]["count"] == 2  # факт создания сохраняется


def test_поля_не_подтверждены_нет_данных():
    out = mr.admin_records([rec(1)], {**CFG, "record_creator_field": ""}, *SEP, NOW)
    assert out["available"] is False and "автор записи" in out["reason"]


def test_автор_вне_списка_не_приписывается_администратору():
    out = mr.admin_records([rec(1, created="2026-09-01T10:00:00+0300", creator=999)], CFG, *SEP, NOW)
    assert out["by_admin"] == {} and out["unassigned"] == 1


# ── Проверка «Записан» ────────────────────────────────────────────────────

CLICK = datetime(2026, 10, 1, 12, 0, tzinfo=MSK)


def att(aid, outcome="booked", client=1, at=CLICK, status=None, record_id=None):
    return mr.Att(id=aid, client_yid=client, outcome=outcome, clicked_at=at,
                  status=status, record_id=record_id)


def booking(rid, created, client=1):
    return rec(rid, client=client, visit="2026-10-15T12:00:00+0300", attendance=0, created=created)


def test_L_запись_и_реальный_booking_confirmed():
    m = mr.match_attempts([att(1)], [booking(10, "2026-10-01T13:00:00+0300")], CFG, NOW)
    assert m.decisions[1].status == mr.CONFIRMED and m.decisions[1].record_id == 10


def test_M_booking_нет_после_окна_not_confirmed():
    m = mr.match_attempts([att(1)], [], CFG, NOW)  # окно 3 дня, сейчас 20.10
    assert m.decisions[1].status == mr.NOT_CONFIRMED


def test_M2_окно_открыто_pending():
    fresh = att(1, at=NOW - timedelta(hours=2))
    assert mr.match_attempts([fresh], [], CFG, NOW).decisions[1].status == mr.PENDING


def test_запись_до_звонка_не_подтверждает():
    before = booking(10, "2026-10-01T09:00:00+0300")
    assert mr.match_attempts([att(1)], [before], CFG, NOW).decisions[1].status == mr.NOT_CONFIRMED


def test_запись_позже_окна_не_подтверждает():
    late = booking(10, "2026-10-09T09:00:00+0300")
    assert mr.match_attempts([att(1)], [late], CFG, NOW).decisions[1].status == mr.NOT_CONFIRMED


def test_запись_другого_клиента_не_подтверждает():
    other = booking(10, "2026-10-01T13:00:00+0300", client=2)
    assert mr.match_attempts([att(1)], [other], CFG, NOW).decisions[1].status == mr.NOT_CONFIRMED


def test_O_другая_кнопка_но_запись_появилась_расхождение():
    m = mr.match_attempts([att(1, "no_booking")], [booking(10, "2026-10-01T13:00:00+0300")], CFG, NOW)
    assert m.discrepancies == {1: 10} and 1 not in m.decisions


def test_P_два_звонка_один_booking():
    second = att(2, at=CLICK + timedelta(hours=1))
    m = mr.match_attempts([att(1), second], [booking(10, "2026-10-01T15:00:00+0300")], CFG, NOW)
    statuses = sorted(d.status for d in m.decisions.values())
    assert statuses == [mr.CONFIRMED, mr.NOT_CONFIRMED]


def test_P2_запись_ушла_booked_а_не_расхождению():
    m = mr.match_attempts([att(1, "no_answer"), att(2, at=CLICK + timedelta(hours=1))],
                          [booking(10, "2026-10-01T15:00:00+0300")], CFG, NOW)
    assert m.decisions[2].status == mr.CONFIRMED and m.discrepancies == {}


def test_Q_подтверждённая_запись_потом_отменена():
    cancelled = booking(10, "2026-10-01T13:00:00+0300")
    cancelled["visit_attendance"] = -1
    m = mr.match_attempts([att(1)], [cancelled], CFG, NOW)
    assert m.decisions[1].status == mr.CONFIRMED
    closed = mr.admin_records([{**cancelled, "created_user_id": 501}], CFG, *OCT, NOW)
    assert closed["by_admin"][50]["closed"]["count"] == 0


def test_R_пять_ошибочных_нажатий_ноль_подтверждений():
    attempts = [att(i, at=CLICK + timedelta(minutes=i)) for i in range(1, 6)]
    m = mr.match_attempts(attempts, [], CFG, NOW)
    counts = mr._counts(attempts, m)
    assert counts["booked_clicks"] == 5 and counts["confirmed"] == 0 and counts["not_confirmed"] == 5
    assert counts["button_accuracy_pct"] == 0.0


def test_подтверждённый_звонок_держит_свою_запись():
    done = att(1, status=mr.CONFIRMED, record_id=10)
    again = att(2, at=CLICK + timedelta(hours=1))
    m = mr.match_attempts([done, again], [booking(10, "2026-10-01T15:00:00+0300")], CFG, NOW)
    assert m.decisions[1].status == mr.CONFIRMED and m.decisions[2].status == mr.NOT_CONFIRMED


def test_дата_создания_без_времени_сравнивается_по_дате():
    same_day = booking(10, "2026-10-01")
    assert mr.match_attempts([att(1)], [same_day], CFG, NOW).decisions[1].status == mr.CONFIRMED


def test_поле_создания_не_подтверждено_pending_а_не_not_confirmed():
    m = mr.match_attempts([att(1)], [], {**CFG, "record_created_field": ""}, NOW)
    assert m.decisions[1].status == mr.PENDING and "не подтверждено" in m.decisions[1].note


def test_метрики_обзвона_и_конверсии():
    attempts = [att(1), att(2, client=2), att(3, "no_booking", client=3), att(4, "no_answer", client=4)]
    m = mr.match_attempts(attempts, [booking(10, "2026-10-01T13:00:00+0300")], CFG, NOW)
    c = mr._counts(attempts, m)
    assert (c["total"], c["booked_clicks"], c["confirmed"], c["not_confirmed"]) == (4, 2, 1, 1)
    assert c["button_accuracy_pct"] == 50.0
    assert c["conv_contacts_pct"] == 33.33 and c["conv_all_pct"] == 25.0
    assert mr._counts([], mr.Match())["button_accuracy_pct"] is None


# ── Статус месяца и целостность ───────────────────────────────────────────


def test_статус_месяца():
    assert mr.month_status("2026-10", NOW) == "preliminary"
    assert mr.month_status("2026-09", NOW) == "final"
    with pytest.raises(ValueError):
        mr.parse_month("сентябрь")


def test_целостность():
    m = master([rec(1)], [{"staff_id": 7, "date": "2026-09-12", "amount": "-50"}])
    checks = mr.integrity_checks([m], [])
    assert any(not c["ok"] for c in checks)
    bad = {"name": "Х", "calls": {"confirmed": 3, "booked_clicks": 2}}
    assert mr.integrity_checks([], [bad])[0]["ok"] is False


def test_описание_полей_скрывает_личное():
    info = mr.describe_record_fields([{"id": 1, "create_date": "2026-09-30T10:00:00+0300",
                                       "created_user_id": 5, "comment": "секрет"}])
    assert info["date_candidates"] == ["create_date"] and info["creator_candidates"] == ["created_user_id"]
    assert info["keys"]["comment"]["example"] == "***"


# ── База: проверка и отказ YCLIENTS ───────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _call(session, created_at, outcome="booked"):
    client = await session.get(Client, 1)
    if client is None:
        client = Client(id=1, yclients_id=1, name="Иван", phone="+79990000000")
        session.add(client)
        await session.flush()
    task = ContactTask(client_id=1, group_code=f"g{created_at:%H%M}{outcome}", due_date=date(2026, 10, 1), status="done")
    session.add(task)
    await session.flush()
    attempt = ContactAttempt(task_id=task.id, outcome=outcome, channel="phone", actor_id="Евгения",
                             admin_staff_id=50, created_at=created_at,
                             verification_status="pending" if outcome == "booked" else None)
    session.add(attempt)
    await session.commit()
    return attempt.id


async def _set_fields(session):
    await mr.save_settings(session, {"record_created_field": "create_date", "admins": CFG["admins"]})


@pytest.mark.asyncio
async def test_N_yclients_недоступен_error_а_не_not_confirmed(session, monkeypatch):
    await _set_fields(session)
    aid = await _call(session, datetime(2026, 10, 1, 12, 0, tzinfo=MSK))

    async def boom(*a, **k):
        raise RuntimeError("YCLIENTS down")

    monkeypatch.setattr(mr, "load_source", boom)
    out = await mr.verify_pending(session, NOW)
    row = await session.get(ContactAttempt, aid)
    assert row.verification_status == mr.ERROR and out["error"] == 1 and out["not_confirmed"] == 0
    assert row.yclients_record_id is None


@pytest.mark.asyncio
async def test_проверка_сохраняет_confirmed_и_повтор_не_дублирует(session, monkeypatch):
    await _set_fields(session)
    a1 = await _call(session, datetime(2026, 10, 1, 12, 0, tzinfo=MSK))
    a2 = await _call(session, datetime(2026, 10, 1, 13, 0, tzinfo=MSK))
    src = mr.Source([booking(10, "2026-10-01T14:00:00+0300")], {}, {}, [], NOW)

    async def fake(*a, **k):
        return src

    monkeypatch.setattr(mr, "load_source", fake)
    await mr.verify_pending(session, NOW)
    await mr.verify_pending(session, NOW)
    r1, r2 = await session.get(ContactAttempt, a1), await session.get(ContactAttempt, a2)
    assert r1.verification_status == mr.CONFIRMED and r1.yclients_record_id == 10
    assert r2.verification_status == mr.NOT_CONFIRMED and r2.yclients_record_id is None
    assert r1.verified_at is not None


@pytest.mark.asyncio
async def test_без_поля_создания_проверка_не_меняет_статус(session, monkeypatch):
    monkeypatch.setitem(mr.ДЕФОЛТЫ, "record_created_field", "")  # поле по умолчанию убрано
    aid = await _call(session, datetime(2026, 10, 1, 12, 0, tzinfo=MSK))
    out = await mr.verify_pending(session, NOW)
    assert out["pending"] == 1 and "не подтверждено" in out["warning"]
    assert (await session.get(ContactAttempt, aid)).verification_status == mr.PENDING


@pytest.mark.asyncio
async def test_настройки_проверяются_и_сохраняются(session):
    cfg = await mr.save_settings(session, {"targets": {"extra_services_norm": 40, "sales_ratio_norm_pct": 12},
                                           "extra_service_ids": [3, 3, 5], "attribution_window_days": 5})
    assert cfg["targets"]["extra_services_norm"] == 40 and cfg["extra_service_ids"] == [3, 5]
    with pytest.raises(ValueError):
        await mr.save_settings(session, {"attribution_window_days": 99})
    with pytest.raises(ValueError):
        await mr.save_settings(session, {"record_created_field": "create date; drop"})
    assert (await mr.load_settings(session))["attribution_window_days"] == 5



async def test_today_authors_skips_api_and_other_days(monkeypatch):
    from datetime import datetime, timedelta
    from app.api import yclients
    now = datetime.now(mr.MOSCOW)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S+0300")
    base = {"client": {"id": 1}, "datetime": iso(now + timedelta(days=3)), "deleted": False}
    rows = [dict(base, id=1, create_date=iso(now), created_user_id=777),
            dict(base, id=2, create_date=iso(now), created_user_id=4058773, api_id="x"),
            dict(base, id=3, create_date=iso(now - timedelta(days=2)), created_user_id=888),
            dict(base, id=4, create_date=iso(now), created_user_id=777, deleted=True)]

    class Fake:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get_all_records(self, a, b): return rows

    monkeypatch.setattr(yclients, "YClientsClient", Fake)
    out = await mr.today_authors()
    assert [a["value"] for a in out["authors"]] == ["777"] and out["via_api"] == 1
    assert out["authors"][0]["count"] == 2 and out["authors"][0]["deleted"] == 1


@pytest.mark.asyncio
async def test_администраторы_определяются_по_авторам_записей(monkeypatch):
    cfg = {"admins": [], "record_creator_field": "created_user_id"}
    recs = [
        {"id": 1, "created_user_id": 900, "client": {"id": 1}},
        {"id": 2, "created_user_id": 900, "client": {"id": 2}},
        {"id": 3, "created_user_id": 901, "client": {"id": 3}},
        {"id": 4, "created_user_id": 902, "api_id": 5, "client": {"id": 4}},  # онлайн-запись
        {"id": 5, "created_user_id": 903, "client": {"id": 5}},                 # мастер
    ]

    async def fake_cached(key, loader, ttl=None):
        return {"900": "Виктор"}, {"903": {"staff_id": 5659614, "name": "Ксения"}}

    monkeypatch.setattr(mr, "cached", fake_cached)
    out = await mr.auto_admins(cfg, recs)
    assert [(a["staff_id"], a["name"], a["creator_values"]) for a in out] == [
        (900, "Виктор", ["900"]), (901, "Сотрудник №901", ["901"])]
