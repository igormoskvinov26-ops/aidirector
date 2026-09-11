"""The record fetcher must not be able to download the whole history again."""

import pytest

from app.api.yclients import YClientsClient


@pytest.mark.asyncio
async def test_missing_dates_are_rejected():
    client = YClientsClient()
    try:
        with pytest.raises(ValueError):
            await client.get_all_records(date_from="", date_to="")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_absurdly_wide_range_is_rejected():
    client = YClientsClient()
    try:
        with pytest.raises(ValueError, match="MAX_RANGE_DAYS"):
            await client.get_all_records(date_from="2017-01-01", date_to="2026-09-01")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_reversed_range_is_rejected():
    client = YClientsClient()
    try:
        with pytest.raises(ValueError, match="after"):
            await client.get_all_records(date_from="2026-09-10", date_to="2026-09-01")
    finally:
        await client.close()
