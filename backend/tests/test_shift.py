"""Смена: что считается планом, фактом и следующей записью.

Сценарии из §40 ТЗ. Те из них, что опираются на историю визитов клиента за
всю жизнь (новый, второй визит, станут постоянными, стали потерянными),
проверяются на подставленном счётчике: сам источник такого счётчика в
YCLIENTS ещё не подтверждён, и в рабочем коде показатели пока отдаются как
«данные недоступны». Правило классификации от этого не зависит и должно
быть верным заранее.
"""

from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client
from app.services.shift import (
    MOSCOW,
    актуальная,
    выполненная,
    записался_дальше,
    клиентская,
    план_дня,
    проверки,
    разложить_записанных,
    разложить_пришедших,
    стали_потерянными,
    текст_закрытия,
    текст_открытия,
)
from app.services.shift_store import ОТКРЫТИЕ, проверить_время

ДЕНЬ = date(2026, 9, 23)
КСЕНИЯ = 5659614
АРТАШ = 5659611


def запись(
    *,
    ident: int = 1,
    client_id: int | None = 100,
    когда: datetime | None = None,
    посещение: int = 0,
    цена: int = 2000,
    удалена: bool = False,
    услуги: bool = True,
    staff_id: int = КСЕНИЯ,
) -> dict:
    когда = когда or datetime(ДЕНЬ.year, ДЕНЬ.month, ДЕНЬ.day, 12, 0, tzinfo=MOSCOW)
    return {
        "id": ident,
        "staff_id": staff_id,
        "datetime": когда.isoformat(),
        "visit_attendance": посещение,
        "deleted": удалена,
        "client": {"id": client_id} if client_id else None,
        "services": [{"cost_to_pay": цена}] if услуги else [],
    }


# --------------------------------------------------------------------------- #
# Что считать записью клиента
# --------------------------------------------------------------------------- #


def test_перерыв_без_клиента_не_запись():
    """Личное время и блокировки приезжают тем же адресом, что и записи."""
    assert клиентская(запись(client_id=None)) is False


def test_событие_без_услуг_не_запись():
    assert клиентская(запись(услуги=False)) is False


def test_удалённая_запись_не_считается():
    assert клиентская(запись(удалена=True)) is False


def test_не_пришедший_выпадает_из_актуальных():
    """Его деньги уже не придут — в плане им не место."""
    з = запись(посещение=-1)
    assert клиентская(з) is True
    assert актуальная(з) is False


def test_пришедший_это_выполненная():
    assert выполненная(запись(посещение=1)) is True
    assert выполненная(запись(посещение=2)) is False


# --------------------------------------------------------------------------- #
# План на день
# --------------------------------------------------------------------------- #


def test_план_складывает_услуги_актуальных_записей():
    записи = [
        запись(ident=1, client_id=100, цена=2000),
        запись(ident=2, client_id=200, цена=1500, посещение=2),
    ]
    assert план_дня(записи, ДЕНЬ) == 3500


def test_план_не_учитывает_отменённые_и_неявки():
    записи = [
        запись(ident=1, client_id=100, цена=2000),
        запись(ident=2, client_id=200, цена=5000, удалена=True),
        запись(ident=3, client_id=300, цена=7000, посещение=-1),
    ]
    assert план_дня(записи, ДЕНЬ) == 2000


def test_план_считает_все_услуги_одной_записи():
    з = запись()
    з["services"] = [{"cost_to_pay": 2000}, {"cost_to_pay": 800}]
    assert план_дня([з], ДЕНЬ) == 2800


def test_план_не_берёт_записи_другого_дня():
    завтра = datetime(2026, 9, 24, 12, 0, tzinfo=MOSCOW)
    assert план_дня([запись(когда=завтра)], ДЕНЬ) == 0


# --------------------------------------------------------------------------- #
# Классификация записанных (§8–§11 ТЗ)
# --------------------------------------------------------------------------- #


def test_клиент_без_прошлых_визитов_новый():
    итог = разложить_записанных([запись(client_id=100)], ДЕНЬ, {100: 0})
    assert итог == {"new": 1, "second": 0, "will_be_regular": 0}


def test_клиент_с_одним_визитом_это_второй_визит():
    итог = разложить_записанных([запись(client_id=100)], ДЕНЬ, {100: 1})
    assert итог == {"new": 0, "second": 1, "will_be_regular": 0}


def test_клиент_с_четырьмя_визитами_станет_постоянным():
    итог = разложить_записанных([запись(client_id=100)], ДЕНЬ, {100: 4})
    assert итог == {"new": 0, "second": 0, "will_be_regular": 1}


