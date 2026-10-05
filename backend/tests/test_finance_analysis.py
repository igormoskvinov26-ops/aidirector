"""Страница «Финансы»: разбор отчёта банка, расчётные остатки, сверка по дням, расходы."""

import base64
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.finance_analysis import router
from app.config import settings
from app.database import Base
from app.main import BasicAuthMiddleware
from app.models.models import AcquiringRow, Shift
from app.services import acquiring, cash_balances, finance_analysis as fa


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ШАПКА = ["Дата операции", "Номер карты", "Сумма операции, ₽", "Комиссия, ₽", "Сумма к зачислению, ₽"]


def test_разбор_находит_колонки_и_пропускает_итого():
    data = _xlsx([["Отчёт по эквайрингу"], [], ШАПКА,
                  [datetime(2026, 9, 26, 12, 0), "*1111", 2000, 36, 1964],
                  ["26.09.2026 15:30", "*2222", "1 500,50", 27, None],
                  ["Итого", None, 3500.5, 63, 3437.5]])
    r = acquiring.разобрать(data, "отчёт.xlsx")
    assert [(x["date"], x["amount"], x["fee"], x["net"]) for x in r["rows"]] == [
        (date(2026, 9, 26), Decimal("2000.00"), Decimal("36.00"), Decimal("1964.00")),
        (date(2026, 9, 26), Decimal("1500.50"), Decimal("27.00"), Decimal("1473.50")),
    ]
    assert r["skipped"] == 1


def test_разбор_csv_cp1251_с_точкой_с_запятой():
    text = "Дата;Сумма;Комиссия\n26.09.2026;1000,00;18,00\n"
    r = acquiring.разобрать(text.encode("cp1251"), "a.csv")
    assert r["rows"][0]["net"] == Decimal("982.00")


def test_непонятный_файл_отклоняется_с_заголовками():
    with pytest.raises(ValueError, match="Пришлите образец"):
        acquiring.разобрать(_xlsx([["Что-то", "Другое"], [1, 2]]), "x.xlsx")
    with pytest.raises(ValueError, match="xlsx"):
        acquiring.разобрать(b"x", "old.xls")


@pytest.mark.asyncio
async def test_повторная_загрузка_заменяет_даты(session: AsyncSession):
    data = _xlsx([ШАПКА, ["26.09.2026", "*1", 1000, 18, 982]])
    await acquiring.сохранить(session, data, "a.xlsx")
    await acquiring.сохранить(session, data, "a.xlsx")
    по_дням = await acquiring.по_дням(session, date(2026, 9, 1), date(2026, 9, 30))
    assert por_dnyam_amount(по_дням) == Decimal("1000.00")


def por_dnyam_amount(d):
    return sum(v["amount"] for v in d.values())


def _tx(day, amount, cash, sold=None, title=None, deleted=False):
    t = {"date": f"{day} 12:00:00", "amount": amount, "account": {"is_cash": cash},
         "sold_item_type": sold, "deleted": deleted}
    if title:
        t["expense"] = {"title": title}
    return t


def test_разнесение_расходов_и_переводов():
    движения, расходы = fa.разнести([
        _tx("2026-09-26", 5000, False, "service"),           # продажа — не здесь
        _tx("2026-09-26", -1000, True, None, "Закупка материалов"),
        _tx("2026-09-26", -3000, True, None, "Инкассация"),  # кассу → счёт
        _tx("2026-09-26", 3000, False, None, "Инкассация"),
        _tx("2026-09-26", -500, True, None, "Прочие расходы", deleted=True),
        _tx("2026-09-26", -700, False),                       # без статьи
    ])
    d = движения[date(2026, 9, 26)]
    assert d["cash"] == Decimal("-4000") and d["bank"] == Decimal("2300")
    свод = fa.расходы_по_статьям(расходы, [], Decimal("10000"))
    # «Без статьи» — то же системное движение денег, что и инкассация/перевод
    # (решение владельца 05.10.2026, сверено с отчётом YCLIENTS): не входит в
    # расходы и уходит в transfers вместе с инкассацией.
    assert свод["total"] == 1000.0 and свод["transfers"] == 3700.0
    assert {a["title"] for a in свод["articles"]} == {"Закупка материалов"}
    assert any("без статьи" in w.lower() for w in свод["watch"])


