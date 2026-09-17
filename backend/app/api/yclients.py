"""YCLIENTS REST API client with retry, rate limiting and caching."""

import asyncio
from datetime import date
from typing import Any

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.services.cache import cached

BASE_URL = "https://api.yclients.com/api/v1"
RATE_LIMIT_DELAY = 0.6
# Guard rail: a single call must never try to walk the entire history.
MAX_RANGE_DAYS = 400

# Со скольких страниц начинаем. Дальше предел пересчитывается от того числа
# записей, которое адрес сам обещает: размер страницы он выбирает свой, и
# угадывать его нельзя.
ПРЕДЕЛ_СТРАНИЦ = 200

# Выше этого не поднимаемся ни при каком обещанном числе. Значение выбрано
# владельцем 17.09.2026. При двадцати строках на страницу это без малого
# двадцать тысяч записей — если понадобилось больше, дело не в размере базы, а
# в том, что адрес отдаёт одно и то же по кругу.
ЖЁСТКИЙ_ПРЕДЕЛ_СТРАНИЦ = 999


def _is_retryable(exc: BaseException) -> bool:
    """Retry on transport errors and on 429/5xx, but never on 4xx client errors."""
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or 500 <= code < 600
    return False


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
                    f"Bearer {settings.yclients_partner_token}, User {self.user_token}"
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

    # ------------------------------------------------------------------ #
    # Low level
    # ------------------------------------------------------------------ #

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _request(self, path: str, params: dict | None = None) -> httpx.Response:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response

    async def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        response = await self._request(path, params)
        return response.json()

    async def _get_paginated(
        self, path: str, params: dict | None = None, page_size: int = 200
    ) -> list[dict[str, Any]]:
        """Выгрузить все страницы ответа.

        Страница считается последней, только если она пустая. Прежняя версия
        останавливалась ещё и когда строк пришло меньше, чем просили, — а
        /transactions/ отдаёт по 50, сколько ни проси, и total_count не
        присылает. Из-за этого выгрузка обрывалась на первой странице: за
        август приходило 40 визитов из примерно 370, и молча — без ошибки.
        """
        all_data: list[dict[str, Any]] = []
        page = 1
        query = (params or {}).copy()
        # Размер страницы просим под двумя именами. Какое понимает конкретный
        # адрес, из ответов не видно: /clients/ отдаёт по 20 строк, сколько ни
        # проси через page_size, и YCLIENTS об этом не сообщает. Лишний
        # непонятый параметр адрес просто игнорирует, вреда нет, а выгрузка в
        # десять раз короче, если имя угадано. Проверяется по числу страниц в
        # итоговой строке журнала, а не по предположению.
        query["page_size"] = page_size
        query["count"] = page_size
        max_pages = ПРЕДЕЛ_СТРАНИЦ
        предыдущая_метка: object = None
        # Объявлено до цикла: итоговая строка в журнале печатается и тогда,
        # когда цикл оборвался на первой же странице и присвоить было негде.
        total = 0

        while page <= max_pages:
            query["page"] = page

            # _request already retries 429/5xx with exponential backoff.
            resp = await self._request(path, params=query)
            result = resp.json()

            if isinstance(result, list):
                all_data.extend(result)
                break

            data = result.get("data", [])
            if not data:
                break

            # Если адрес не понимает параметр page, он будет отдавать одну и ту
            # же страницу до упора в max_pages и раздует ответ повторами.
            метка = data[0].get("id") if isinstance(data[0], dict) else None
            if метка is not None and метка == предыдущая_метка:
                logger.warning(f"{path}: страница {page} повторяет предыдущую, выгрузка прервана")
                break
            предыдущая_метка = метка

            all_data.extend(data)

            meta = result.get("meta") if isinstance(result, dict) else None
            total = meta.get("total_count", 0) if isinstance(meta, dict) else 0

            if total > 0 and len(all_data) >= total:
                break

            # Предел страниц считаем от обещанного числа записей, а не держим
            # постоянным. Постоянный предел режет выдачу молча: /clients/
            # отдаёт по 20 строк на страницу, и на 200 страницах поместилось
            # 4000 записей из 4082 — восемьдесят два клиента просто не доехали.
            #
            # Сколько строк на странице, знает только сам адрес, и узнаётся это
            # из его же ответа. Отсюда и предел: столько страниц, сколько нужно
            # для обещанного числа, плюс запас на последнюю неполную.
            if total > 0 and data:
                нужно = -(-total // len(data)) + 2
                max_pages = min(max(ПРЕДЕЛ_СТРАНИЦ, нужно), ЖЁСТКИЙ_ПРЕДЕЛ_СТРАНИЦ)

            await asyncio.sleep(RATE_LIMIT_DELAY)
            page += 1
            # Раз в пятьдесят страниц, а не в десять: страниц бывает больше
            # двухсот, и двадцать строк подряд об одном и том же мешают читать
            # журнал. Итог всё равно печатается отдельной строкой в конце.
            if page % 50 == 0:
                logger.info(f"  идёт выгрузка {path}: {len(all_data)} из {total or '?'}")

        if page > max_pages:
            # Не «возможно неполный», а именно неполный, и сказать, насколько:
            # по этой строке человек решает, можно ли опираться на цифры.
            нехватка = f", не хватает {total - len(all_data)}" if total else ""
            logger.warning(
                f"{path}: выгрузка оборвана на пределе {max_pages} страниц, "
                f"забрано {len(all_data)}{нехватка}. Данные неполные."
            )

        # Итог печатается всегда, а не раз в десять страниц. По нему видно,
        # столько ли забрали, сколько YCLIENTS обещал: на живой установке
        # клиентов приехало ровно 4000 — слишком круглое число, чтобы верить
        # ему без сверки, а сверять было нечем.
        #
        # total == 0 означает, что адрес не присылает total_count, — так ведёт
        # себя /transactions/. Тогда судить о полноте можно только по тому, что
        # последняя страница пришла пустой.
        logger.info(
            f"  выгружено {path}: {len(all_data)}"
            + (f" из {total}" if total else " (сколько всего — не сообщает)")
            + f", страниц {page - 1}"
        )

        return all_data

    def _ck(self, name: str, *parts: object) -> str:
        """Cache key scoped to the company this client talks to."""
        return ":".join([str(self.company_id), name, *(str(p) for p in parts)])

    # ------------------------------------------------------------------ #
    # Staff
    # ------------------------------------------------------------------ #

    async def get_staff(self) -> list[dict[str, Any]]:
        async def load() -> list[dict[str, Any]]:
            result = await self._get(f"/company/{self.company_id}/staff")
            return result.get("data", [])

        return await cached(self._ck("staff"), load)

    async def get_active_staff(self) -> list[dict[str, Any]]:
        """Staff excluding hidden, fired and the 'waiting list' pseudo-master."""
        staff = await self.get_staff()
        return [
            s
            for s in staff
            if not s.get("hidden")
            and not s.get("fired")
            and not s.get("is_fired")
            and s.get("name") != "Лист Ожидания"
        ]

    # ------------------------------------------------------------------ #
    # Clients
    # ------------------------------------------------------------------ #

    async def get_clients(self, page: int = 1, page_size: int = 200) -> dict[str, Any]:
        return await self._get(
            f"/clients/{self.company_id}",
            params={"page": page, "page_size": page_size},
        )

    async def get_all_clients(self) -> list[dict[str, Any]]:
        return await self._get_paginated(f"/clients/{self.company_id}")

    async def search_clients(
        self, phone: str | None = None, name: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if phone:
            params["phone"] = phone
        if name:
            params["name"] = name
        return await self._get_paginated(
            f"/company/{self.company_id}/clients/search", params=params
        )

    # ------------------------------------------------------------------ #
    # Records / visits
    # ------------------------------------------------------------------ #

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
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        """Fetch records for a bounded date range.

        Dates are mandatory: the previous open-ended version downloaded the whole
        history (up to 40k records, ~2 minutes) on every single request.
        """
        if not date_from or not date_to:
            raise ValueError("get_all_records requires both date_from and date_to")

        span = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days
        if span < 0:
            raise ValueError(f"date_from ({date_from}) is after date_to ({date_to})")
        if span > MAX_RANGE_DAYS:
            raise ValueError(
                f"Requested range of {span} days exceeds MAX_RANGE_DAYS={MAX_RANGE_DAYS}. "
                "Narrow the range or sync into PostgreSQL instead."
            )

        async def load() -> list[dict[str, Any]]:
            return await self._get_paginated(
                f"/records/{self.company_id}",
                params={"date_from": date_from, "date_to": date_to},
            )

        return await cached(self._ck("records", date_from, date_to), load)

    async def get_records_for_day(self, day: date) -> list[dict[str, Any]]:
        """Records for a single day — cheap, cached, used by slots and stories."""
        iso = day.isoformat()
        return await self.get_all_records(date_from=iso, date_to=iso)

    # ------------------------------------------------------------------ #
    # Services
    # ------------------------------------------------------------------ #

    async def get_services(self) -> list[dict[str, Any]]:
        async def load() -> list[dict[str, Any]]:
            result = await self._get(f"/services/{self.company_id}")
            return result.get("data", []) if isinstance(result, dict) else result

        return await cached(self._ck("services"), load)

    # ------------------------------------------------------------------ #
    # Products / sales
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Loyalty
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Financial report
    # ------------------------------------------------------------------ #

    async def get_financial_report(self, date_from: str, date_to: str) -> dict[str, Any]:
        return await self._get(
            f"/reports/finance/{self.company_id}",
            params={"date_from": date_from, "date_to": date_to},
        )

    # ------------------------------------------------------------------ #
    # Schedule
    # ------------------------------------------------------------------ #

    async def get_schedule(self, staff_id: int, day: date | str) -> dict[str, Any]:
        iso = day.isoformat() if isinstance(day, date) else day
        return await self._get(f"/schedule/{self.company_id}/{staff_id}/{iso}")

    async def get_working_staff_ids(self, day: date) -> set[int] | None:
        """Staff scheduled to work on ``day`` according to YCLIENTS.

        Returns ``None`` when the schedule endpoint is unavailable, so callers can
        fall back to a heuristic instead of silently reporting "nobody works today".
        """

        async def load() -> set[int] | None:
            staff = await self.get_active_staff()
            working: set[int] = set()
            ok = False
            for s in staff:
                try:
                    resp = await self.get_schedule(s["id"], day)
                except httpx.HTTPError as exc:
                    logger.warning(f"schedule unavailable for staff {s['id']}: {exc}")
                    continue
                ok = True
                data = resp.get("data") if isinstance(resp, dict) else None
                entries = data if isinstance(data, list) else ([data] if data else [])
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    slots = entry.get("slots") or entry.get("intervals") or []
                    if slots or entry.get("is_working"):
                        working.add(s["id"])
                        break
                await asyncio.sleep(0.15)
            return working if ok else None

        return await cached(self._ck("working", day.isoformat()), load, ttl=900)