def test_клиент_с_пятью_визитами_уже_постоянный_и_никуда_не_входит():
    итог = разложить_записанных([запись(client_id=100)], ДЕНЬ, {100: 5})
    assert итог == {"new": 0, "second": 0, "will_be_regular": 0}


def test_две_записи_одного_клиента_это_один_человек():
    """Клиента нельзя превратить в двух новых из-за второй услуги (§27 ТЗ)."""
    записи = [запись(ident=1, client_id=100), запись(ident=2, client_id=100)]
    итог = разложить_записанных(записи, ДЕНЬ, {100: 0})
    assert итог["new"] == 1


def test_без_истории_показатели_не_нули_а_отсутствие_данных():
    """§33 ТЗ: подменять ошибку получения данных нулём запрещено."""
    итог = разложить_записанных([запись(client_id=100)], ДЕНЬ, None)
    assert итог == {"new": None, "second": None, "will_be_regular": None}


# --------------------------------------------------------------------------- #
# Следующая запись (§19, §20 ТЗ)
# --------------------------------------------------------------------------- #


def test_пришёл_и_записан_вперёд():
    сегодня = [запись(ident=1, client_id=100, посещение=1)]
    будущие = [
        запись(
            ident=2,
            client_id=100,
            когда=datetime(2026, 9, 30, 12, 0, tzinfo=MOSCOW),
            посещение=0,
        )
    ]
    записались, не_записались, пришли = записался_дальше(сегодня, будущие, ДЕНЬ)
    assert (записались, не_записались, пришли) == (1, 0, {100})


def test_пришёл_и_не_записан():
    сегодня = [запись(ident=1, client_id=100, посещение=1)]
    записались, не_записались, пришли = записался_дальше(сегодня, [], ДЕНЬ)
    assert (записались, не_записались, пришли) == (0, 1, {100})


def test_не_пришедший_в_показатель_не_входит():
    """Показатель только про тех, кто сегодня фактически был."""
    сегодня = [запись(ident=1, client_id=100, посещение=-1)]
    будущие = [
        запись(
            ident=2,
            client_id=100,
            когда=datetime(2026, 9, 30, 12, 0, tzinfo=MOSCOW),
        )
    ]
    записались, не_записались, пришли = записался_дальше(сегодня, будущие, ДЕНЬ)
    assert (записались, не_записались, пришли) == (0, 0, set())


def test_отменённая_будущая_запись_не_считается():
    сегодня = [запись(ident=1, client_id=100, посещение=1)]
    будущие = [
        запись(
            ident=2,
            client_id=100,
            когда=datetime(2026, 9, 30, 12, 0, tzinfo=MOSCOW),
            удалена=True,
        )
    ]
    записались, не_записались, _ = записался_дальше(сегодня, будущие, ДЕНЬ)
    assert (записались, не_записались) == (0, 1)


def test_сумма_записавшихся_и_нет_равна_числу_пришедших():
    """§20 ТЗ: равенство обязано выполняться, иначе расчёт неверен."""
    сегодня = [
        запись(ident=1, client_id=100, посещение=1),
        запись(ident=2, client_id=200, посещение=1),
        запись(ident=3, client_id=300, посещение=-1),
    ]
    будущие = [
        запись(
            ident=4,
            client_id=200,
            когда=datetime(2026, 10, 5, 12, 0, tzinfo=MOSCOW),
        )
    ]
    записались, не_записались, пришли = записался_дальше(сегодня, будущие, ДЕНЬ)
    assert записались + не_записались == len(пришли) == 2


# --------------------------------------------------------------------------- #
# Факт вечера
# --------------------------------------------------------------------------- #


def test_вечером_новым_считается_только_пришедший():
    assert разложить_пришедших({100}, {100: 0}) == {"new": 1, "became_regular": 0}


def test_вечером_постоянным_становится_тот_у_кого_был_пятый_визит():
    assert разложить_пришедших({100}, {100: 4}) == {"new": 0, "became_regular": 1}


def test_не_пришедший_вечером_никуда_не_попадает():
    """Утром он был в прогнозе, вечером его в факте нет."""
    assert разложить_пришедших(set(), {100: 4}) == {"new": 0, "became_regular": 0}


# --------------------------------------------------------------------------- #
# Стали потерянными сегодня (§24, §25 ТЗ)
# --------------------------------------------------------------------------- #


def _давно(дней: int) -> datetime:
    return datetime(ДЕНЬ.year, ДЕНЬ.month, ДЕНЬ.day, 12, 0, tzinfo=MOSCOW) - timedelta(days=дней)


