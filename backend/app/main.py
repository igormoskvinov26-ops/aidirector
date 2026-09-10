"""Rubl AI Director — FastAPI Application."""

import asyncio
import base64
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes.ai import router as ai_router
from app.api.routes.client_base import router as client_base_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.employees import router as employees_router
from app.api.routes.finance import router as finance_router
from app.api.routes.sync import router as sync_router
from app.config import settings
from app.database import init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Rubl Director"'},
                content="Authentication required",
            )

        try:
            decoded = base64.b64decode(auth[6:]).decode()
            login, password = decoded.split(":", 1)
        except Exception:
            return Response(status_code=401, content="Invalid credentials")

        if not secrets.compare_digest(login, settings.admin_login) or \
           not secrets.compare_digest(password, settings.admin_password):
            return Response(status_code=401, content="Invalid credentials")

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Rubl AI Director...")
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database not available, running without DB: {e}")

    from app.services.sync import run_sync_loop

    sync_task = asyncio.create_task(run_sync_loop())

    yield

    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down...")


app = FastAPI(
    title="Rubl AI Director",
    version="1.0.0",
    description="AI-powered management system for Rubl Barbershop",
    lifespan=lifespan,
)

app.add_middleware(BasicAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)
app.include_router(client_base_router)
app.include_router(dashboard_router)
app.include_router(employees_router)
app.include_router(finance_router)
app.include_router(sync_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/info")
async def info() -> dict[str, int | str]:
    return {
        "company_id": settings.yclients_company_id,
        "sync_interval_minutes": settings.sync_interval_minutes,
    }


@app.get("/api/salary")
async def salary(
    date_from: str,
    date_to: str,
    company_id: int | None = None,
) -> dict:
    from app.api.yclients import YClientsClient

    async with YClientsClient(company_id=company_id) as client:
        records = await client.get_all_records()
        staff = await client.get_staff()

    staff_map = {s["id"]: s for s in staff if not s.get("hidden") and s.get("name") != "Лист Ожидания"}

    by_master: dict[int, dict] = {}
    for r in records:
        rdate = (r.get("datetime") or "")[:10]
        if rdate < date_from or rdate > date_to:
            continue

        sid = r.get("staff_id", 0)
        if sid not in staff_map:
            continue

        rev = sum(s.get("cost", 0) for s in r.get("services", []))
        status = str(r.get("visit_attendance", r.get("status", "")))

        if sid not in by_master:
            by_master[sid] = {
                "id": sid,
                "name": staff_map[sid]["name"],
                "avatar": staff_map[sid].get("avatar"),
                "revenue": 0,
                "visits": 0,
                "completed": 0,
            }

        by_master[sid]["revenue"] += rev
        by_master[sid]["visits"] += 1
        if status in ("1", "completed", "finished"):
            by_master[sid]["completed"] += 1

    masters_list = sorted(by_master.values(), key=lambda x: x["revenue"], reverse=True)

    total_revenue = sum(m["revenue"] for m in masters_list)
    total_visits = sum(m["visits"] for m in masters_list)

    return {
        "period": f"{date_from} — {date_to}",
        "total_revenue": total_revenue,
        "total_visits": total_visits,
        "masters": masters_list,
    }


@app.get("/api/slots")
async def slots() -> dict:
    from datetime import date, datetime
    from app.api.yclients import YClientsClient

    today = date.today()
    today_str = today.isoformat()
    now = datetime.now()

    async with YClientsClient() as client:
        staff = await client.get_staff()
        records = await client.get_all_records()

    today_records = [r for r in records if (r.get("datetime") or "")[:10] == today_str]
    staff_by_id = {s["id"]: s for s in staff}

    # Find masters with appointments today (they're working)
    working_ids = set()
    for r in today_records:
        sid = r.get("staff_id")
        if sid:
            working_ids.add(sid)

    masters = []
    for sid in working_ids:
        s = staff_by_id.get(sid)
        if not s:
            continue
        name = s.get("name", "")
        if name == "Лист Ожидания" or s.get("fired") or s.get("is_fired"):
            continue

        booked_times = set()
        free_slots = []

        for r in today_records:
            if r.get("staff_id") != sid:
                continue
            dt = r.get("datetime") or ""
            time_part = dt[11:16] if len(dt) >= 16 else ""
            if time_part:
                booked_times.add(time_part)

        for hour in range(10, 22):
            for minute in (0, 30):
                t = f"{hour:02d}:{minute:02d}"
                if t in booked_times:
                    continue
                try:
                    slot_dt = datetime(today.year, today.month, today.day, hour, minute)
                    if slot_dt <= now:
                        continue
                except ValueError:
                    continue
                free_slots.append(t)

        if free_slots:
            masters.append({
                "id": sid,
                "name": name,
                "avatar": s.get("avatar"),
                "specialization": s.get("specialization"),
                "free_slots": free_slots,
                "booked_count": len(booked_times),
            })

    return {
        "date": today_str,
        "masters": masters,
        "total_free": sum(len(m["free_slots"]) for m in masters),
    }


@app.get("/api/stories/generate")
async def generate_stories_endpoint() -> dict:
    from datetime import date, datetime
    from app.api.yclients import YClientsClient
    from app.services.stories import generate_story, compute_slot_hash

    today = date.today()
    today_str = today.isoformat()
    now = datetime.now()

    async with YClientsClient() as client:
        staff = await client.get_staff()
        records = await client.get_all_records()

    today_records = [r for r in records if (r.get("datetime") or "")[:10] == today_str]
    staff_by_id = {s["id"]: s for s in staff}

    working_ids = {r.get("staff_id") for r in today_records if r.get("staff_id")}

    results = []
    for sid in working_ids:
        s = staff_by_id.get(sid)
        if not s:
            continue
        name = s.get("name", "")
        if name == "Лист Ожидания" or s.get("fired") or s.get("is_fired"):
            continue

        booked_times = set()
        for r in today_records:
            if r.get("staff_id") == sid:
                dt = r.get("datetime") or ""
                if len(dt) >= 16:
                    booked_times.add(dt[11:16])

        free_slots = []
        for hour in range(10, 22):
            for minute in (0, 30):
                t = f"{hour:02d}:{minute:02d}"
                if t in booked_times:
                    continue
                try:
                    slot_dt = datetime(today.year, today.month, today.day, hour, minute)
                    if slot_dt <= now:
                        continue
                except ValueError:
                    continue
                free_slots.append(t)

        if not free_slots:
            results.append({"name": name, "status": "no_slots"})
            continue

        try:
            path = generate_story(name, free_slots, today)
            h = compute_slot_hash(free_slots)
            results.append({"name": name, "status": "ok", "path": path, "hash": h, "slots": len(free_slots)})
        except Exception as e:
            results.append({"name": name, "status": "error", "error": str(e)})

    return {"date": today_str, "results": results}


@app.post("/api/stories/send")
async def send_stories_to_telegram() -> dict:
    import httpx
    from datetime import date, datetime
    from app.api.yclients import YClientsClient
    from app.services.stories import generate_story

    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id

    if not token or not chat_id:
        return {"status": "error", "message": "TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID не настроены в .env"}

    today = date.today()
    today_str = today.isoformat()
    now = datetime.now()

    async with YClientsClient() as client:
        staff = await client.get_staff()
        records = await client.get_all_records()

    today_records = [r for r in records if (r.get("datetime") or "")[:10] == today_str]
    staff_by_id = {s["id"]: s for s in staff}
    working_ids = {r.get("staff_id") for r in today_records if r.get("staff_id")}

    sent = []
    for sid in working_ids:
        s = staff_by_id.get(sid)
        if not s:
            continue
        name = s.get("name", "")
        if name == "Лист Ожидания" or s.get("fired") or s.get("is_fired"):
            continue

        booked_times = set()
        for r in today_records:
            if r.get("staff_id") == sid:
                dt = r.get("datetime") or ""
                if len(dt) >= 16:
                    booked_times.add(dt[11:16])

        free_slots = []
        for hour in range(10, 22):
            for minute in (0, 30):
                t = f"{hour:02d}:{minute:02d}"
                if t in booked_times:
                    continue
                try:
                    slot_dt = datetime(today.year, today.month, today.day, hour, minute)
                    if slot_dt <= now:
                        continue
                except ValueError:
                    continue
                free_slots.append(t)

        if not free_slots:
            continue

        path = generate_story(name, free_slots, today)

        try:
            async with httpx.AsyncClient(timeout=30) as http:
                with open(path, "rb") as f:
                    caption = f"В РУБЛЪ ТЕБЯ СЕГОДНЯ ЖДУТ\n\n{name.upper()}\n{'  '.join(free_slots[:6])}"
                    resp = await http.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data={"chat_id": chat_id, "caption": caption},
                        files={"photo": f},
                    )
                    if resp.status_code == 200:
                        sent.append({"name": name, "status": "sent"})
                    else:
                        sent.append({"name": name, "status": "error", "error": resp.text[:200]})
        except Exception as e:
            sent.append({"name": name, "status": "error", "error": str(e)})

    return {"date": today_str, "sent": sent}


