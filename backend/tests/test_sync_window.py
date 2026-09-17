"""Окно выгрузки должно захватывать будущее.

Раздел предстоящих записей читает их из своей базы, а не из YCLIENTS.
Пока окно выгрузки заканчивалось сегодняшним днём, записей на завтра в базе
не было вовсе — и раздел оставался пустым при полностью исправной выгрузке.
Найдено на живой установке 17.09.2026: владелец запустил Директора и увидел
пустые «будущие записи».
"""

from datetime import date, timedelta

from app.config import settings
from app.services.sync import default_window


def test_окно_кончается_в_будущем():
    сегодня = date(2026, 9, 17)
    _, вперёд = default_window(сегодня)
    assert date.fromisoformat(вперёд) > сегодня


def test_вперёд_ровно_на_сколько_настроено():
    сегодня = date(2026, 9, 17)
    _, вперёд = default_window(сегодня)
    assert date.fromisoformat(вперёд) == сегодня + timedelta(
        days=settings.sync_window_ahead_days
    )


def test_назад_ровно_на_сколько_настроено():
    сегодня = date(2026, 9, 17)
    назад, _ = default_window(сегодня)
    assert date.fromisoformat(назад) == сегодня - timedelta(days=settings.sync_window_days)


def test_горизонт_выгрузки_не_меньше_того_что_показывает_интерфейс():
    """Иначе в списке предстоящих будут дни, про которые данных нет.

    Интерфейс умеет показывать записи на MAX_DAYS_AHEAD дней вперёд. Если
    выгрузка заходит вперёд на меньший срок, дальние дни окажутся пустыми не
    потому, что записей нет, а потому, что их не забрали.
    """
    from app.services.bookings import MAX_DAYS_AHEAD

    assert settings.sync_window_ahead_days >= MAX_DAYS_AHEAD


def test_окно_не_сужается_до_одного_дня():
    сегодня = date(2026, 9, 17)
    назад, вперёд = default_window(сегодня)
    assert date.fromisoformat(назад) < date.fromisoformat(вперёд)