def test_пересёк_рубеж_именно_сегодня():
    """Вчера было 59 дней, сегодня 60 — вот сегодня он и потерян."""
    окно = [запись(ident=1, client_id=100, посещение=1, когда=_давно(60))]
    assert стали_потерянными(окно, [], ДЕНЬ) == 1


def test_пересёк_рубеж_неделю_назад_сегодня_не_считается():
    """Иначе один и тот же человек попадал бы в отчёт каждый вечер."""
    окно = [запись(ident=1, client_id=100, посещение=1, когда=_давно(67))]
    assert стали_потерянными(окно, [], ДЕНЬ) == 0


def test_будущая_запись_снимает_статус_потерянного():
    окно = [запись(ident=1, client_id=100, посещение=1, когда=_давно(60))]
    будущие = [
        запись(
            ident=2,
            client_id=100,
            когда=datetime(2026, 10, 2, 12, 0, tzinfo=MOSCOW),
        )
    ]
    assert стали_потерянными(окно, будущие, ДЕНЬ) == 0


def test_приходил_после_рубежа_значит_не_потерян():
    окно = [
        запись(ident=1, client_id=100, посещение=1, когда=_давно(60)),
        запись(ident=2, client_id=100, посещение=1, когда=_давно(20)),
    ]
    assert стали_потерянными(окно, [], ДЕНЬ) == 0


def test_несостоявшийся_визит_на_рубеже_не_продлевает_жизнь():
    """Не пришёл — значит и не был: рубеж считается от выполненного визита."""
    окно = [
        запись(ident=1, client_id=100, посещение=1, когда=_давно(60)),
        запись(ident=2, client_id=100, посещение=-1, когда=_давно(30)),
    ]
    assert стали_потерянными(окно, [], ДЕНЬ) == 1


# --------------------------------------------------------------------------- #
# Проверки целостности (§34 ТЗ)
# --------------------------------------------------------------------------- #


def _закрытие(**поля) -> dict:
    итог = {
        "records_total": 10,
        "records_completed": 8,
        "services_revenue": 50000.0,
        "products_revenue": 3000.0,
        "clients_came": 8,
        "clients": {"booked_next": 5, "not_booked": 3},
        "completed": {"new": 2, "became_regular": 1},
    }
    итог.update(поля)
    return итог


def test_целый_расчёт_проверки_проходит():
    assert проверки(_закрытие()) == []


def test_выполнено_больше_чем_записано_это_ошибка():
    assert проверки(_закрытие(records_completed=12)) != []


def test_расхождение_записавшихся_это_ошибка():
    итог = _закрытие(clients={"booked_next": 5, "not_booked": 1})
    assert проверки(итог) != []


def test_отрицательная_выручка_это_ошибка():
    assert проверки(_закрытие(services_revenue=-1.0)) != []


# --------------------------------------------------------------------------- #
# Время прихода и ухода (§29 ТЗ)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("значение", ["00:00", "09:54", "23:59"])
def test_время_в_пределах_суток_принимается(значение):
    assert проверить_время(значение) == значение


@pytest.mark.parametrize("значение", ["24:00", "9:54", "09:60", "полдень", "", "0954"])
def test_негодное_время_отклоняется(значение):
    with pytest.raises(ValueError):
        проверить_время(значение)


# --------------------------------------------------------------------------- #
# Сообщения в Telegram
# --------------------------------------------------------------------------- #


def test_текст_открытия_содержит_план_и_время_прихода():
    снимок = {
        "shift_date": ДЕНЬ.isoformat(),
        "plan": 78500,
        "masters_working": 1,
        "masters": [{"staff_id": КСЕНИЯ, "name": "Ксения"}],
        "clients": {"new": 5, "second": 3, "will_be_regular": 2},
    }
    текст = текст_открытия(снимок, {КСЕНИЯ: "09:54"})
    assert "23 сентября" in текст
    assert "План на день: 78 500 ₽" in текст
    assert "Второй визит — 3" in текст
    assert "Ксения — 09:54" in текст


def test_недоступный_показатель_пишется_словами_а_не_нулём():
    снимок = {
        "shift_date": ДЕНЬ.isoformat(),
        "plan": 78500,
        "masters_working": 0,
        "masters": [],
        "clients": {"new": None, "second": None, "will_be_regular": None},
    }
    текст = текст_открытия(снимок, {})
    assert "Новые — данные недоступны" in текст
    assert "Новые — 0" not in текст


