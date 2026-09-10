"""Rule-based management report generation (no external API)."""

from datetime import datetime

from loguru import logger

# Нормативы для триггеров
CANCELLATION_LIMIT = 15.0
RETENTION_LIMIT = 40.0
AVG_CHECK_TARGET = 2500.0
TREND_DECLINE_LIMIT = 10.0
MASTER_SHARE_LIMIT = 30.0


def _num(value, default=0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result


def _money(value: float) -> str:
    return f"{round(value):,}".replace(",", " ")


def _parse_day(point: dict) -> datetime | None:
    raw = str(point.get("date", "")).strip()
    for layout in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw[:10], layout)
        except ValueError:
            continue
    return None


def generate_report(kpi_data: dict) -> dict:
    kpis = kpi_data.get("kpis") or {}
    trend = kpi_data.get("revenue_trend") or []
    masters = kpi_data.get("top_masters") or []
    period = kpi_data.get("period", "")

    total_revenue = _num(kpis.get("total_revenue"))
    visits = int(kpis.get("total_visits") or 0)
    avg_check = _num(kpis.get("avg_check"))
    new_clients = int(kpis.get("new_clients") or 0)
    repeat_clients = int(kpis.get("repeat_clients") or 0)
    retention = _num(kpis.get("retention_pct"))
    cancellation = _num(kpis.get("cancellation_pct"))
    ltv = _num(kpis.get("ltv"))

    if total_revenue <= 0 and visits <= 0:
        return {
            "report": "Недостаточно данных за выбранный период. "
                      "Дождитесь синхронизации YCLIENTS и повторите запрос.",
            "insights": [],
            "risks": [],
            "opportunities": [],
            "actions_tomorrow": [],
        }

    insights: list[str] = []
    risks: list[str] = []
    opportunities: list[str] = []
    actions: list[str] = []

    # ── Выручка и посещаемость ──────────────────────────────────────────
    insights.append(
        f"Выручка за период: {_money(total_revenue)} ₽ при {visits} визитах, "
        f"средний чек {_money(avg_check)} ₽."
    )

    # ── Динамика выручки по тренду ──────────────────────────────────────
    days = []
    for point in trend:
        revenue = _num(point.get("revenue"))
        day = _parse_day(point)
        if day is not None:
            days.append((day, revenue))
    days.sort(key=lambda item: item[0])

    if len(days) >= 6:
        half = len(days) // 2
        first = sum(rev for _, rev in days[:half])
        second = sum(rev for _, rev in days[half:])
        if first > 0:
            change = (second - first) / first * 100
            direction = "выросла" if change >= 0 else "снизилась"
            insights.append(
                f"Динамика: во второй половине периода выручка {direction} "
                f"на {abs(change):.0f}% относительно первой."
            )
            if change < -TREND_DECLINE_LIMIT:
                risks.append(
                    f"Выручка снижается: падение {abs(change):.0f}% во второй "
                    "половине периода. Причину стоит искать в загрузке "
                    "мастеров или оттоке клиентов."
                )
        if days:
            best = max(days, key=lambda item: item[1])
            insights.append(
                f"Лучший день — {best[0].strftime('%d.%m')}: "
                f"{_money(best[1])} ₽."
            )

    # ── Клиентская база ─────────────────────────────────────────────────
    if new_clients or repeat_clients:
        insights.append(
            f"Клиенты: {new_clients} новых, {repeat_clients} повторных, "
            f"возвращаемость {retention:.1f}%."
        )
        if retention > 0 and retention < RETENTION_LIMIT and visits >= 10:
            risks.append(
                f"Возвращаемость {retention:.1f}% — ниже нормы "
                f"{RETENTION_LIMIT:.0f}%: база не удерживается, выручка держится "
                "на новых клиентах."
            )
        elif retention >= 50:
            opportunities.append(
                f"Возвращаемость {retention:.1f}% — сильная база. Выгодно "
                "предложить постоянникам комплексы и абонементы."
            )

    # ── Отмены и неявки ─────────────────────────────────────────────────
    if cancellation > CANCELLATION_LIMIT:
        lost_visits = round(visits * cancellation / 100)
        lost = lost_visits * avg_check
        risks.append(
            f"Отмены и неявки — {cancellation:.1f}% (норма до "
            f"{CANCELLATION_LIMIT:.0f}%). При среднем чеке {_money(avg_check)} ₽ "
            f"это около {_money(lost)} ₽ упущенной выручки."
        )
        actions.append(
            "Завтра с 11:00 обзвонить всех записанных на день и подтвердить "
            "явку — это снижает неявки в 1,5–2 раза."
        )

    # ── Мастера ─────────────────────────────────────────────────────────
    if masters:
        total_masters_revenue = sum(_num(m.get("revenue")) for m in masters)
        best = masters[0]
        best_share = (
            _num(best.get("revenue")) / total_masters_revenue * 100
            if total_masters_revenue > 0 else 0.0
        )
        if best_share >= MASTER_SHARE_LIMIT:
            opportunities.append(
                f"{best.get('name')} даёт {best_share:.0f}% выручки "
                f"({_money(_num(best.get('revenue')))} ₽). Стоит расширить "
                "его смены или повысить цену."
            )
        weakest = min(masters, key=lambda m: _num(m.get("revenue")))
        if len(masters) >= 2 and _num(weakest.get("revenue")) < _num(best.get("revenue")) * 0.3:
            risks.append(
                f"У {weakest.get('name')} наименьшая выручка "
                f"({_money(_num(weakest.get('revenue')))} ₽) — загрузка низкая, "
                "пересмотрите его расписание или прокачайте запись к нему."
            )

    # ── Средний чек ─────────────────────────────────────────────────────
    if avg_check > 0 and avg_check < AVG_CHECK_TARGET and visits > 0:
        opportunities.append(
            f"Средний чек {_money(avg_check)} ₽ — ниже целевых "
            f"{_money(AVG_CHECK_TARGET)} ₽. Потенциал в допродаже комплексов "
            "и уходов к стрижке."
        )
        actions.append(
            "Дать мастерам скрипт допродажи: после стрижки предлагать "
            "бороду, камуфляж или SPA-уход."
        )

    if ltv > 0:
        opportunities.append(
            f"LTV клиента — {_money(ltv)} ₽. Каждый новый клиент окупает "
            "вложения в рекламу; стоит масштабировать привлечение."
        )

    # ── Действия на завтра ──────────────────────────────────────────────
    actions.append("Проверить свободные окна в записи на ближайшие 3 дня и "
                   "заполнить их повторными клиентами.")
    if retention > 0 and retention < RETENTION_LIMIT:
        actions.append(
            "Сделать выборку клиентов без визита 30+ дней и запустить по ним "
            "персональную рассылку в MAX."
        )
    actions.append("Сверить выручку дня с планом и отметить отклонения в журнале.")
    actions = actions[:4]

    # ── Развёрнутый отчёт ───────────────────────────────────────────────
    paragraphs = [
        f"Отчётный период: {period}." if period else "Отчёт за выбранный период.",
    ]
    if insights:
        paragraphs.append(insights[0])
    trend_line = next((line for line in insights if line.startswith("Динамика")), "")
    if trend_line:
        paragraphs.append(trend_line)
    remaining = [line for line in insights if not line.startswith("Динамика")]
    if len(remaining) > 1:
        paragraphs.append("Главные выводы: " + " ".join(remaining[1:]))
    if risks:
        paragraphs.append("Риски: " + " ".join(risks))
    if opportunities:
        paragraphs.append("Возможности: " + " ".join(opportunities))
    if actions:
        paragraphs.append("Действия на завтра: " + " ".join(actions))

    report = "\n\n".join(paragraphs).strip()

    logger.info("Report generated from internal analytics (no external API)")
    return {
        "report": report,
        "insights": insights[:3],
        "risks": risks[:3],
        "opportunities": opportunities[:3],
        "actions_tomorrow": actions[:4],
    }
