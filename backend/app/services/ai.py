"""AI-powered management report generation using DeepSeek."""

import json

import httpx
from loguru import logger

from app.config import settings

SYSTEM_PROMPT = """Ты — AI-директор барбершопа «РублЪ». Ты анализируешь бизнес-метрики и даёшь управленческие рекомендации.

Твой стиль: прямой, конкретный, на основе цифр. Никакой воды.

Ты получаешь JSON с KPI за период и должен вернуть СТРОГО JSON такого формата:
{
  "insights": ["главный вывод 1", "главный вывод 2", "главный вывод 3"],
  "risks": ["риск 1 с конкретной цифрой", "риск 2"],
  "opportunities": ["возможность 1", "возможность 2"],
  "actions_tomorrow": ["конкретное действие на завтра 1", "конкретное действие 2", "конкретное действие 3"],
  "report": "развёрнутый управленческий отчёт на 3-5 абзацев. Включи анализ: главные выводы, какие мастера просели, какие показатели растут, почему изменился средний чек, какие клиенты скоро потеряются, что сделать."
}

Правила:
1. Только JSON в ответе, без markdown-блоков.
2. Каждый пункт — 1-2 предложения, с цифрами.
3. Если данных мало — честно скажи об этом.
4. Действия на завтра должны быть конкретными: кому позвонить, что проверить, что изменить.
"""


MAX_REVENUE_TREND_DAYS = 90
MAX_PROMPT_CHARS = 55_000


def _prepare_kpi_data(kpi_data: dict) -> tuple[dict, bool]:
    data = {**kpi_data}
    truncated = False
    trend = data.get("revenue_trend", [])
    if isinstance(trend, list) and len(trend) > MAX_REVENUE_TREND_DAYS:
        data["revenue_trend"] = trend[-MAX_REVENUE_TREND_DAYS:]
        data["_trend_truncated"] = True
        data["_original_days"] = len(trend)
        truncated = True
    return data, truncated


def _serialize_kpi_data(data: dict) -> str:
    json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(json_str) > MAX_PROMPT_CHARS:
        json_str = json_str[:MAX_PROMPT_CHARS] + "..."
    return json_str


async def generate_report(kpi_data: dict) -> dict:
    if not settings.deepseek_api_key:
        return {
            "report": "AI-сервис не настроен. Укажите DEEPSEEK_API_KEY в .env",
            "insights": [],
            "risks": [],
            "opportunities": [],
            "actions_tomorrow": [],
        }

    prepared_data, truncated = _prepare_kpi_data(kpi_data)
    user_content = f"Проанализируй метрики барбершопа:\n\n{_serialize_kpi_data(prepared_data)}"
    if truncated:
        user_content += "\n\n(Данные по дням обрезаны до последних 90 дней во избежание превышения лимита контекста.)"

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{settings.deepseek_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 2000,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]

            result = json.loads(content)
            logger.info("AI report generated successfully")
            return result

        except Exception as e:
            logger.error(f"AI report generation failed: {e}")
            return {
                "report": f"Не удалось сгенерировать отчёт: {e}",
                "insights": [],
                "risks": [],
                "opportunities": [],
                "actions_tomorrow": [],
            }