def test_текст_закрытия_разделяет_услуги_и_товары():
    снимок = {
        "shift_date": ДЕНЬ.isoformat(),
        "records_total": 31,
        "records_completed": 27,
        "services_revenue": 61800,
        "products_revenue": 7400,
        "clients": {"booked_next": 15, "not_booked": 12},
        "created_today_for_future": None,
        "completed": {"new": 4, "became_regular": 2},
        "lost_today": None,
        "masters": [{"staff_id": КСЕНИЯ, "name": "Ксения"}],
    }
    текст = текст_закрытия(снимок, {КСЕНИЯ: "20:03"})
    assert "Услуги — 61 800 ₽" in текст
    assert "Товары — 7 400 ₽" in текст
    assert "Ксения — уход 20:03" in текст


# --------------------------------------------------------------------------- #
# Хранение: одна смена на дату
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_повторное_открытие_не_создаёт_вторую_смену(session: AsyncSession, monkeypatch):
    from app.services import shift, shift_store

    снимок = {
        "shift_date": ДЕНЬ.isoformat(),
        "plan": 1000.0,
        "masters_working": 1,
        "masters": [{"staff_id": КСЕНИЯ, "name": "Ксения"}],
        "clients": {"new": None, "second": None, "will_be_regular": None},
        "warnings": [],
        "calculated_at": "2026-09-23T10:00:00+03:00",
    }
    вызовов = []

    async def собрать(день=None):
        вызовов.append(день)
        return снимок

    monkeypatch.setattr(shift, "собрать_открытие", собрать)

    первый = await shift_store.открыть(session, ДЕНЬ)
    второй = await shift_store.открыть(session, ДЕНЬ)

    assert len(вызовов) == 1, "второе нажатие не должно пересчитывать утро"
    assert первый["opening_snapshot"] == второй["opening_snapshot"]
    assert len(второй["employees"]) == 1

    from sqlalchemy import func, select

    from app.models.models import Shift

    сколько = await session.execute(select(func.count()).select_from(Shift))
    assert сколько.scalar_one() == 1, "на дату должна быть ровно одна смена"


@pytest.mark.asyncio
async def test_время_прихода_сохраняется_за_мастером(session: AsyncSession, monkeypatch):
    from app.services import shift, shift_store

    async def собрать(день=None):
        return {
            "shift_date": ДЕНЬ.isoformat(),
            "plan": 0.0,
            "masters_working": 1,
            "masters": [{"staff_id": КСЕНИЯ, "name": "Ксения"}],
            "clients": {"new": None, "second": None, "will_be_regular": None},
            "warnings": [],
            "calculated_at": "2026-09-23T10:00:00+03:00",
        }

    monkeypatch.setattr(shift, "собрать_открытие", собрать)
    await shift_store.открыть(session, ДЕНЬ)

    итог = await shift_store.записать_времена(session, ОТКРЫТИЕ, {КСЕНИЯ: "09:54"}, ДЕНЬ)
    assert итог["employees"][0]["arrival_time"] == "09:54"
    assert итог["employees"][0]["departure_time"] is None


@pytest.mark.asyncio
async def test_негодное_время_не_записывается(session: AsyncSession, monkeypatch):
    from app.services import shift, shift_store

    async def собрать(день=None):
        return {
            "shift_date": ДЕНЬ.isoformat(),
            "plan": 0.0,
            "masters_working": 1,
            "masters": [{"staff_id": КСЕНИЯ, "name": "Ксения"}],
            "clients": {"new": None, "second": None, "will_be_regular": None},
            "warnings": [],
            "calculated_at": "2026-09-23T10:00:00+03:00",
        }

    monkeypatch.setattr(shift, "собрать_открытие", собрать)
    await shift_store.открыть(session, ДЕНЬ)

    with pytest.raises(ValueError):
        await shift_store.записать_времена(session, ОТКРЫТИЕ, {КСЕНИЯ: "25:00"}, ДЕНЬ)


@pytest.mark.asyncio
async def test_смены_нет_значит_нечего_отправлять(session: AsyncSession):
    from app.services import shift_store

    with pytest.raises(ValueError):
        await shift_store.предпросмотр(session, ОТКРЫТИЕ, ДЕНЬ + timedelta(days=1))


# --------------------------------------------------------------------------- #
# Сборка целиком: от ответа YCLIENTS до готового снимка
# --------------------------------------------------------------------------- #


