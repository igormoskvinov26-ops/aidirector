"""Салон и Мак через настоящий общий сервер (hub/app.py): ничья отметка не
должна теряться и не должна доставаться другому клиенту.

Сервер принимает документ, только если отправитель видел последнюю версию
(base_seq), иначе 409 — и тогда отправитель забирает чужую копию. До 9.25.6
чужая копия «состояния клиентов» затирала свежие отметки целиком: салон
ставил «Записан», Мак в ту же минуту менял светофор — и «Записан» у салона
пропадал, клиент возвращался в очередь (разбор жалобы 22.11.2026).
"""

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.models import Base, Client, ClientTag, ClientTagLink
from app.services import client_base, hub

КОРЕНЬ = Path(__file__).resolve().parents[2]


@pytest.fixture
def сервер(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_TOKEN", "t")
    monkeypatch.setenv("HUB_DB", str(tmp_path / "hub.db"))
    spec = importlib.util.spec_from_file_location("hub_server_test", КОРЕНЬ / "hub" / "app.py")
    модуль = importlib.util.module_from_spec(spec)
    sys.modules["hub_server_test"] = модуль
    spec.loader.exec_module(модуль)
    monkeypatch.setattr(hub, "_префикс", lambda: "")
    yield модуль.app
    sys.modules.pop("hub_server_test", None)


async def _машина() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)()


def _клиент_hub(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub",
                             headers={"Authorization": "Bearer t"})


async def _цикл(session, app) -> dict:
    async with _клиент_hub(app) as c:
        итог = await hub.обмен(session, c)
    await session.commit()
    return итог


async def _клиент(session, local_id: int) -> Client:
    return (await session.execute(select(Client).where(Client.id == local_id))).scalars().one()


@pytest.mark.asyncio
async def test_отметка_салона_не_теряется_при_встречной_правке_с_мака(сервер):
    салон, мак = await _машина(), await _машина()
    завтра = client_base.moscow_today() + timedelta(days=1)
    # Один клиент YCLIENTS, у каждой машины свой внутренний номер.
    салон.add(Client(id=1, yclients_id=501, name="Иван", phone="+79990000001",
                     call_status="no_answer", next_contact_at=завтра))
    мак.add(Client(id=7, yclients_id=501, name="Иван", phone="+79990000001"))
    await салон.commit()
    await мак.commit()
    for _ in range(2):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)
    assert (await _клиент(мак, 7)).call_status == "no_answer"

    # Мак: владелец ставит светофор и успевает отправить.
    к = await _клиент(мак, 7)
    к.loyalty = "green"
    await мак.commit()
    await _цикл(мак, сервер)

    # Салон в ту же минуту: администратор записал клиента.
    к = await _клиент(салон, 1)
    к.call_status, к.next_contact_at = "booked", None
    await салон.commit()
    for _ in range(3):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)

    for сессия, local_id in ((салон, 1), (мак, 7)):
        к = await _клиент(сессия, local_id)
        await сессия.refresh(к)
        assert к.call_status == "booked", "отметка «Записан» потерялась"
        assert к.next_contact_at is None, "клиент вернулся в очередь перезвона"
        assert к.loyalty == "green", "светофор с Мака потерялся"


@pytest.mark.asyncio
async def test_не_звонить_с_салона_не_снимается_старой_копией_мака(сервер):
    салон, мак = await _машина(), await _машина()
    for s, cid in ((салон, 1), (мак, 7)):
        s.add(Client(id=cid, yclients_id=777, name="Пётр", phone="+79990000007",
                     call_status="no_booking"))
        await s.commit()
    for _ in range(2):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)

    к = await _клиент(мак, 7)
    к.loyalty = "red"
    await мак.commit()
    await _цикл(мак, сервер)

    к = await _клиент(салон, 1)
    к.do_not_call, к.call_status = True, "do_not_call"
    await салон.commit()
    for _ in range(3):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)

    for сессия, local_id in ((салон, 1), (мак, 7)):
        к = await _клиент(сессия, local_id)
        await сессия.refresh(к)
        assert к.do_not_call, "пометка «НЕ ЗВОНИТЬ» снялась сама"
        assert к.loyalty == "red"


