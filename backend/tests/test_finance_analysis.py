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
    assert свод["total"] == 1700.0 and свод["transfers"] == 3000.0
    assert {a["title"] for a in свод["articles"]} == {"Закупка материалов", "Без статьи"}
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
    """Колонку добавили в модель, а миграцию забыли — таблицы не будет."""
    import re
    папка = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    колонки: set[str] = set()
    for файл in ("0011_acquiring_rows.py", "0013_acquiring_source.py"):
        текст = (папка / файл).read_text(encoding="utf-8")
        колонки |= set(re.findall(r'sa\.Column\(\s*"([a-z_]+)"', текст))
        колонки |= set(re.findall(r'^КОЛОНКА = "([a-z_]+)"', текст, re.M))
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


@pytest.mark.asyncio
async def test_сбп_и_эквайринг_за_один_день_складываются(session):
    """Второй файл за тот же день больше не затирает первый."""
    from app.services.acquiring import по_дням, сохранить

    # Имена у Альфа-Банка из одних цифр, различать приходится по шапке файла.
    карты = ("Отчёт по эквайрингу;;\nДата операции;Сумма транзакции\n05.10.2026;10000,00\n").encode("utf-8")
    сбп = ("Реестр операций СБП;;\nДата операции;Сумма транзакции\n05.10.2026;2500,00\n").encode("utf-8")

    await сохранить(session, карты, "94771706.csv")
    итог = await сохранить(session, сбп, "94771810.csv")
    assert итог["source"] == "СБП"

    день = (await по_дням(session, date(2026, 10, 5), date(2026, 10, 5)))[date(2026, 10, 5)]
    assert день["amount"] == Decimal("12500.00")
    assert день["by_source"] == {"Эквайринг": Decimal("10000.00"), "СБП": Decimal("2500.00")}

    # Повторная загрузка того же потока заменяет только его.
    исправленный = ("Реестр операций СБП;;\nДата операции;Сумма транзакции\n05.10.2026;3000,00\n").encode("utf-8")
    await сохранить(session, исправленный, "94771999.csv")
    день = (await по_дням(session, date(2026, 10, 5), date(2026, 10, 5)))[date(2026, 10, 5)]
    assert день["by_source"] == {"Эквайринг": Decimal("10000.00"), "СБП": Decimal("3000.00")}


@pytest.mark.asyncio
async def test_строки_без_потока_заменяются_первой_же_загрузкой(session):
    """Строки, загруженные до 0013: сложить их с новыми — посчитать день дважды."""
    from app.models.models import AcquiringRow
    from app.services.acquiring import по_дням, сохранить

    session.add(AcquiringRow(op_date=date(2026, 10, 6), amount=Decimal("9000"), fee=Decimal(0),
                             net=Decimal("9000"), source_file="старый.csv", source=""))
    await session.commit()
    await сохранить(session, ("Дата операции;Сумма транзакции\n06.10.2026;9100,00\n").encode("utf-8"),
                    "94771706.csv")
    день = (await по_дням(session, date(2026, 10, 6), date(2026, 10, 6)))[date(2026, 10, 6)]
    assert день["amount"] == Decimal("9100.00")


def test_поток_определяется_по_шапке_а_не_по_имени():
    """У Альфа-Банка имя файла — одни цифры, различать можно только содержимым."""
    шапка = "Дата операции;Сумма транзакции\n05.10.2026;100,00\n"
    карты = acquiring.разобрать((f"Отчёт по эквайрингу;;\n{шапка}").encode("utf-8"), "94771706.csv")
    сбп = acquiring.разобрать((f"Реестр операций СБП;;\n{шапка}").encode("utf-8"), "94771810.csv")
    словами = acquiring.разобрать((f"Система быстрых платежей;;\n{шапка}").encode("utf-8"), "a.csv")
    по_имени = acquiring.разобрать(шапка.encode("utf-8"), "Реестр СБП за 05.10.csv")
    assert карты["source"] == "Эквайринг"
    assert сбп["source"] == сбп["source"] == "СБП"
    assert словами["source"] == "СБП" and по_имени["source"] == "СБП"
    # Ничего не нашли — считаем эквайрингом: третьего потока у салона нет.
    assert acquiring.разобрать(шапка.encode("utf-8"), "94771706.csv")["source"] == "Эквайринг"


# Настоящий реестр СБП Альфа-Банка (Игорь прислал 09.10.2026). Файл в cp1251,
# слова «СБП» есть только в названиях колонок — по имени файла его не узнать.
РЕЕСТР_СБП = (
    "Дата успешной авторизации операции;Время успешной авторизации операции;"
    "Уникальный идентификатор операции в СБП;"
    "Идентификатор зарегистрированного QR кода в СБП;Наименование ЮЛ;"
    "Идентификатор ТСП;Номер счета;Тип QR кода;БИК Банка Плательщика;"
    "Сумма транзакции;Тип операции;Номер терминала;Сумма комиссии;"
    "Сумма без комиссии ;Валюта;Назначение платежа;Наименование ТСТ;"
    "Идентификатор ТСТ;Идентификатор Операции оплаты;Референс операции\n"
    "06.10.2026;11:38:26;B6279083825988270G10180011860303;"
    "BD10107GHCMJ0P959EOBAI55TGIHCKCR;Индивидуальный предприниматель;"
    "LB0003414804;30233**********97532;QRDyn;044525974;2300;Кредит;94771708;"
    "-16.10;2283.9;RUB;Возм. по согл. в СБП № 350703733403 от Платеж СБП;"
    "Барбершоп 44;MB0003034518;;C300610260585767\n"
)