class ПодставнойYClients:
    """Отвечает как YCLIENTS, но из памяти: проверяем сборку, а не сеть."""

    company_id = 1

    def __init__(self, записи: list[dict], график: list[dict] | None = None):
        self.записи = записи
        self.график = график if график is not None else [{"staff_id": КСЕНИЯ, "slots": 1}]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def _get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        if "schedule" in path:
            return {"data": self.график}
        if "transactions" in path:
            return {"data": []}
        if params.get("page", 1) > 1:
            return {"data": []}
        начало = date.fromisoformat(params["start_date"])
        конец = date.fromisoformat(params["end_date"])
        кого = params.get("client_id")
        свои = [
            з
            for з in self.записи
            if начало <= datetime.fromisoformat(з["datetime"]).date() <= конец
            and (кого is None or (з.get("client") or {}).get("id") == кого)
        ]
        return {"data": свои, "meta": {"total_count": len(свои)}}


def не_про_историю(предупреждения: list[str]) -> bool:
    return not any("История визитов" in w for w in предупреждения)


@pytest.mark.asyncio
async def test_открытие_собирается_из_ответа_yclients(monkeypatch):
    from app.services import shift

    записи = [
        запись(ident=1, client_id=100, цена=2000),
        запись(ident=2, client_id=200, цена=1500, посещение=2),
        запись(ident=3, client_id=300, цена=9000, удалена=True),
    ]
    monkeypatch.setattr(shift, "YClientsClient", lambda: ПодставнойYClients(записи))

    снимок = await shift.собрать_открытие(ДЕНЬ)

    assert снимок["plan"] == 3500
    assert снимок["masters_working"] == 1
    assert снимок["masters"][0]["staff_id"] == КСЕНИЯ
    # У обоих записанных прошлых визитов в истории нет — оба новые.
    assert снимок["clients"] == {"new": 2, "second": 0, "will_be_regular": 0}
    assert не_про_историю(снимок["warnings"])


@pytest.mark.asyncio
async def test_закрытие_считает_факт_и_следующую_запись(monkeypatch):
    from app.services import shift

    записи = [
        запись(ident=1, client_id=100, посещение=1, цена=2000),
        запись(ident=2, client_id=200, посещение=1, цена=1500),
        запись(ident=3, client_id=300, посещение=-1, цена=3000),
        запись(
            ident=4,
            client_id=100,
            когда=datetime(2026, 10, 1, 12, 0, tzinfo=MOSCOW),
            цена=2000,
        ),
    ]
    monkeypatch.setattr(shift, "YClientsClient", lambda: ПодставнойYClients(записи))

    снимок = await shift.собрать_закрытие(ДЕНЬ)

    assert снимок["records_total"] == 3
    assert снимок["records_completed"] == 2
    assert снимок["services_revenue"] == 3500
    assert снимок["products_revenue"] == 0
    assert снимок["clients"] == {"booked_next": 1, "not_booked": 1}
    assert снимок["completed"] == {"new": 2, "became_regular": 0}
    assert снимок["lost_today"] == 0
    assert снимок["integrity_failures"] == []


@pytest.mark.asyncio
async def test_история_клиента_берётся_поимённо(monkeypatch):
    """Прошлые визиты считаются по его собственной истории, а не по окну базы."""
    from app.services import shift

    прошлые = [
        запись(
            ident=10 + i,
            client_id=100,
            посещение=1,
            когда=datetime(2026, 3 + i, 10, 12, 0, tzinfo=MOSCOW),
        )
        for i in range(4)
    ]
    записи = [*прошлые, запись(ident=1, client_id=100)]
    monkeypatch.setattr(shift, "YClientsClient", lambda: ПодставнойYClients(записи))

    снимок = await shift.собрать_открытие(ДЕНЬ)

    # Четыре визита до сегодняшнего — сегодня может стать пятым.
    assert снимок["clients"] == {"new": 0, "second": 0, "will_be_regular": 1}


@pytest.mark.asyncio
async def test_проигнорированный_фильтр_client_id_не_даёт_чужих_визитов(monkeypatch):
    """Если YCLIENTS перестанет отбирать по client_id, счёт станет ложным.

    Молча принять чужие визиты нельзя: клиент с первым визитом получил бы
    пятый и уехал бы в «постоянные». Лучше честное «данные недоступны».
    """
    from app.services import shift

    class БезФильтра(ПодставнойYClients):
        async def _get(self, path, params=None):
            params = dict(params or {})
            params.pop("client_id", None)
            return await super()._get(path, params)

    записи = [
        запись(ident=1, client_id=100),
        запись(ident=2, client_id=999, посещение=1, когда=_давно(30)),
    ]
    monkeypatch.setattr(shift, "YClientsClient", lambda: БезФильтра(записи))

    снимок = await shift.собрать_открытие(ДЕНЬ)

    assert снимок["clients"] == {"new": None, "second": None, "will_be_regular": None}