@pytest.mark.asyncio
async def test_тег_не_теряется_при_встречной_правке(сервер):
    салон, мак = await _машина(), await _машина()
    for s, cid in ((салон, 1), (мак, 7)):
        s.add(ClientTag(id=1, code="moved", name="Переехал"))
        s.add(Client(id=cid, yclients_id=900, name="Олег", phone="+79990000009",
                     call_status="no_answer"))
        await s.commit()
    for _ in range(2):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)

    к = await _клиент(мак, 7)
    к.loyalty = "yellow"
    await мак.commit()
    await _цикл(мак, сервер)

    салон.add(ClientTagLink(client_id=1, tag_id=1))
    await салон.commit()
    for _ in range(3):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)

    for сессия, local_id in ((салон, 1), (мак, 7)):
        теги = (await сессия.execute(
            select(ClientTagLink).where(ClientTagLink.client_id == local_id))).scalars().all()
        assert len(теги) == 1, "тег «Переехал» потерялся"


async def _двое(сервер, клиент_салона: dict, клиент_мака: dict):
    салон, мак = await _машина(), await _машина()
    салон.add(ClientTag(id=1, code="moved", name="Переехал"))
    мак.add(ClientTag(id=1, code="moved", name="Переехал"))
    салон.add(Client(id=1, **клиент_салона))
    мак.add(Client(id=7, **клиент_мака))
    await салон.commit()
    await мак.commit()
    for _ in range(2):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)
    return салон, мак


async def _сойтись(салон, мак, сервер):
    for _ in range(3):
        await _цикл(салон, сервер)
        await _цикл(мак, сервер)


@pytest.mark.asyncio
async def test_снятый_светофор_снимается_и_на_другом_компьютере(сервер):
    база = {"yclients_id": 42, "name": "А", "phone": "+79990000042"}
    салон, мак = await _двое(сервер, {**база, "loyalty": "red"}, база)
    assert (await _клиент(мак, 7)).loyalty == "red"
    к = await _клиент(салон, 1)
    к.loyalty = None
    await салон.commit()
    await _сойтись(салон, мак, сервер)
    к = await _клиент(мак, 7)
    await мак.refresh(к)
    assert к.loyalty is None


@pytest.mark.asyncio
async def test_одно_поле_с_двух_сторон_побеждает_поздняя_правка(сервер):
    база = {"yclients_id": 43, "name": "Б", "phone": "+79990000043"}
    салон, мак = await _двое(сервер, {**база, "call_status": "no_answer"}, база)
    к = await _клиент(мак, 7)
    к.call_status = "no_booking"
    await мак.commit()
    await _цикл(мак, сервер)
    к = await _клиент(салон, 1)
    к.call_status = "booked"  # позже — должна победить
    await салон.commit()
    await _сойтись(салон, мак, сервер)
    for сессия, local_id in ((салон, 1), (мак, 7)):
        к = await _клиент(сессия, local_id)
        await сессия.refresh(к)
        assert к.call_status == "booked"


@pytest.mark.asyncio
async def test_старая_версия_на_маке_не_затирает_свежую_отметку(сервер):
    """Мак ещё на 9.25.5: его строки без меток свежести."""
    база = {"yclients_id": 44, "name": "В", "phone": "+79990000044"}
    салон, мак = await _двое(сервер, {**база, "call_status": "no_answer"}, база)
    к = await _клиент(салон, 1)
    к.call_status = "booked"
    await салон.commit()
    from app.services import hub as h

    старая_строка = {"yclients_id": 44, "next_contact_at": None, "call_status": "no_answer",
                     "loyalty": "green", "do_not_call": False, "tags": []}
    await h._применить(салон, "client_state", [старая_строка])
    await салон.commit()
    к = await _клиент(салон, 1)
    assert к.call_status == "booked", "строка старой версии затёрла свежую отметку"
    assert к.loyalty == "green", "поле, которое здесь не правили, должно прийти"


@pytest.mark.asyncio
async def test_удалённый_тег_снимается_у_клиентов_на_обоих(сервер):
    база = {"yclients_id": 45, "name": "Г", "phone": "+79990000045"}
    салон, мак = await _двое(сервер, база, база)
    салон.add(ClientTagLink(client_id=1, tag_id=1))
    await салон.commit()
    await _сойтись(салон, мак, сервер)
    assert len((await мак.execute(select(ClientTagLink))).scalars().all()) == 1
    await client_base.set_client_tag(салон, 1, 1, False, "Админ")
    await _сойтись(салон, мак, сервер)
    assert (await мак.execute(select(ClientTagLink))).scalars().all() == []
