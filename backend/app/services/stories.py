"""Story generator — creates 1080×1920 PNG for Telegram stories."""

import hashlib
import io
import os
from datetime import date

from loguru import logger
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from app.config import settings

WIDTH = 1080
HEIGHT = 1920

# Configurable, not hardcoded to the VPS path — the old value made stories
# impossible to generate anywhere but production.
OUTPUT_DIR = settings.stories_dir

# Brand faces first (drop the .ttf files into assets/fonts/), system faces only
# as a last resort so a missing font degrades instead of crashing.
BRAND_REGULAR = ["Manrope-Regular.ttf", "Manrope-Medium.ttf", "JetBrainsMono-Regular.ttf"]
BRAND_BOLD = ["Manrope-Bold.ttf", "Cormorant-Bold.ttf", "Manrope-ExtraBold.ttf"]

SYSTEM_FALLBACK = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
SYSTEM_FALLBACK_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

_warned: set[str] = set()


def _load(candidates: list[str], size: int) -> ImageFont.FreeTypeFont | None:
    for name in candidates:
        path = name if os.path.isabs(name) else str(settings.fonts_dir / name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return None


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if bold:
        return _get_font_bold(size)
    font = _load(BRAND_REGULAR, size)
    if font:
        return font
    _warn_once(
        "regular",
        f"Brand fonts not found in {settings.fonts_dir} — stories will render "
        "with a system face and will be off-brand.",
    )
    return _load(SYSTEM_FALLBACK, size) or ImageFont.load_default()


def _get_font_bold(size: int) -> ImageFont.FreeTypeFont:
    font = _load(BRAND_BOLD, size)
    if font:
        return font
    _warn_once(
        "bold",
        f"Brand bold font not found in {settings.fonts_dir} — falling back to a system face.",
    )
    return (
        _load(SYSTEM_FALLBACK_BOLD, size)
        or _load(SYSTEM_FALLBACK, size)
        or ImageFont.load_default()
    )


def _load_photo(master_name: str) -> Image.Image | None:
    import asyncio

    import httpx

    async def _fetch():
        from app.api.yclients import YClientsClient
        async with YClientsClient() as c:
            staff = await c.get_staff()
        for s in staff:
            if s.get("name") == master_name:
                avatar_url = s.get("avatar_big") or s.get("avatar")
                if avatar_url:
                    async with httpx.AsyncClient(timeout=15) as http:
                        resp = await http.get(avatar_url)
                        if resp.status_code == 200 and len(resp.content) > 100:
                            return Image.open(io.BytesIO(resp.content)).convert("RGB")
        return None

    try:
        return asyncio.run(_fetch())
    except Exception:
        return None


def _process_photo(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    bw, bh = img.size
    target_ratio = target_w / target_h
    img_ratio = bw / bh

    if img_ratio > target_ratio:
        new_h = bh
        new_w = int(bh * target_ratio)
    else:
        new_w = bw
        new_h = int(bw / target_ratio)

    left = (bw - new_w) // 2
    top = (bh - new_h) // 2
    img = img.crop((left, top, left + new_w, top + new_h))
    img = img.resize((target_w, target_h), Image.LANCZOS)

    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.05)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.08)

    return img


def generate_story(master_name: str, free_slots: list[str], target_date: date) -> str:
    os.makedirs(OUTPUT_DIR / target_date.isoformat(), exist_ok=True)

    gold = (201, 161, 90)
    cream = (239, 230, 216)
    muted = (150, 138, 121)
    white = (255, 255, 255)
    ink = (10, 10, 10)

    photo = _load_photo(master_name)

    if photo:
        photo = _process_photo(photo, 960, 1100)

    canvas = Image.new("RGB", (WIDTH, HEIGHT), ink)
    draw = ImageDraw.Draw(canvas)

    if photo:
        canvas.paste(photo, (60, 340))

    title_font = _get_font_bold(60)
    name_font = _get_font_bold(80)
    slot_font = _get_font(44)
    small_font = _get_font(30)

    # Top text
    draw.text((60, 180), "В РУБЛЪ ТЕБЯ", fill=gold, font=title_font)
    draw.text((60, 260), "СЕГОДНЯ ЖДУТ", fill=cream, font=title_font)

    # Name
    name = master_name.upper()
    bbox = draw.textbbox((0, 0), name, font=name_font)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 1480), name, fill=white, font=name_font)

    # Slots
    if free_slots:
        slots_text = "  ".join(free_slots[:6])
        bbox = draw.textbbox((0, 0), slots_text, font=slot_font)
        draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 1570), slots_text, fill=gold, font=slot_font)

    # Footer
    draw.text((60, 1710), "РУБЛЁВСКОЕ ШОССЕ, 22К2", fill=muted, font=small_font)
    draw.text((60, 1760), "n2387007.yclients.com", fill=muted, font=small_font)

    # Gold line
    for y_offset in (1470, 1680):
        draw.line([(60, y_offset), (WIDTH - 60, y_offset)], fill=gold, width=1)

    slug = master_name.lower().replace(" ", "_")
    filename = f"RUBL_{target_date.isoformat()}_{slug}.png"
    filepath = OUTPUT_DIR / target_date.isoformat() / filename
    canvas.save(filepath, "PNG", optimize=True)

    import logging
    logging.info(f"Story saved: {filepath} ({os.path.getsize(filepath)} bytes, photo={'yes' if photo else 'no'})")

    return str(filepath)


def compute_slot_hash(slots: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(slots)).encode()).hexdigest()[:12]