@pytest.mark.asyncio
async def test_упавший_запрос_истории_даёт_нет_данных_а_не_нули(monkeypatch):
    """§33 ТЗ: недосчитанная история хуже её отсутствия — цифры выйдут ложными."""
    from app.services import shift

    class Падающий(ПодставнойYClients):
        async def _get(self, path, params=None):
            if (params or {}).get("client_id"):
                raise RuntimeError("YCLIENTS не ответил")
            return await super()._get(path, params)

    monkeypatch.setattr(
        shift, "YClientsClient", lambda: Падающий([запись(ident=1, client_id=100)])
    )

    снимок = await shift.собрать_открытие(ДЕНЬ)

    assert снимок["clients"] == {"new": None, "second": None, "will_be_regular": None}
    assert any("История визитов" in w for w in снимок["warnings"])


# --------------------------------------------------------------------------- #
# Деньги: расшифровка выручки по услугам и товарам
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_детали_услуг_по_одной_строке_на_визит(monkeypatch):
    from app.services import shift

    записи = [
        запись(ident=1, client_id=100, посещение=1, цена=1500),
        запись(ident=2, client_id=200, посещение=1, цена=2000, staff_id=АРТАШ),
        запись(ident=3, client_id=300, посещение=0, цена=9000),  # ожидание — не выполнена
    ]
    записи[0]["services"] = [{"title": "Стрижка", "cost_to_pay": 1500}]
    записи[1]["services"] = [{"title": "Борода", "cost_to_pay": 2000}]
    monkeypatch.setattr(shift, "YClientsClient", lambda: ПодставнойYClients(записи))

    строки = await shift.собрать_детали_услуг(ДЕНЬ)

    assert len(строки) == 2
    assert {с["client_id"] for с in строки} == {100, 200}
    ксенина = next(с for с in строки if с["client_id"] == 100)
    assert ксенина["title"] == "Стрижка"
    assert ксенина["amount"] == 1500
    assert ксенина["master"] == "Ксения"


@pytest.mark.asyncio
async def test_детали_товаров_подставляет_запасное_название(monkeypatch):
    from app.services import shift

    class СТоварами(ПодставнойYClients):
        async def _get(self, path, params=None):
            params = params or {}
            if "transactions" in path and "storage_operations" not in path:
                if params.get("page", 1) > 1:
                    return {"data": []}
                return {"data": [{
                    "sold_item_type": "goods_transaction", "sold_item_id": 55,
                    "deleted": False, "amount": 800, "date": ДЕНЬ.isoformat(),
                }]}
            if "storage_operations" in path:
                return {"data": {
                    "deleted": False, "type_id": 1, "master_id": КСЕНИЯ,
                    "create_date": ДЕНЬ.isoformat(),
                }}
            return await super()._get(path, params)

    monkeypatch.setattr(shift, "YClientsClient", lambda: СТоварами([]))

    строки = await shift.собрать_детали_товаров(ДЕНЬ)

    assert len(строки) == 1
    assert строки[0]["title"] == "Товар №55"
    assert строки[0]["amount"] == 800
    assert строки[0]["master"] == "Ксения"


@pytest.mark.asyncio
async def test_закрытие_считает_заработано_всего_только_когда_известны_оба(monkeypatch):
    from app.services import shift

    записи = [запись(ident=1, client_id=100, посещение=1, цена=1000)]
    monkeypatch.setattr(shift, "YClientsClient", lambda: ПодставнойYClients(записи))

    снимок = await shift.собрать_закрытие(ДЕНЬ)

    assert снимок["money"]["total_earned"] == 1000  # товаров не было — продажи пустые, 0
    # Транзакций за день нет вовсе — YCLIENTS ответил пустым списком, это
    # настоящий ноль, а не «данные недоступны» (§33 ТЗ).
    assert снимок["money"]["non_cash"] == 0
    assert снимок["money"]["cash"] == 0
    assert снимок["money"]["spent"] == 0


class _СТранзакциямиДенег(ПодставнойYClients):
    """Фейк с настоящими транзакциями — для проверки разбивки нал/безнал/расход."""

    def __init__(self, записи, транзакции):
        super().__init__(записи)
        self._транзакции = транзакции

    async def _get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        if "transactions" in path and "storage_operations" not in path:
            if params.get("page", 1) > 1:
                return {"data": []}
            return {"data": self._транзакции}
        return await super()._get(path, params)


@pytest.mark.asyncio
async def test_деньги_за_день_делит_по_account_is_cash():
    from app.services import shift

    транзакции = [
        {"sold_item_type": "service", "amount": 1900, "account": {"is_cash": False}},
        {"sold_item_type": "service", "amount": 500, "account": {"is_cash": True}},
        {"sold_item_type": "goods_transaction", "amount": 300, "account": {"is_cash": True}},
    ]
    итог = await shift._деньги_за_день(_СТранзакциямиДенег([], транзакции), ДЕНЬ)

    assert итог == {"non_cash": 1900.0, "cash": 800.0, "spent": 0.0}


