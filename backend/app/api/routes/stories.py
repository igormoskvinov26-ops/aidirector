"""Story generation and Telegram delivery."""

import base64
import io
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from loguru import logger

from app.api.yclients import YClientsClient
from app.services import configuration, salon
from app.services.slots import compute_free_slots
from app.services.stories import compute_slot_hash, generate_story
from app.services.story_preview import render_story_html

router = APIRouter(prefix="/api/stories", tags=["stories"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _caption(name: str, slots: list[str] | None = None) -> str:
    lines = [f"В {salon.name.upper()} ТЕБЯ СЕГОДНЯ ЖДУТ", "", name.upper()]
    if slots:
        lines.append("  ".join(slots[:6]))
    if salon.booking_url:
        lines.append(f"Запись: {salon.booking_url}")
    return "\n".join(lines)


async def _send_photo(data: bytes, filename: str, caption: str) -> dict:
    # Через configuration, а не напрямую из .env: бот и чат настраиваются в
    # интерфейсе, и сторис должны уходить тому же боту, что и отчёты смены.
    # Раньше здесь читался только .env, и после настройки через форму сторис
    # продолжали уходить старому боту либо не уходили вовсе.
    token = configuration.значение("TELEGRAM_BOT_TOKEN")
    chat_id = configuration.значение("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise HTTPException(
            status_code=503,
            detail="Telegram не настроен — заполните его в разделе «Настройки → Интеграции»",
        )

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": (filename, io.BytesIO(data), "image/png")},
        )
    if resp.status_code != 200:
        # Never echo Telegram's raw body: it can contain the bot token.
        logger.error(f"telegram sendPhoto failed: {resp.status_code}")
        raise HTTPException(status_code=502, detail="Telegram отклонил отправку")
    return {"status": "sent"}


@router.get("/generate")
async def generate(day: str | None = Query(None)) -> dict:
    """Render a PNG story per working master with free slots."""
    target = date.fromisoformat(day) if day else date.today()

    async with YClientsClient() as client:
        computed = await compute_free_slots(client, day=target)

    results = []
    for m in computed["masters"]:
        if not m["free_slots"]:
            results.append({"name": m["name"], "status": "no_slots"})
            continue
        try:
            path = generate_story(m["name"], m["free_slots"], target)
            results.append(
                {
                    "name": m["name"],
                    "status": "ok",
                    "path": str(path),
                    "hash": compute_slot_hash(m["free_slots"]),
                    "slots": len(m["free_slots"]),
                }
            )
        except Exception as exc:
            logger.exception(f"story generation failed for {m['name']}")
            results.append({"name": m["name"], "status": "error", "error": str(exc)})

    return {"date": computed["date"], "source": computed["source"], "results": results}


@router.post("/send")
async def send(day: str | None = Query(None)) -> dict:
    """Generate and push stories to the Telegram channel."""
    target = date.fromisoformat(day) if day else date.today()

    async with YClientsClient() as client:
        computed = await compute_free_slots(client, day=target)

    sent = []
    for m in computed["masters"]:
        if not m["free_slots"]:
            continue
        try:
            path = generate_story(m["name"], m["free_slots"], target)
            with open(path, "rb") as fh:
                await _send_photo(fh.read(), "story.png", _caption(m["name"], m["free_slots"]))
            sent.append({"name": m["name"], "status": "sent"})
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(f"story send failed for {m['name']}")
            sent.append({"name": m["name"], "status": "error", "error": str(exc)})

    return {"date": computed["date"], "sent": sent}


@router.post("/upload-send")
async def upload_and_send(request: Request) -> dict:
    """Accept a browser-composed PNG (base64) and forward it to Telegram."""
    body = await request.json()
    image_b64 = body.get("image", "")
    master_name = str(body.get("name", "master"))[:100]

    if not image_b64:
        raise HTTPException(status_code=400, detail="Нет изображения")
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Некорректный base64") from None

    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Изображение больше 8 МБ")

    await _send_photo(image_bytes, "story.png", _caption(master_name))
    return {"status": "ok", "name": master_name}


@router.get("/preview/{master_name}")
async def preview(master_name: str, day: str | None = Query(None)) -> Response:
    """HTML version of a story, for browser-side composition via html2canvas."""
    target = date.fromisoformat(day) if day else date.today()

    async with YClientsClient() as client:
        computed = await compute_free_slots(client, day=target)

    master = next((m for m in computed["masters"] if m["name"] == master_name), None)
    if master is None:
        raise HTTPException(status_code=404, detail="Master not found or not working")

    html = render_story_html(
        master_name=master_name,
        free_slots=master["free_slots"],
        photo_url=f"/api/photo/{master['id']}" if master["avatar"] else "",
        target_date=target,
    )
    return Response(content=html, media_type="text/html; charset=utf-8")
