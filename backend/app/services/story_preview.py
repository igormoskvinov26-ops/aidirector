"""Story preview — HTML template renderer for browser-based composition."""

from datetime import date


def render_story_html(master_name: str, free_slots: list[str], photo_url: str, target_date: date) -> str:
    date_formatted = target_date.strftime("%d.%m.%Y")
    slots_html = ""
    for slot in free_slots[:8]:
        slots_html += f'<div class="slot">{slot}</div>'

    photo_bg = ""
    if photo_url:
        photo_bg = f"""
  <div class="photo-bg" style="background-image:url('{photo_url}')"></div>
  <div class="photo-overlay"></div>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1080, initial-scale=1">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  width: 1080px; height: 1920px; overflow: hidden;
  font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
  background: #0a0a0a;
  color: #efe6d8;
}}
.story {{
  width: 1080px; height: 1920px; position: relative; overflow: hidden;
}}
.photo-bg {{
  position: absolute; inset: 0;
  background-size: cover;
  background-position: center 10%;
  filter: brightness(0.8) contrast(1.05);
}}
.photo-overlay {{
  position: absolute; inset: 0;
  background: linear-gradient(
    180deg,
    rgba(10,10,10,0.55) 0%,
    rgba(10,10,10,0.08) 28%,
    rgba(10,10,10,0.08) 48%,
    rgba(10,10,10,0.78) 72%,
    rgba(10,10,10,0.94) 100%
  );
}}
.gold-line {{
  position: absolute; left: 80px; right: 80px; height: 1px;
  background: linear-gradient(90deg, transparent, #c9a15a 20%, #c9a15a 80%, transparent);
}}
.badge {{
  position: absolute; top: 120px; left: 80px;
  font-size: 18px; font-weight: 700; letter-spacing: 0.25em;
  text-transform: uppercase; color: #c9a15a;
}}
.headline {{
  position: absolute; top: 170px; left: 80px; right: 80px;
  font-size: 88px; font-weight: 800; line-height: 1.02;
  color: #efe6d8; letter-spacing: -0.02em;
}}
.headline .accent {{ color: #c9a15a; }}
.master-name {{
  position: absolute; bottom: 540px; left: 80px;
  font-size: 56px; font-weight: 700;
  color: #fff; letter-spacing: 0.04em;
}}
.slots-container {{
  position: absolute; bottom: 350px; left: 80px; right: 80px;
  display: flex; gap: 20px; flex-wrap: wrap;
}}
.slot {{
  padding: 18px 36px;
  border: 2px solid #c9a15a;
  color: #c9a15a;
  font-size: 36px; font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.06em;
}}
.slogan {{
  position: absolute; bottom: 220px; left: 80px;
  font-size: 20px; font-weight: 500; letter-spacing: 0.15em;
  text-transform: uppercase; color: #968a79;
}}
.footer {{
  position: absolute; bottom: 80px; left: 80px; right: 80px;
  display: flex; justify-content: space-between; align-items: flex-end;
}}
.footer-left {{
  font-size: 18px; color: #968a79; line-height: 1.6;
}}
.footer-left .addr {{ font-size: 16px; }}
.footer-right {{
  font-size: 16px; color: #c9a15a; letter-spacing: 0.1em;
  border: 1px solid #c9a15a; padding: 14px 36px;
}}
.brand-mark {{
  position: absolute; top: 120px; right: 80px;
  font-size: 20px; font-weight: 700; color: #c9a15a;
  letter-spacing: 0.2em;
}}
</style>
</head>
<body>
<div class="story">
  {photo_bg}

  <div class="brand-mark">РУБЛЪ</div>
  <div class="badge">{date_formatted}</div>

  <div class="headline">
    <span class="accent">В РУБЛЪ</span><br>
    ТЕБЯ СЕГОДНЯ<br>
    ЖДУТ
  </div>

  <div class="gold-line" style="bottom:640px;"></div>

  <div class="master-name">{master_name.upper()}</div>

  <div class="slots-container">{slots_html}</div>

  <div class="slogan">НАМ ДОВЕРЯЮТ СВОИ ГОЛОВЫ</div>

  <div class="gold-line" style="bottom:160px;"></div>

  <div class="footer">
    <div class="footer-left">
      РУБЛЁВСКОЕ ШОССЕ, 22К2<br>
      <span class="addr">n2387007.yclients.com</span>
    </div>
    <div class="footer-right">ЗАПИСАТЬСЯ →</div>
  </div>
</div>
</body>
</html>"""
