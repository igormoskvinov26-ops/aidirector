"""YCLIENTS REST API client with automatic retry and rate limiting."""

import asyncio
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

BASE_URL = "https://api.yclients.com/api/v1"
RATE_LIMIT_DELAY = 0.6


class YClientsClient:
    def __init__(self, company_id: int | None = None, user_token: str | None = None):
        self.company_id = company_id or settings.yclients_company_id
        if user_token:
            self.user_token = user_token
        elif company_id and company_id != settings.yclients_company_id:
            self.user_token = settings.yclients_old_user_token
        else:
            self.user_token = settings.yclients_user_token
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": (
                    f"Bearer {settings.yclients_partner_token}, "
                    f"User {self.user_token}"
                ),
                "Accept": "application/vnd.yclients.v2+json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "YClientsClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    async def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def _get_paginated(
        self, path: str, params: dict | None = None, page_size: int = 200
    ) -> list[dict[str, Any]]:
        all_data: list[dict[str, Any]] = []
        page = 1
        query = (params or {}).copy()
        query["page_size"] = page_size
        max_pages = 200

        while page <= max_pages:
            query["page"] = page

            for attempt in range(3):
                resp = await self._client.get(path, params=query)
                if resp.status_code == 429:
                    wait = min(2 ** attempt, 30)
                    logger.warning(f"  Rate limited on {path}, waiting {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                result = resp.json()
                break
            else:
                raise httpx.HTTPStatusError(
                    f"Rate limit exceeded on {path} after 3 attempts",
                    request=resp.request,
                    response=resp,
                )

            if isinstance(result, list):
                all_data.extend(result)
                break

            data = result.get("data", [])
            if not data:
                break

            all_data.extend(data)

            meta = result.get("meta") if isinstance(result, dict) else None
            total = meta.get("total_count", 0) if isinstance(meta, dict) else 0

            if total > 0 and len(all_data) >= total:
                break
            if total == 0 and len(data) < page_size:
                break

            await asyncio.sleep(RATE_LIMIT_DELAY)
            page += 1
            if page % 10 == 0:
                logger.info(f"  Paginated {path}: {len(all_data)} / {total}")

        return all_data

    # ── Staff ──
    async def get_staff(self) -> list[dict[str, Any]]:
        result = await self._get(f"/company/{self.company_id}/staff")
        return result.get("data", [])

    # ── Clients ──
    async def get_clients(self, page: int = 1, page_size: int = 200) -> dict[str, Any]:
        return await self._get(
            f"/clients/{self.company_id}",
            params={"page": page, "page_size": page_size},
        )

    async def get_all_clients(self) -> list[dict[str, Any]]:
        return await self._get_paginated(f"/clients/{self.company_id}")

    async def search_clients(self, phone: str | None = None, name: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if phone:
            params["phone"] = phone
        if name:
            params["name"] = name
        return await self._get_paginated(f"/company/{self.company_id}/clients/search", params=params)

    # ── Records / Visits ──
    async def get_records(
        self,
        page: int = 1,
        page_size: int = 200,
        date_from: str | None = None,
        date_to: str | None = None,
        staff_id: int | None = None,
        client_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if staff_id:
            params["staff_id"] = staff_id
        if client_id:
            params["client_id"] = client_id
        return await self._get(f"/records/{self.company_id}", params=params)

    async def get_all_records(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._get_paginated(f"/records/{self.company_id}", params=params)

    # ── Services ──
    async def get_services(self) -> list[dict[str, Any]]:
        result = await self._get(f"/services/{self.company_id}")
        return result.get("data", []) if isinstance(result, dict) else result

    # ── Products / Sales ──
    async def get_transactions(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._get_paginated(
            f"/storages/transactions/{self.company_id}", params=params
        )

    # ── Loyalty ──
    async def get_loyalty_transactions(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._get_paginated(
            f"/loyalty/transactions/{self.company_id}", params=params
        )

    # ── Financial Report ──
    async def get_financial_report(self, date_from: str, date_to: str) -> dict[str, Any]:
        return await self._get(
            f"/reports/finance/{self.company_id}",
            params={"date_from": date_from, "date_to": date_to},
        )

    # ── Schedule ──
    async def get_schedule(self, staff_id: int, date: str) -> dict[str, Any]:
        return await self._get(
            f"/schedule/{self.company_id}/{staff_id}/{date}"
        )