def test_рост_статьи_попадает_в_кандидаты():
    cur = [{"date": date(2026, 9, 2), "title": "Реклама", "amount": Decimal(20000), "cash": False,
            "transfer": False, "comment": ""}]
    prev = [{"date": date(2026, 8, 2), "title": "Реклама", "amount": Decimal(10000), "cash": False,
             "transfer": False, "comment": ""}]
    свод = fa.расходы_по_статьям(cur, prev, None)
    assert свод["articles"][0]["delta_pct"] == 100.0 and "выросла на 100%" in свод["watch"][0]


def _смена(day, non_cash, cash, closed=True):
    return Shift(shift_date=day, closed_at=datetime(2026, 1, 1, tzinfo=UTC) if closed else None,
                 closing_snapshot={"money": {"non_cash": non_cash, "cash": cash, "spent": 0}})


@pytest.mark.asyncio
async def test_остатки_и_сверка_по_дням(session: AsyncSession, monkeypatch):
    сегодня = date(2026, 9, 28)
    await cash_balances.сохранить(
        session, cash_amount=Decimal(10000), cash_as_of=date(2026, 9, 25),
        settlement_amount=Decimal(50000), settlement_as_of=date(2026, 9, 25),
        other_account_debt=Decimal(40000), other_debt_note="заняли")
    session.add_all([_смена(date(2026, 9, 26), 8000, 2000), _смена(date(2026, 9, 27), 6000, 1000)])
    # банк: 26-го совпало, 27-го не хватает 500
    session.add_all([
        AcquiringRow(op_date=date(2026, 9, 26), amount=8000, fee=144, net=7856, source_file="a"),
        AcquiringRow(op_date=date(2026, 9, 27), amount=5500, fee=99, net=5401, source_file="a"),
    ])
    await session.commit()

    async def fake(first, last):
        return [_tx("2026-09-26", -1500, True, None, "Закупка товаров"),
                _tx("2026-09-27", -20000, False, None, "Аренда")]

    monkeypatch.setattr(fa, "_транзакции", fake)
    r = await fa.build(session, "2026-09", today=сегодня)
    b = r["balances"]
    assert b["cash"]["calc"] == 10000 + 2000 - 1500 + 1000          # смена − расход наличкой
    assert b["rs"]["calc_yclients"] == 50000 + 8000 + 6000 - 20000
    # поправка на банк: (7856−8000)+(5401−6000) = −743
    assert b["rs"]["calc_bank"] == b["rs"]["calc_yclients"] - 743 and b["rs"]["bank_days"] == 2
    assert b["missing_closure_days"] == []                           # сегодня (28-е) не считаем
    assert r["debt"]["amount"] == 40000.0
    дни = {d["date"]: d for d in r["days"]}
    assert дни["2026-09-26"]["status"] == "ok" and дни["2026-09-27"]["status"] == "mismatch"
    assert дни["2026-09-27"]["diff"] == -500.0
    assert r["totals"]["mismatch_days"] == 1 and r["totals"]["diff_total"] == -500.0
    assert r["expenses"]["total"] == 21500.0


@pytest.mark.asyncio
async def test_без_остатков_и_без_закрытой_смены(session: AsyncSession, monkeypatch):
    async def fake(first, last):
        return []

    monkeypatch.setattr(fa, "_транзакции", fake)
    r = await fa.build(session, "2026-09", today=date(2026, 9, 10))
    assert r["balances"]["entered"] is False and r["debt"]["amount"] is None
    assert any("эквайринг" in w for w in r["warnings"])
    assert {d["status"] for d in r["days"]} <= {"no_data", "pending"}


