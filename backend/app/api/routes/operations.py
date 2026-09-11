"""Operational routes: payroll figures, free slots, staff photo proxy."""

import io
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.yclients import YClientsClient
from app.services.slots import compute_free_slots

router = APIRouter(prefix="/api", tags=["operations"])

ATTENDED = {"1", "completed", "finished"}


@router.get("/salary")
async def salary(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    company_id: int | None = None,
) -> dict:
    """Revenue and visit counts per master for a bounded period."""
    async with YClientsClient(company_id=company_id) as client:
        records = await client.get_all_records(date_from=date_from, date_to=date_to)
        staff = await client.get_active_staff()

    staff_map = {s["id"]: s for s in staff}
    by_master: dict[int, dict] = {}

    for r in records:
        sid = r.get("staff_id", 0)
        if sid not in staff_map:
            continue

        revenue = sum(s.get("cost", 0) for s in r.get("services", []))
        status = str(r.get("visit_attendance", r.get("status", "")))

        entry = by_master.setdefault(
            sid,
            {
                "id": sid,
                "name": staff_map[sid]["name"],
                "avatar": staff_map[sid].get("avatar"),
                "revenue": 0,
                "visits": 0,
                "completed": 0,
            },
        )
        entry["revenue"] += revenue
        entry["visits"] += 1
        if status in ATTENDED:
            entry["completed"] += 1

    masters = sorted(by_master.values(), key=lambda m: m["revenue"], reverse=True)

    return {
        "period": f"{date_from} — {date_to}",
        "total_revenue": sum(m["revenue"] for m in masters),
        "total_visits": sum(m["visits"] for m in masters),
        "masters": masters,
    }


@router.get("/slots")
async def slots(day: str | None = Query(None, description="YYYY-MM-DD, default today")) -> dict:
    """Free slots per working master."""
    target = date.fromisoformat(day) if day else date.today()
    async with YClientsClient() as client:
        return await compute_free_slots(client, day=target)


@router.get("/photo/{staff_id}")
async def proxy_photo(staff_id: int) -> StreamingResponse:
    """Proxy a master's avatar so the browser never talks to YCLIENTS directly."""
    async with YClientsClient() as client:
        staff = await client.get_staff()

    photo_url = next(
        (s.get("avatar_big") or s.get("avatar") for s in staff if s["id"] == staff_id),
        None,
    )
    if not photo_url:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Only proxy YCLIENTS-hosted assets — the URL comes from an API response, but
    # forwarding arbitrary URLs from it would make this endpoint an open relay.
    host = httpx.URL(photo_url).host or ""
    if not (host.endswith("yclients.com") or host.endswith("yclients.ru")):
        raise HTTPException(status_code=400, detail="Unexpected photo host")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as http:
        resp = await http.get(photo_url)
        resp.raise_for_status()
        return StreamingResponse(
            io.BytesIO(resp.content),
            media_type=resp.headers.get("content-type", "image/jpeg"),
        )