def test_реестр_сбп_альфа_банка():
    """Комиссия в файле отрицательная, «к зачислению» колонки нет — считаем сами."""
    r = acquiring.разобрать(РЕЕСТР_СБП.encode("cp1251"), "sbp_reestr.CSV")
    assert r["source"] == "СБП"
    assert [(x["date"], x["amount"], x["fee"], x["net"]) for x in r["rows"]] == [
        (date(2026, 10, 6), Decimal("2300.00"), Decimal("16.10"), Decimal("2283.90")),
    ]
    # «Сумма без комиссии» рядом с «Сумма комиссии» — колонку суммы не подменяет.
    assert r["columns"]["amount"] == "сумма транзакции"
    assert r["skipped"] == 0


@pytest.mark.asyncio
async def test_сбп_и_эквайринг_альфы_не_затирают_друг_друга(session):
    """Оба файла за 30.09–06.10 ложатся рядом: имена у них из одних цифр."""
    from app.services.acquiring import по_дням, сохранить

    await сохранить(session, АЛЬФА.encode("cp1251"), "94771706.csv")
    await сохранить(session, РЕЕСТР_СБП.encode("cp1251"), "94771708.csv")
    дни = await по_дням(session, date(2026, 9, 30), date(2026, 10, 6))
    assert дни[date(2026, 9, 30)]["by_source"] == {"Эквайринг": Decimal("6550.00")}
    assert дни[date(2026, 10, 6)]["by_source"] == {"СБП": Decimal("2300.00")}


# Настоящий отчёт по эквайрингу Альфа-Банка (Игорь прислал 11.10.2026).
# Имя файла «94771706.277.csv» — те же цифры, что и у реестра СБП, слова
# «СБП» в нём нет нигде, в том числе в строках операций.
ЭКВАЙРИНГ_АЛЬФА = (
    '"Наименование банка ""Альфа-Банк""";;;;;;;;;;;;;;;;\n'
    "Наименование предприятия ИП МОСКВИНОВ ИГОРЬ АНД;;;;;;;;;;;;;;;;\n"
    "За период 05.10.2026 по 05.10.2026;;;;;;;;;;;;;;;;\n"
    "Сумма транзакций;37790.00;;;;;;;;;;;;;;;\n"
    "Сумма комиссий с НДС;-461.04;;;;;;;;;;;;;;;\n"
    "Сумма НДС;-83.14;;;;;;;;;;;;;;;\n"
    "Сумма комиссий без НДС;-377.90;;;;;;;;;;;;;;;\n"
    "Сумма транзакций без комиссий;37328.96;;;;;;;;;;;;;;;\n"
    "Дата операции;Время операции;FE UTRNNO;RRN;Номер терминала;"
    "Наименование торговой точки;Номер карты;Признак карты своя/чужая;"
    "Платежная система;Сумма транзакции;Тип операции;Код авторизации;"
    "Сумма комиссии с НДС;Сумма без комиссии;Валюта;Сумма НДС;"
    "Комиссия без учета НДС\n"
    "04.10.2026;11:17:36;623470647925;627708145806;94771708;Барбершоп 44;"
    "220015******0150;0;MIR (NSPC);2300.00;Кредит;853179;-28.06;2271.94;810;"
    "-5.06;-23.00\n"
    "04.10.2026;19:30:11;623480601146;627711392439;94771708;Барбершоп 44;"
    "220040******2653;1;MIR (NSPC);4465.00;Кредит;260237;-54.47;4410.53;810;"
    "-9.82;-44.65\n"
)


def test_отчёт_эквайринга_альфы_не_путается_с_сбп():
    """«Сумма без комиссии» и «Сумма НДС» рядом — колонки не подменяются."""
    r = acquiring.разобрать(ЭКВАЙРИНГ_АЛЬФА.encode("cp1251"), "94771706.277.csv")
    assert r["source"] == "Эквайринг"
    assert r["columns"]["amount"] == "сумма транзакции"
    assert r["columns"]["fee"] == "сумма комиссии с ндс"
    assert [(x["date"], x["amount"], x["fee"], x["net"]) for x in r["rows"]] == [
        (date(2026, 10, 4), Decimal("2300.00"), Decimal("28.06"), Decimal("2271.94")),
        (date(2026, 10, 4), Decimal("4465.00"), Decimal("54.47"), Decimal("4410.53")),
    ]
    # Дата в строках — день операции (04.10), а не «период» из шапки (05.10):
    # сверяемся со сменой того дня, когда деньги приняли.
    assert {x["date"] for x in r["rows"]} == {date(2026, 10, 4)}


@pytest.mark.asyncio
async def test_два_настоящих_отчёта_альфы_ложатся_рядом(session):
    """Оба файла названы цифрами; различает их только содержимое."""
    from app.services.acquiring import по_дням, сохранить

    await сохранить(session, ЭКВАЙРИНГ_АЛЬФА.encode("cp1251"), "94771706.277.csv")
    await сохранить(session, РЕЕСТР_СБП.encode("cp1251"), "94771708.csv")
    дни = await по_дням(session, date(2026, 10, 4), date(2026, 10, 6))
    assert дни[date(2026, 10, 4)]["by_source"] == {"Эквайринг": Decimal("6765.00")}
    assert дни[date(2026, 10, 6)]["by_source"] == {"СБП": Decimal("2300.00")}