@pytest.mark.asyncio
async def test_сбой_yclients_не_выдаёт_нули(session: AsyncSession, monkeypatch):
    async def boom(first, last):
        raise RuntimeError("down")

    monkeypatch.setattr(fa, "_транзакции", boom)
    await cash_balances.сохранить(
        session, cash_amount=Decimal(1), cash_as_of=date(2026, 9, 1), settlement_amount=Decimal(1),
        settlement_as_of=date(2026, 9, 1), other_account_debt=Decimal(0), other_debt_note=None)
    r = await fa.build(session, "2026-09", today=date(2026, 9, 10))
    assert r["expenses"] is None and r["balances"]["cash"]["calc"] is None
    assert any("недоступны" in w for w in r["warnings"])


def _auth(login, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("кто", [_auth(settings.operator_login, settings.operator_password),
                                 _auth("test-master", "test-master-password")])
def test_только_владельцу(client: TestClient, кто):
    assert client.get("/api/finance-analysis?month=2026-09", headers=кто).status_code == 403
    assert client.get("/api/finance-analysis/balances", headers=кто).status_code == 403
    assert client.post("/api/finance-analysis/acquiring", headers=кто, content=b"x").status_code == 403
    assert client.get("/api/finance-analysis?month=2026-09").status_code == 401


def test_миграция_совпадает_с_моделью():
    import re
    текст = (Path(__file__).resolve().parent.parent / "alembic" / "versions"
             / "0011_acquiring_rows.py").read_text(encoding="utf-8")
    колонки = set(re.findall(r'sa\.Column\(\s*"([a-z_]+)"', текст))
    assert колонки == {c.name for c in AcquiringRow.__table__.columns}


АЛЬФА = (
    '"Наименование банка ""Альфа-Банк""";;;;\n'
    "Наименование предприятия ИП;;;;\n"
    "За период 01.10.2026 по 01.10.2026;;;;\n"
    "Сумма транзакций;6550.00;;;\n"
    "Сумма комиссий с НДС;-79.91;;;\n"
    "Сумма транзакций без комиссий;6470.09;;;\n"
    "Дата операции;Время операции;Сумма транзакции;Тип операции;Сумма комиссии с НДС;"
    "Сумма без комиссии;Комиссия без учета НДС\n"
    "30.09.2026;11:49:14;2300.00;кредит;-28.06;2271.94;-23.00\n"
    "30.09.2026;14:48:42;4250.00;кредит;-51.85;4198.15;-42.50\n"
)


def test_отчёт_альфа_банка_сходится_с_итогом_шапки():
    r = acquiring.разобрать(АЛЬФА.encode("cp1251"), "94771706.csv")
    assert [(x["date"], x["amount"], x["fee"], x["net"]) for x in r["rows"]] == [
        (date(2026, 9, 30), Decimal("2300.00"), Decimal("28.06"), Decimal("2271.94")),
        (date(2026, 9, 30), Decimal("4250.00"), Decimal("51.85"), Decimal("4198.15")),
    ]
    assert r["header_total"] == Decimal("6550.00") and r["matches_header"] is True


def test_возврат_вычитается_и_итог_шапки_ловит_расхождение():
    текст = АЛЬФА + "30.09.2026;16:00:00;1000.00;дебет;-12.00;988.00;-10.00\n"
    r = acquiring.разобрать(текст.encode("cp1251"), "a.csv")
    assert r["rows"][-1]["amount"] == Decimal("-1000.00")
    assert r["matches_header"] is False


def test_группы_сравниваются_по_доле_дохода_а_не_рублям():
    """Аренда та же в рублях, но доход упал — доля выросла, это и надо показать."""
    from datetime import date as d
    from decimal import Decimal as D

    from app.services.finance_analysis import расходы_по_статьям

    x = lambda title, amount: {"date": d(2026, 10, 1), "title": title, "amount": D(amount),  # noqa: E731
                               "cash": False, "transfer": False, "comment": ""}
    r = расходы_по_статьям([x("Аренда", 100000)], [x("Аренда", 100000)], None,
                           доход=D(400000), доход_прошлый=D(500000))
    g = r["groups"][0]
    assert g["pct_of_income"] == 25.0 and g["prev_pct_of_income"] == 20.0 and g["delta_pp"] == 5.0
    assert r["expenses_pct_of_income"] == 25.0