@pytest.mark.asyncio
async def test_деньги_за_день_считает_расход_по_отрицательной_сумме():
    from app.services import shift

    транзакции = [
        {"sold_item_type": None, "amount": -40000, "account": {"is_cash": False},
         "expense": {"title": "Зарплата персонала"}},
        # Продажа с sold_item_type=None не встречается в жизни, но если бы
        # сумма была положительной — это не трата, и в «Потрачено» не идёт.
        {"sold_item_type": None, "amount": 100, "account": {"is_cash": True}},
    ]
    итог = await shift._деньги_за_день(_СТранзакциямиДенег([], транзакции), ДЕНЬ)

    assert итог["spent"] == 40000.0


@pytest.mark.asyncio
async def test_деньги_за_день_пропускает_удалённые_транзакции():
    from app.services import shift

    транзакции = [
        {"sold_item_type": "service", "amount": 5000, "account": {"is_cash": False},
         "deleted": True},
    ]
    итог = await shift._деньги_за_день(_СТранзакциямиДенег([], транзакции), ДЕНЬ)

    assert итог == {"non_cash": 0.0, "cash": 0.0, "spent": 0.0}


@pytest.mark.asyncio
async def test_закрытие_предупреждает_если_нал_безнал_не_сходится_с_заработано(monkeypatch):
    from app.services import shift

    # Записано на 1000 ₽ услуг, а транзакция в тот же день — только на 100 ₽:
    # похоже, что оплата прошла другим днём или сумму поправили после визита.
    записи = [запись(ident=1, client_id=100, посещение=1, цена=1000)]
    транзакции = [{"sold_item_type": "service", "amount": 100, "account": {"is_cash": True}}]
    monkeypatch.setattr(
        shift, "YClientsClient", lambda: _СТранзакциямиДенег(записи, транзакции)
    )

    снимок = await shift.собрать_закрытие(ДЕНЬ)

    assert снимок["money"]["total_earned"] == 1000
    assert снимок["money"]["cash"] == 100
    assert any("не совпадает" in w for w in снимок["warnings"])


@pytest.mark.asyncio
async def test_деньги_детали_услуг_подставляет_имя_из_локальной_базы(session, monkeypatch):
    from app.services import shift, shift_store

    session.add(Client(id=100, yclients_id=100, name="Иван Тестовый", phone="+79990000100"))
    await session.commit()

    async def собрать_детали_услуг(день=None):
        return [{"client_id": 100, "master": "Ксения", "title": "Стрижка", "amount": 1500.0,
                 "time": "10:00"}]

    monkeypatch.setattr(shift, "собрать_детали_услуг", собрать_детали_услуг)

    строки = await shift_store.деньги_детали(session, shift_store.УСЛУГИ, ДЕНЬ)
    assert строки == [{"time": "10:00", "client": "Иван Тестовый", "master": "Ксения",
                        "title": "Стрижка", "amount": 1500.0}]


@pytest.mark.asyncio
async def test_деньги_детали_неизвестный_раздел_ошибка(session):
    from app.services import shift_store

    with pytest.raises(ValueError):
        await shift_store.деньги_детали(session, "чушь", ДЕНЬ)


# --------------------------------------------------------------------------- #
# Остатки денег подставляются в закрытие смены
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_закрытие_подставляет_внесённые_остатки(session: AsyncSession, monkeypatch):
    from decimal import Decimal

    from app.services import cash_balances, shift, shift_store

    async def собрать_закрытие(день=None):
        return {
            "shift_date": ДЕНЬ.isoformat(), "records_total": 0, "records_completed": 0,
            "services_revenue": 0.0, "products_revenue": 0.0,
            "money": {"total_earned": 0.0, "non_cash": None, "cash": None, "spent": None,
                      "cash_register_estimate": None, "settlement_account_estimate": None,
                      "other_account_debt": None},
            "clients_came": 0, "clients": {"booked_next": 0, "not_booked": 0},
            "created_today_for_future": None, "completed": {"new": None, "became_regular": None},
            "lost_today": None, "masters": [], "warnings": [], "calculated_at": "x",
        }

    monkeypatch.setattr(shift, "собрать_закрытие", собрать_закрытие)
    await cash_balances.сохранить(
        session, cash_amount=Decimal("7446"), cash_as_of=ДЕНЬ,
        settlement_amount=Decimal("0"), settlement_as_of=ДЕНЬ,
        other_account_debt=Decimal("40000"), other_debt_note="заняли на расходы",
    )

    итог = await shift_store.закрыть(session, ДЕНЬ)

    деньги = итог["closing_snapshot"]["money"]
    assert деньги["cash_register_estimate"] == 7446.0
    assert деньги["settlement_account_estimate"] == 0.0
    assert деньги["other_account_debt"] == 40000.0
    assert not any("не пересчитан" in w for w in итог["closing_snapshot"]["warnings"])