@app.post("/api/stories/upload-send")
async def upload_and_send(request: Request) -> dict:
    import io
    import base64
    import httpx
    import os

    body = await request.json()
    image_b64 = body.get("image", "")
    master_name = body.get("name", "master")

    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id

    if not token or not chat_id:
        return {"status": "error", "message": "Telegram не настроен"}

    if not image_b64:
        return {"status": "error", "message": "Нет изображения"}

    # Decode base64 to bytes
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    image_bytes = base64.b64decode(image_b64)

    caption = f"В РУБЛЪ ТЕБЯ СЕГОДНЯ ЖДУТ\n\n{master_name.upper()}\nЗапись: n2387007.yclients.com"

    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": ("story.png", io.BytesIO(image_bytes), "image/png")},
            )
            if resp.status_code == 200:
                return {"status": "ok", "name": master_name}
            else:
                return {"status": "error", "message": resp.text[:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/stories/preview/{master_name}")
async def story_preview(master_name: str) -> Response:
    from datetime import date, datetime
    from app.api.yclients import YClientsClient
    from app.services.story_preview import render_story_html

    today = date.today()
    today_str = today.isoformat()
    now = datetime.now()

    async with YClientsClient() as client:
        staff = await client.get_staff()
        records = await client.get_all_records()

    today_records = [r for r in records if (r.get("datetime") or "")[:10] == today_str]
    staff_by_id = {s["id"]: s for s in staff}

    # Find the master
    master_sid = None
    master_photo = None
    for s in staff:
        if s.get("name") == master_name and s["name"] != "Лист Ожидания":
            master_sid = s["id"]
            master_photo = s.get("avatar_big") or s.get("avatar")
            break

    if not master_sid:
        return Response("Master not found", status_code=404)

    # Calculate free slots
    booked_times = set()
    for r in today_records:
        if r.get("staff_id") != master_sid:
            continue
        dt = r.get("datetime") or ""
        time_part = dt[11:16] if len(dt) >= 16 else ""
        if time_part:
            booked_times.add(time_part)

    free_slots = []
    for hour in range(10, 22):
        for minute in (0, 30):
            t = f"{hour:02d}:{minute:02d}"
            if t in booked_times:
                continue
            try:
                slot_dt = datetime(today.year, today.month, today.day, hour, minute)
                if slot_dt <= now:
                    continue
            except ValueError:
                continue
            free_slots.append(t)

    photo_src = f"/api/photo/{master_sid}" if master_photo else ""

    html = render_story_html(
        master_name=master_name,
        free_slots=free_slots,
        photo_url=photo_src,
        target_date=today,
    )

    return Response(content=html, media_type="text/html; charset=utf-8")


@app.get("/api/photo/{staff_id}")
async def proxy_photo(staff_id: int):
    import io
    import httpx
    from app.api.yclients import YClientsClient

    async with YClientsClient() as client:
        staff = await client.get_staff()

    photo_url = None
    for s in staff:
        if s["id"] == staff_id:
            photo_url = s.get("avatar_big") or s.get("avatar")
            break

    if not photo_url:
        raise HTTPException(status_code=404, detail="Photo not found")

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(photo_url)
        return StreamingResponse(
            io.BytesIO(resp.content),
            media_type=resp.headers.get("content-type", "image/jpeg"),
        )


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    logger.info(f"Serving static files from {STATIC_DIR}")
else:
    logger.info("No static directory, API-only mode")
