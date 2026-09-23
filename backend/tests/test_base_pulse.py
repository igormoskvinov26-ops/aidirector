"""Пульс базы: четыре сегмента в разрезе мастеров.

Решение владельца 23.09.2026: лояльный — от двух до четырёх визитов к одному
мастеру, постоянный — пять и больше, сегменты непересекающиеся. Клиент приписан к
мастеру, у которого был чаще (при равенстве — к тому, у кого был последним).
Если ни у одного барбера нет даже двух визитов, а в салоне их два и больше —
клиент «без своего мастера», отдельный столбец.

Главное свойство, которое здесь проверяется: каждый клиент попадает ровно в
одну ячейку. Иначе сумма столбцов разойдётся с размером базы и по
гистограмме нельзя будет судить, растёт база или нет.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import Client, Employee, Visit
from app.services.client_base import (
    NO_MASTER,
    build_base_pulse,
    classify_client,
    get_pulse_clients,
    moscow_today,
)

КСЕНИЯ = 5659614  # settings.barber_payroll_rules в тестовом .env
АРТАШ = 5659611
ДМИТРИЙ = 5659617
БАРБЕРЫ = {КСЕНИЯ, АРТАШ, ДМИТРИЙ}
АДМИНИСТРАТОР = 777001


def _дни(*сколько_назад: int) -> list:
    сегодня = moscow_today()
    return [сегодня - timedelta(days=d) for d in сколько_назад]


# --------------------------------------------------------------------------- #
# classify_client — чистая функция, без базы
# --------------------------------------------------------------------------- #


def test_один_визит_недавно_это_новый():
    итог = classify_client({КСЕНИЯ: _дни(10)}, БАРБЕРЫ, False, moscow_today())
    assert итог == ("new", КСЕНИЯ)


def test_два_визита_к_одному_мастеру_это_лояльный():
    итог = classify_client({КСЕНИЯ: _дни(40, 10)}, БАРБЕРЫ, False, moscow_today())
    assert итог == ("loyal", КСЕНИЯ)


def test_три_визита_ещё_лояльный():
    итог = classify_client({КСЕНИЯ: _дни(50, 30, 10)}, БАРБЕРЫ, False, moscow_today())
    assert итог == ("loyal", КСЕНИЯ)


def test_четыре_визита_ещё_лояльный():
    итог = classify_client({КСЕНИЯ: _дни(50, 40, 30, 10)}, БАРБЕРЫ, False, moscow_today())
    assert итог == ("loyal", КСЕНИЯ)


def test_пять_визитов_это_постоянный():
    """Порог постоянного — пять визитов, решение владельца 23.09.2026."""
    итог = classify_client({КСЕНИЯ: _дни(60, 50, 40, 30, 10)}, БАРБЕРЫ, False, moscow_today())
    assert итог == ("regular", КСЕНИЯ)


def test_постоянный_не_считается_заодно_лояльным():
    """Сегменты непересекающиеся — решение владельца 23.09.2026."""
    сегмент, _ = classify_client(
        {КСЕНИЯ: _дни(60, 50, 40, 30, 10)}, БАРБЕРЫ, False, moscow_today()
    )
    assert сегмент != "loyal"


def test_нет_визитов_больше_60_дней_это_потерянный():
    итог = classify_client({КСЕНИЯ: _дни(90)}, БАРБЕРЫ, False, moscow_today())
    assert итог == ("lost", КСЕНИЯ)


def test_будущая_запись_снимает_статус_потерянного():
    итог = classify_client({КСЕНИЯ: _дни(90)}, БАРБЕРЫ, True, moscow_today())
    assert итог == ("new", КСЕНИЯ)


def test_потеряли_постоянного_столбец_остаётся_за_мастером():
    """Ксения потеряла постоянного клиента — это её столбец,
    а не «ничей»: вопрос к тому, кто его вёл."""
    итог = classify_client(
        {КСЕНИЯ: _дни(210, 200, 190, 180, 170)}, БАРБЕРЫ, False, moscow_today()
    )
    assert итог == ("lost", КСЕНИЯ)


def test_ходит_к_разным_мастерам_попадает_в_столбец_без_своего_мастера():
    визиты = {КСЕНИЯ: _дни(40), АРТАШ: _дни(20), ДМИТРИЙ: _дни(5)}
    итог = classify_client(визиты, БАРБЕРЫ, False, moscow_today())
    assert итог == ("loyal", NO_MASTER)


def test_много_визитов_но_все_к_разным_мастерам_это_постоянный_без_мастера():
    """Пять визитов в салон, ни к кому двух — постоянный клиент салона,
    но ничей. Ровно тот случай, ради которого заведён четвёртый столбец."""
    визиты = {
        КСЕНИЯ: _дни(50), АРТАШ: _дни(40), ДМИТРИЙ: _дни(30), АДМИНИСТРАТОР: _дни(20, 10),
    }
    итог = classify_client(визиты, БАРБЕРЫ, False, moscow_today())
    assert итог == ("regular", NO_MASTER)


def test_свой_мастер_это_тот_у_кого_чаще():
    визиты = {КСЕНИЯ: _дни(70, 60, 50, 40, 30), АРТАШ: _дни(10)}
    итог = classify_client(визиты, БАРБЕРЫ, False, moscow_today())
    assert итог == ("regular", КСЕНИЯ)


def test_при_равенстве_визитов_свой_мастер_тот_у_кого_был_последним():
    визиты = {КСЕНИЯ: _дни(50, 40), АРТАШ: _дни(30, 10)}
    _, столбец = classify_client(визиты, БАРБЕРЫ, False, moscow_today())
    assert столбец == АРТАШ


def test_обслуживал_не_барбер_значит_без_своего_мастера():
    итог = classify_client({АДМИНИСТРАТОР: _дни(30, 10)}, БАРБЕРЫ, False, moscow_today())
    assert итог == ("loyal", NO_MASTER)


def test_без_визитов_клиент_не_в_базе():
    assert classify_client({}, БАРБЕРЫ, False, moscow_today()) is None


# --------------------------------------------------------------------------- #
# build_base_pulse и get_pulse_clients — с базой
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


async def _seed(session: AsyncSession) -> None:
    команда = ((1, КСЕНИЯ, "Ксения"), (2, АРТАШ, "Арташ"), (3, ДМИТРИЙ, "Дмитрий"))
    for local_id, yid, name in команда:
        session.add(Employee(id=local_id, yclients_id=yid, name=name))
    await session.flush()


async def _клиент(session: AsyncSession, cid: int, имя: str) -> None:
    session.add(Client(id=cid, yclients_id=cid, name=имя, phone=f"+7999000{cid:04d}"))


_счётчик_визитов = [0]


async def _визит(
    session: AsyncSession, cid: int, employee_id: int, days_ago: int, status: str = "completed",
) -> None:
    _счётчик_визитов[0] += 1
    vid = _счётчик_визитов[0]
    session.add(Visit(
        id=vid, yclients_id=vid, client_id=cid, employee_id=employee_id,
        datetime=datetime.now(UTC) - timedelta(days=days_ago),
        status=status, total_amount=Decimal("1000"),
    ))


def _ячейка(итог: dict, сегмент: str, staff_id: int) -> int:
    блок = next(s for s in итог["segments"] if s["code"] == сегмент)
    return next(c["count"] for c in блок["columns"] if c["staff_id"] == staff_id)


@pytest.mark.asyncio
async def test_сумма_всех_столбцов_равна_размеру_базы(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "Новый")
    await _визит(session, 1, 1, days_ago=5)
    await _клиент(session, 2, "Лояльный")
    await _визит(session, 2, 1, days_ago=40)
    await _визит(session, 2, 1, days_ago=10)
    await _клиент(session, 3, "Потерянный")
    await _визит(session, 3, 2, days_ago=120)
    await _клиент(session, 4, "Ничей")
    await _визит(session, 4, 1, days_ago=30)
    await _визит(session, 4, 2, days_ago=10)
    await session.commit()

    итог = await build_base_pulse(session)
    по_столбцам = sum(c["count"] for s in итог["segments"] for c in s["columns"])
    assert по_столбцам == итог["base_total"] == 4


@pytest.mark.asyncio
async def test_клиенты_раскладываются_по_нужным_ячейкам(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "Новый у Ксении")
    await _визит(session, 1, 1, days_ago=5)
    await _клиент(session, 2, "Постоянный Арташа")
    for d in (90, 70, 50, 30, 10):
        await _визит(session, 2, 2, days_ago=d)
    await _клиент(session, 3, "Ничей")
    await _визит(session, 3, 1, days_ago=30)
    await _визит(session, 3, 3, days_ago=10)
    await session.commit()

    итог = await build_base_pulse(session)
    assert _ячейка(итог, "new", КСЕНИЯ) == 1
    assert _ячейка(итог, "regular", АРТАШ) == 1
    assert _ячейка(итог, "loyal", NO_MASTER) == 1
    assert _ячейка(итог, "lost", КСЕНИЯ) == 0


@pytest.mark.asyncio
async def test_клик_по_столбцу_отдаёт_этих_клиентов_с_именем_и_телефоном(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "Иван Потерянный")
    await _визит(session, 1, 1, days_ago=100)
    await _клиент(session, 2, "Пётр Активный")
    await _визит(session, 2, 1, days_ago=10)
    await session.commit()

    список = await get_pulse_clients(session, "lost", КСЕНИЯ)
    assert len(список) == 1
    assert список[0]["name"] == "Иван Потерянный"
    assert список[0]["phone"] == "+79990000001"
    assert список[0]["visits_total"] == 1
    assert список[0]["lost_since"] is not None


@pytest.mark.asyncio
async def test_потерянные_отсортированы_ценными_вперёд(session: AsyncSession):
    """Вернуть постоянного важнее, чем того, кто был однажды."""
    await _seed(session)
    await _клиент(session, 1, "Разовый")
    await _визит(session, 1, 1, days_ago=100)
    await _клиент(session, 2, "Был постоянным")
    for d in (210, 200, 190, 180, 170):
        await _визит(session, 2, 1, days_ago=d)
    await session.commit()

    список = await get_pulse_clients(session, "lost", КСЕНИЯ)
    assert [c["name"] for c in список] == ["Был постоянным", "Разовый"]


@pytest.mark.asyncio
async def test_список_ничейных_клиентов_доступен_по_нулевому_столбцу(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "Ходит к разным")
    await _визит(session, 1, 1, days_ago=30)
    await _визит(session, 1, 2, days_ago=10)
    await session.commit()

    список = await get_pulse_clients(session, "loyal", NO_MASTER)
    assert [c["name"] for c in список] == ["Ходит к разным"]
    assert список[0]["master"] is None