@pytest.mark.asyncio
async def test_закрытие_без_остатков_предупреждает_а_не_молчит(session: AsyncSession, monkeypatch):
    from app.services import shift, shift_store

    async def собрать_закрытие(день=None):
        return {
            "shift_date": ДЕНЬ.isoformat(), "records_total": 0, "records_completed": 0,
            "services_revenue": 0.0, "products_revenue": 0.0,
            "money": {"total_earned": 0.0, "non_cash": None, "cash": None, "spent": None,
                      "cash_register_estimate": None, "settlement_account_estimate": None,
                      "other_account_debt": None},
            "clients_came": 0, "clients": {"booked_next": 0, "not_booked": 0},
            "created_today_for_future": None, "completed": {"new": None, "became_regular": None},
            "lost_today": None, "masters": [], "warnings": [], "calculated_at": "x",
        }

    monkeypatch.setattr(shift, "собрать_закрытие", собрать_закрытие)

    итог = await shift_store.закрыть(session, ДЕНЬ)

    деньги = итог["closing_snapshot"]["money"]
    assert деньги["cash_register_estimate"] is None
    assert any("не внесены" in w for w in итог["closing_snapshot"]["warnings"])


# --------------------------------------------------------------------------- #
# Старый снимок без блока «Деньги» не должен ронять страницу
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_старый_отправленный_снимок_без_денег_открывается(session: AsyncSession):
    """До появления блока «Деньги» закрытие хранилось без него. Отправленное
    в Telegram закрытие не пересчитывается больше никогда (§32 ТЗ) — значит,
    такой снимок остаётся в базе навсегда и должен открываться, а не падать."""
    from app.models.models import Shift
    from app.services import shift_store

    старый_снимок = {
        "shift_date": ДЕНЬ.isoformat(), "records_total": 10, "records_completed": 8,
        "services_revenue": 5000.0, "products_revenue": 500.0,
        "clients": {"booked_next": 3, "not_booked": 5},
        "created_today_for_future": None, "completed": {"new": None, "became_regular": None},
        "lost_today": None, "masters": [], "warnings": [], "integrity_failures": [],
        # намеренно без ключа "money" — так выглядели снимки до его появления
    }
    session.add(Shift(shift_date=ДЕНЬ, closing_snapshot=старый_снимок))
    await session.commit()

    итог = await shift_store.текущая(session, ДЕНЬ)

    деньги = итог["closing_snapshot"]["money"]
    assert деньги == {
        "total_earned": None, "non_cash": None, "cash": None, "spent": None,
        "cash_register_estimate": None, "settlement_account_estimate": None,
        "other_account_debt": None,
    }
    # Остальное содержимое старого снимка не тронуто.
    assert итог["closing_snapshot"]["services_revenue"] == 5000.0


@pytest.mark.asyncio
async def test_снимок_с_деньгами_без_долга_дополняется(session: AsyncSession):
    """Снимок между появлением «Деньги» и появлением «Долг по другому счёту»
    (§ 26.09.2026, вторая часть) — тоже должен открыться с долгом = None."""
    from app.models.models import Shift
    from app.services import shift_store

    снимок_без_долга = {
        "shift_date": ДЕНЬ.isoformat(), "records_total": 1, "records_completed": 1,
        "services_revenue": 100.0, "products_revenue": 0.0,
        "money": {"total_earned": 100.0, "non_cash": None, "cash": None, "spent": None,
                  "cash_register_estimate": 500.0, "settlement_account_estimate": 0.0},
        "clients": {"booked_next": 0, "not_booked": 1},
        "created_today_for_future": None, "completed": {"new": None, "became_regular": None},
        "lost_today": None, "masters": [], "warnings": [], "integrity_failures": [],
    }
    session.add(Shift(shift_date=ДЕНЬ, closing_snapshot=снимок_без_долга))
    await session.commit()

    итог = await shift_store.текущая(session, ДЕНЬ)

    деньги = итог["closing_snapshot"]["money"]
    assert деньги["cash_register_estimate"] == 500.0
    assert деньги["other_account_debt"] is None
