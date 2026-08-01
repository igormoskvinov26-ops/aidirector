"""Dashboard routes — direct YCLIENTS analytics."""

from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.api.yclients import YClientsClient

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


async def get_dashboard_from_api(date_from: str, date_to: str) -> dict:
    async with YClientsClient() as client:
        records = await client.get_all_records(date_from=date_from, date_to=date_to)
        staff = await client.get_staff()
        services = await client.get_services()

    if not records:
        records = []

    staff_map = {s["id"]: s["name"] for s in staff}
    svc_map = {s["id"]: s["title"] for s in services}

    total_revenue = 0
    total_visits = 0
    new_clients = 0
    repeat_clients = 0
    by_day: dict[str, dict] = {}
    by_master: dict[int, dict] = {}
    by_service: dict[str, dict] = {}

    for r in records:
        rdate = (r.get("datetime") or "")[:10]
        if not rdate or rdate < date_from or rdate > date_to:
            continue

        if rdate not in by_day:
            by_day[rdate] = {"date": rdate, "revenue": 0, "visits": 0, "avg_check": "0"}

        rev = sum(s.get("cost", 0) for s in r.get("services", []))
        by_day[rdate]["visits"] += 1
        by_day[rdate]["revenue"] += rev
        total_revenue += rev
        total_visits += 1

        client_data = r.get("client", {})
        if client_data.get("is_new"):
            new_clients += 1
        else:
            repeat_clients += 1

        staff_id = r.get("staff_id", 0)
        if staff_id not in by_master:
            by_master[staff_id] = {
                "name": staff_map.get(staff_id, f"#{staff_id}"),
                "visits": 0,
                "revenue": 0,
                "avatar_url": next((s["avatar"] for s in staff if s["id"] == staff_id), None),
            }
        by_master[staff_id]["visits"] += 1
        by_master[staff_id]["revenue"] += rev

        for svc in r.get("services", []):
            sname = svc.get("title", f"#{svc.get('id')}")
            if sname not in by_service:
                by_service[sname] = {"name": sname, "count": 0, "revenue": 0}
            by_service[sname]["count"] += 1
            by_service[sname]["revenue"] += svc.get("cost", 0)

    for d in by_day.values():
        d["avg_check"] = str(round(d["revenue"] / d["visits"], 2)) if d["visits"] else "0"

    completed = total_visits
    avg_check = round(total_revenue / completed, 2) if completed else 0
    retention_pct = round(repeat_clients / max(new_clients + repeat_clients, 1) * 100, 1)

    masters = sorted(by_master.values(), key=lambda x: x["revenue"], reverse=True)[:10]
    for m in masters:
        m["avg_check"] = str(round(m["revenue"] / m["visits"], 2)) if m["visits"] else "0"
        m["revenue"] = str(m["revenue"])
        m["retention_pct"] = 0
        m["product_sales"] = "0"

    top_services = sorted(by_service.values(), key=lambda x: x["revenue"], reverse=True)[:10]
    for s in top_services:
        s["pctRevenue"] = round(s["revenue"] / max(total_revenue, 1) * 100, 1)
        s["revenue"] = str(s["revenue"])

    return {
        "period": f"{date_from} — {date_to}",
        "kpis": {
            "total_revenue": str(total_revenue),
            "avg_check": str(avg_check),
            "total_visits": total_visits,
            "new_clients": new_clients,
            "repeat_clients": repeat_clients,
            "retention_pct": retention_pct,
            "ltv": "0",
            "cancellation_pct": 0,
            "product_sales": "0",
            "profit": str(total_revenue),
        },
        "revenue_trend": sorted(by_day.values(), key=lambda d: d["date"]),
        "top_masters": masters,
        "cancellation_rate": 0,
    }


@router.get("/")
async def dashboard(
    days: int = Query(30, description="Days to cover"),
) -> dict:
    date_to = date.today()
    date_from = date_to - timedelta(days=days)
    return await get_dashboard_from_api(date_from.isoformat(), date_to.isoformat())


@router.get("/range")
async def dashboard_range(
    date_from: str = Query(..., description="Start date YYYY-MM-DD"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
) -> dict:
    return await get_dashboard_from_api(date_from, date_to)
