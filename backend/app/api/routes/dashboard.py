"""Dashboard routes — direct YCLIENTS analytics."""

from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.api.yclients import YClientsClient

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


async def get_dashboard_from_api(date_from: str, date_to: str, company_id: int | None = None) -> dict:
    async with YClientsClient(company_id=company_id) as client:
        records = await client.get_all_records(date_from=date_from, date_to=date_to)
        staff = await client.get_staff()
        services = await client.get_services()
        transactions = await client.get_transactions(date_from=date_from, date_to=date_to)

    if not records:
        records = []

    staff_map = {s["id"]: s["name"] for s in staff}
    svc_map = {s["id"]: s["title"] for s in services}

    total_revenue = 0
    total_visits = 0
    new_clients = 0
    repeat_clients = 0
    total_cancelled = 0
    total_product_sales = 0
    by_day: dict[str, dict] = {}
    by_master: dict[int, dict] = {}
    by_service: dict[str, dict] = {}

    for r in records:
        rdate = (r.get("datetime") or "")[:10]
        if not rdate or rdate < date_from or rdate > date_to:
            continue

        va = r.get("visit_attendance")
        va_int = int(va) if va is not None else 0

        if va_int == 2:
            total_cancelled += 1

        if va_int != 1:
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

    cancellation_pct = round(total_cancelled / max(total_visits + total_cancelled, 1) * 100, 1)

    for t in transactions:
        if t.get("type_id") in (2, 4):
            td = (t.get("create_date") or "")[:10]
            if td >= date_from and td <= date_to:
                total_product_sales += abs(int(t.get("cost", 0)))

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
            "cancellation_pct": cancellation_pct,
            "product_sales": str(total_product_sales),
            "profit": str(total_revenue + total_product_sales),
        },
        "revenue_trend": sorted(by_day.values(), key=lambda d: d["date"]),
        "top_masters": masters,
        "cancellation_rate": 0,
    }


@router.get("/")
async def dashboard(
    days: int = Query(0, description="Days to cover (0 = current month)"),
    company_id: int | None = Query(None, description="Override company ID"),
) -> dict:
    today = date.today()
    if days > 0:
        date_from = today - timedelta(days=days)
    else:
        date_from = today.replace(day=1)
    date_to = today
    return await get_dashboard_from_api(date_from.isoformat(), date_to.isoformat(), company_id)


@router.get("/range")
async def dashboard_range(
    date_from: str = Query(..., description="Start date YYYY-MM-DD"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
    company_id: int | None = Query(None, description="Override company ID"),
) -> dict:
    return await get_dashboard_from_api(date_from, date_to, company_id)
