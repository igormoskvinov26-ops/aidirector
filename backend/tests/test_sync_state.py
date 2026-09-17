"""Что показывает надпись о свежести данных.

Владелец спросил: на каждой странице должно стоять время последнего
обновления и признак того, что загрузка идёт. Главная тонкость — различать
последнюю удачную выгрузку и последнюю попытку. Если попытки падают пять
часов подряд, на экране обязаны стоять и время удачной, и предупреждение:
иначе вчерашние числа выглядят как сегодняшние.
"""

from datetime import UTC, datetime

import pytest

from app.services import sync


class ПоддельныйОтвет:
    def __init__(self, значение):
        self._значение = значение

    def scalar_one_or_none(self):
        return self._значение


class ПоддельнаяСессия:
    """Отдаёт заранее заданные ответы по порядку запросов.

    Порядок в get_sync_state такой: сначала последняя удачная, потом последняя
    любая. Если ответов не хватило — значит запросов стало больше, и тест
    должен об этом сказать, а не молча пройти.
    """

    def __init__(self, ответы):
        self._ответы = list(ответы)
        self.запросов = 0

    async def execute(self, _stmt):
        self.запросов += 1
        assert self._ответы, "запросов больше, чем подготовлено ответов"
        return ПоддельныйОтвет(self._ответы.pop(0))


class ПадающаяСессия:
    async def execute(self, _stmt):
        raise RuntimeError('relation "sync_runs" does not exist')


def прогон(**поля):
    """Строка журнала выгрузок. Поля те же, что у модели."""
    основа = {
        "finished_at": datetime(2026, 9, 17, 10, 40, tzinfo=UTC),
        "ok": True,
        "error": None,
        "staff_count": 4,
        "services_count": 37,
        "clients_count": 1200,
        "visits_count": 2441,
        "sales_count": 88,
    }
    основа.update(поля)
    return type("Прогон", (), основа)()


@pytest.fixture(autouse=True)
def сбросить_память():
    """Состояние процесса — глобальное. Между тестами его надо возвращать."""
    yield
    sync._sync_in_progress = False
    sync._sync_stage = None


@pytest.mark.asyncio
async def test_выгрузок_не_было_ничего_не_придумываем():
    состояние = await sync.get_sync_state(ПоддельнаяСессия([None, None]))
    assert состояние["last_success_at"] is None
    assert состояние["last_attempt_at"] is None
    assert состояние["last_error"] is None
    assert состояние["counts"] is None


@pytest.mark.asyncio
async def test_удачная_выгрузка_даёт_время_и_числа():
    удачная = прогон()
    состояние = await sync.get_sync_state(ПоддельнаяСессия([удачная, удачная]))
    assert состояние["last_success_at"] == "2026-09-17T10:40:00+00:00"
    assert состояние["counts"]["visits"] == 2441
    assert состояние["counts"]["clients"] == 1200
    assert состояние["last_error"] is None


@pytest.mark.asyncio
async def test_упавшая_попытка_не_затирает_время_удачной():
    """Самый важный случай. Данные на экране — от удачной выгрузки, а о том,
    что последняя попытка упала, надо предупредить отдельно."""
    удачная = прогон(finished_at=datetime(2026, 9, 17, 6, 0, tzinfo=UTC))
    упавшая = прогон(
        finished_at=datetime(2026, 9, 17, 11, 0, tzinfo=UTC),
        ok=False,
        error="ForeignKeyViolationError: visit_services_service_id_fkey",
    )
    состояние = await sync.get_sync_state(ПоддельнаяСессия([удачная, упавшая]))

    assert состояние["last_success_at"] == "2026-09-17T06:00:00+00:00"
    assert состояние["last_attempt_at"] == "2026-09-17T11:00:00+00:00"
    assert "ForeignKeyViolationError" in состояние["last_error"]
    # Числа остаются от удачной: у упавшей их нет.
    assert состояние["counts"]["visits"] == 2441


@pytest.mark.asyncio
async def test_после_удачной_попытки_предупреждения_нет():
    удачная = прогон()
    состояние = await sync.get_sync_state(ПоддельнаяСессия([удачная, удачная]))
    assert состояние["last_error"] is None


@pytest.mark.asyncio
async def test_идущая_выгрузка_называет_шаг_по_русски():
    sync._sync_in_progress = True
    sync._sync_stage = "clients"
    состояние = await sync.get_sync_state(ПоддельнаяСессия([None, None]))
    assert состояние["in_progress"] is True
    assert состояние["stage"] == "клиенты"


@pytest.mark.asyncio
async def test_все_шаги_переводятся():
    """Непереведённый шаг покажет на экране английское слово из кода."""
    for код in ("staff", "services", "clients", "visits", "sales", "segments"):
        assert sync.STAGES.get(код), f"шаг {код} без русского названия"


@pytest.mark.asyncio
async def test_неизвестный_шаг_не_показывается():
    sync._sync_stage = "что-то новое"
    состояние = await sync.get_sync_state(ПоддельнаяСессия([None, None]))
    assert состояние["stage"] is None


@pytest.mark.asyncio
async def test_если_таблицы_нет_экран_всё_равно_работает():
    """Миграции могли не прогоняться. Показать страницу без отметки лучше,
    чем не показать страницу."""
    sync._sync_in_progress = True
    состояние = await sync.get_sync_state(ПадающаяСессия())
    assert состояние["in_progress"] is True
    assert состояние["last_success_at"] is None
