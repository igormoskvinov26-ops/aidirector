"""Пульс базы: пять сегментов, столбец — последний мастер клиента.

Решение владельца 25.09.2026: прежняя приписка «к своему мастеру по частоте
визитов» с отдельным разбором разрозненных визитов была источником путаницы
и двойного счёта. Теперь сегмент считается по общему числу визитов клиента
во всём салоне (1 → новый, 2 → второй визит, 3–9 → лояльный, 10+ → VIP,
60+ дней без визита и без записи вперёд → потерянный — независимо от числа),
а столбец гистограммы — просто тот, кто вёл последний завершённый визит.

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
    в_зоне_риска,
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
    итог = classify_client(_дни(10), КСЕНИЯ, БАРБЕРЫ, False, moscow_today())
    assert итог == ("new", КСЕНИЯ)


def test_два_визита_это_второй_визит():
    итог = classify_client(_дни(40, 10), КСЕНИЯ, БАРБЕРЫ, False, moscow_today())
    assert итог == ("second", КСЕНИЯ)


def test_три_визита_это_лояльный():
    итог = classify_client(_дни(50, 30, 10), КСЕНИЯ, БАРБЕРЫ, False, moscow_today())
    assert итог == ("loyal", КСЕНИЯ)


def test_девять_визитов_ещё_лояльный():
    итог = classify_client(_дни(*range(90, 0, -10)), КСЕНИЯ, БАРБЕРЫ, False, moscow_today())
    assert итог == ("loyal", КСЕНИЯ)


def test_десять_визитов_это_vip():
    """Порог VIP — десять визитов, решение владельца 25.09.2026."""
    итог = classify_client(_дни(*range(100, 0, -10)), КСЕНИЯ, БАРБЕРЫ, False, moscow_today())
    assert итог == ("vip", КСЕНИЯ)


def test_vip_не_считается_заодно_лояльным():
    """Сегменты непересекающиеся — решение владельца 25.09.2026."""
    сегмент, _ = classify_client(
        _дни(*range(100, 0, -10)), КСЕНИЯ, БАРБЕРЫ, False, moscow_today()
    )
    assert сегмент != "loyal"


def test_нет_визитов_больше_60_дней_это_потерянный():
    итог = classify_client(_дни(90), КСЕНИЯ, БАРБЕРЫ, False, moscow_today())
    assert итог == ("lost", КСЕНИЯ)


def test_будущая_запись_снимает_статус_потерянного():
    итог = classify_client(_дни(90), КСЕНИЯ, БАРБЕРЫ, True, moscow_today())
    assert итог == ("new", КСЕНИЯ)


def test_потеряли_vip_столбец_остаётся_за_последним_мастером():
    """VIP потерян — столбец остаётся за тем, кто вёл последний визит,
    а не становится «ничьим»: вопрос к тому, кто его вёл."""
    итог = classify_client(
        _дни(*range(260, 160, -10)), КСЕНИЯ, БАРБЕРЫ, False, moscow_today()
    )
    assert итог == ("lost", КСЕНИЯ)


def test_последний_визит_определяет_столбец_даже_если_прежде_ходил_к_другому():
    """Столбец — не приписка «по частоте», а просто последний визит."""
    итог = classify_client(_дни(40, 10), АРТАШ, БАРБЕРЫ, False, moscow_today())
    assert итог == ("second", АРТАШ)


def test_обслуживал_не_барбер_значит_без_своего_мастера():
    итог = classify_client(_дни(30, 10), АДМИНИСТРАТОР, БАРБЕРЫ, False, moscow_today())
    assert итог == ("second", NO_MASTER)


def test_мастер_не_найден_в_штате_тоже_без_своего_мастера():
    итог = classify_client(_дни(10), None, БАРБЕРЫ, False, moscow_today())
    assert итог == ("new", NO_MASTER)


def test_без_визитов_клиент_не_в_базе():
    assert classify_client([], КСЕНИЯ, БАРБЕРЫ, False, moscow_today()) is None


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
    команда = (
        (1, КСЕНИЯ, "Ксения"), (2, АРТАШ, "Арташ"), (3, ДМИТРИЙ, "Дмитрий"),
        (4, АДМИНИСТРАТОР, "Виктор"),
    )
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
    await _визит(session, 2, 1, days_ago=30)
    await _визит(session, 2, 1, days_ago=10)
    await _клиент(session, 3, "Потерянный")
    await _визит(session, 3, 2, days_ago=120)
    await _клиент(session, 4, "Без своего мастера")
    await _визит(session, 4, 4, days_ago=10)
    await session.commit()

    итог = await build_base_pulse(session)
    по_столбцам = sum(c["count"] for s in итог["segments"] for c in s["columns"])
    assert по_столбцам == итог["base_total"] == 4


@pytest.mark.asyncio
async def test_клиенты_раскладываются_по_нужным_ячейкам(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "Новый у Ксении")
    await _визит(session, 1, 1, days_ago=5)
    await _клиент(session, 2, "VIP Арташа")
    for d in (100, 90, 80, 70, 60, 50, 40, 30, 20, 10):
        await _визит(session, 2, 2, days_ago=d)
    await _клиент(session, 3, "Без своего мастера")
    await _визит(session, 3, 4, days_ago=10)
    await session.commit()

    итог = await build_base_pulse(session)
    assert _ячейка(итог, "new", КСЕНИЯ) == 1
    assert _ячейка(итог, "vip", АРТАШ) == 1
    assert _ячейка(итог, "new", NO_MASTER) == 1
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
    """Вернуть VIP важнее, чем того, кто был однажды."""
    await _seed(session)
    await _клиент(session, 1, "Разовый")
    await _визит(session, 1, 1, days_ago=100)
    await _клиент(session, 2, "Был VIP")
    for d in (260, 250, 240, 230, 220, 210, 200, 190, 180, 170):
        await _визит(session, 2, 1, days_ago=d)
    await session.commit()

    список = await get_pulse_clients(session, "lost", КСЕНИЯ)
    assert [c["name"] for c in список] == ["Был VIP", "Разовый"]


@pytest.mark.asyncio
async def test_список_ничейных_клиентов_доступен_по_нулевому_столбцу(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "Обслуживал администратор")
    await _визит(session, 1, 4, days_ago=10)
    await session.commit()

    список = await get_pulse_clients(session, "new", NO_MASTER)
    assert [c["name"] for c in список] == ["Обслуживал администратор"]
    assert список[0]["master"] is None


# --------------------------------------------------------------------------- #
# Зона риска: не потерян, но пора напомнить (решение владельца 25.09.2026)
# --------------------------------------------------------------------------- #


def test_29_дней_это_уже_зона_риска():
    assert в_зоне_риска(moscow_today() - timedelta(days=29), False, moscow_today()) is True


def test_28_дней_ещё_не_риск():
    """Порог строгий: «более 28» — значит 28 самих ещё не считаются."""
    assert в_зоне_риска(moscow_today() - timedelta(days=28), False, moscow_today()) is False


def test_59_дней_ещё_риск_60_уже_потерянный_а_не_риск():
    assert в_зоне_риска(moscow_today() - timedelta(days=59), False, moscow_today()) is True
    assert в_зоне_риска(moscow_today() - timedelta(days=60), False, moscow_today()) is False


def test_будущая_запись_снимает_зону_риска():
    assert в_зоне_риска(moscow_today() - timedelta(days=40), True, moscow_today()) is False


@pytest.mark.asyncio
async def test_риск_не_входит_в_base_total_пяти_сегментов(session: AsyncSession):
    """Зона риска пересекается с сегментами (не важно число визитов), поэтому
    она не должна прибавляться к сумме, иначе появятся клиенты сверх базы."""
    await _seed(session)
    await _клиент(session, 1, "В зоне риска, но новый")
    await _визит(session, 1, 1, days_ago=40)
    await session.commit()

    итог = await build_base_pulse(session)
    assert итог["base_total"] == 1
    assert итог["risk_zone"]["total"] == 1
    по_столбцам = sum(c["count"] for s in итог["segments"] for c in s["columns"])
    assert по_столбцам == 1


@pytest.mark.asyncio
async def test_клик_по_зоне_риска_отдаёт_клиента(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "Давно не было")
    await _визит(session, 1, 1, days_ago=45)
    await _клиент(session, 2, "Был недавно")
    await _визит(session, 2, 1, days_ago=5)
    await session.commit()

    список = await get_pulse_clients(session, "risk", КСЕНИЯ)
    assert [c["name"] for c in список] == ["Давно не было"]
    assert список[0]["days_since"] == 45


@pytest.mark.asyncio
async def test_зона_риска_сортирована_ближе_к_порогу_вперёд(session: AsyncSession):
    await _seed(session)
    await _клиент(session, 1, "35 дней")
    await _визит(session, 1, 1, days_ago=35)
    await _клиент(session, 2, "55 дней")
    await _визит(session, 2, 1, days_ago=55)
    await session.commit()

    список = await get_pulse_clients(session, "risk", КСЕНИЯ)
    assert [c["name"] for c in список] == ["55 дней", "35 дней"]
