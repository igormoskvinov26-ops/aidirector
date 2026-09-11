"""Tests for the slot logic — the part that was silently inverted."""

from datetime import date, datetime

import pytest

from app.services import slots


class FakeClient:
    """Stands in for YClientsClient without touching the network."""

    def __init__(self, staff, records, working=None):
        self._staff, self._records, self._working = staff, records, working

    async def get_active_staff(self):
        return self._staff

    async def get_records_for_day(self, day):
        return self._records

    async def get_working_staff_ids(self, day):
        return self._working


DAY = date(2026, 9, 10)
NOW = datetime(2026, 9, 10, 9, 0)

STAFF = [
    {"id": 1, "name": "Дмитрий"},
    {"id": 2, "name": "Ксения"},
    {"id": 3, "name": "Арташ"},
]


@pytest.mark.asyncio
async def test_master_with_empty_day_is_shown():
    """The original bug: a master with zero bookings was reported as not working.

    That hid exactly the person whose free slots most needed advertising.
    """
    booking = {
        "staff_id": 1,
        "datetime": "2026-09-10T12:00:00",
        "seance_length": 3600,
    }
    client = FakeClient(STAFF, [booking], working={1, 2, 3})

    result = await slots.compute_free_slots(client, day=DAY, now=NOW)
    names = [m["name"] for m in result["masters"]]

    assert "Ксения" in names, "мастер со свободным днём обязан попасть в выдачу"
    assert "Арташ" in names
    assert result["masters_working"] == 3


@pytest.mark.asyncio
async def test_emptiest_master_comes_first():
    booking = {"staff_id": 1, "datetime": "2026-09-10T12:00:00", "seance_length": 3600}
    client = FakeClient(STAFF, [booking], working={1, 2, 3})

    result = await slots.compute_free_slots(client, day=DAY, now=NOW)
    assert result["masters"][0]["name"] != "Дмитрий"


@pytest.mark.asyncio
async def test_booking_blocks_its_full_duration():
    """A 60-minute service must occupy two 30-minute cells, not one."""
    booking = {"staff_id": 1, "datetime": "2026-09-10T12:00:00", "seance_length": 3600}
    client = FakeClient([STAFF[0]], [booking], working={1})

    result = await slots.compute_free_slots(client, day=DAY, now=NOW)
    free = result["masters"][0]["free_slots"]

    assert "12:00" not in free
    assert "12:30" not in free, "вторая половина часовой стрижки тоже занята"
    assert "13:00" in free


@pytest.mark.asyncio
async def test_past_times_are_excluded():
    client = FakeClient([STAFF[0]], [], working={1})
    result = await slots.compute_free_slots(
        client, day=DAY, now=datetime(2026, 9, 10, 15, 15)
    )
    free = result["masters"][0]["free_slots"]

    assert "10:00" not in free
    assert "15:00" not in free
    assert "15:30" in free


@pytest.mark.asyncio
async def test_schedule_unavailable_falls_back_to_all_active():
    """If the schedule endpoint is down, show everyone rather than nobody."""
    client = FakeClient(STAFF, [], working=None)
    result = await slots.compute_free_slots(client, day=DAY, now=NOW)

    assert result["source"] == "fallback_all_active"
    assert result["masters_working"] == 3
