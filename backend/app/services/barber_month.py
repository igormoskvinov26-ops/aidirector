"""Read-only current-month barber statistics. No writes to CRM or payroll."""
import asyncio
import calendar
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.api.yclients import YClientsClient
from app.config import settings
from app.services.cache import cached

MOSCOW = ZoneInfo('Europe/Moscow')


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=MOSCOW) if dt.tzinfo is None else dt.astimezone(MOSCOW)


def period(now):
    now = now.astimezone(MOSCOW)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(day=calendar.monthrange(now.year, now.month)[1]) + timedelta(days=1)
    return start, end


def visit_attendance(record):
    """Код посещения из записи YCLIENTS.

    Поле называется visit_attendance — так его читают синхронизация, сводка
    операций и дашборд, то есть весь остальной код, работающий с тем же
    эндпоинтом /records/. Ранее здесь стояло record['attendance']; при таком
    имени поле всегда оказывалось пустым, код посещения получался нулевым, и
    выполненные визиты не попадали никуда: в выполненные их не пускало
    условие attendance == 1, в будущие — уже прошедшее время.

    Короткое имя оставлено запасным вариантом: если YCLIENTS отдаёт его в
    каком-то из ответов, поведение не изменится.
    """
    for key in ("visit_attendance", "attendance"):
        value = record.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def amount(record):
    total = Decimal(0)
    for service in record.get('services') or []:
        value = next((service[k] for k in ('cost_to_pay', 'cost', 'first_cost')
                      if service.get(k) is not None), 0)
        total += money(value)  # YCLIENTS cost is the total line cost, not a unit price.
    return total


async def pages(client, path, start, end):
    result, seen = [], set()
    for page in range(1, 201):
        raw = await client._get(path, {'start_date': start, 'end_date': end,
                                       'count': 200, 'page': page})
        data = raw.get('data') if isinstance(raw, dict) else raw
        if not isinstance(data, list) or (isinstance(raw, dict) and raw.get('success') is False):
            raise ValueError('Некорректный ответ YCLIENTS')
        if not data:
            return result
        new = [row for row in data if row.get('id') not in seen]
        if not new:
            raise ValueError('YCLIENTS повторяет страницу: выгрузка неполная')
        seen.update(row.get('id') for row in new)
        result.extend(new)
        total = (raw.get('meta') or {}).get('total_count') if isinstance(raw, dict) else None
        if total is not None and len(result) >= int(total):
            return result
        await asyncio.sleep(0.15)
    raise ValueError('Превышен предел выгрузки: данные неполные')


async def load_products(client, start, end):
    transactions = await pages(client, f'/transactions/{client.company_id}', start, end)
    grouped = {}
    for row in transactions:
        if row.get('sold_item_type') != 'goods_transaction' or row.get('deleted'):
            continue
        ident = int(row.get('sold_item_id') or 0)
        if ident:
            # Keep signed corrections; do not count split payments as separate sales.
            item = grouped.setdefault(ident, {'amount': Decimal(0), 'date': row.get('date')})
            item['amount'] += money(row.get('amount'))
    sales = []
    for ident, payment in grouped.items():
        path = f'/storage_operations/goods_transactions/{client.company_id}/{ident}'
        raw = await client._get(path)
        detail = raw.get('data')
        if not isinstance(detail, dict):
            raise ValueError('Не получены детали продажи косметики')
        if detail.get('deleted') or int(detail.get('type_id') or 0) != 1:
            continue
        seller = detail.get('master_id') or (detail.get('master') or {}).get('id') or 0
        sales.append({'staff_id': int(seller),
                      'date': str(detail.get('create_date') or payment['date'])[:10],
                      'amount': payment['amount']})
        await asyncio.sleep(0.15)
    return sales


async def source(now):
    start, end = period(now)
    first, last = start.date().isoformat(), (end - timedelta(days=1)).date().isoformat()

    async def load():
        async with YClientsClient() as client:
            records = await pages(client, f'/records/{client.company_id}', first, last)
            warnings = []
            try:
                raw = await client._get(f'/company/{client.company_id}/staff/schedule',
                                        {'start_date': first, 'end_date': last})
                schedule = raw.get('data')
                if not isinstance(schedule, list):
                    raise ValueError('Invalid schedule')
            except Exception:
                schedule = None
                warnings.append('График YCLIENTS недоступен: зарплата с гарантом не рассчитана.')
            try:
                products = await load_products(client, first, last)
            except Exception:
                products = None
                warnings.append('Продажи косметики недоступны: полная зарплата не рассчитана.')
            try:
                staff = await client.get_active_staff()
            except Exception:
                staff = None
                warnings.append(
                    'Список сотрудников недоступен: продажи администраторов не показаны.'
                )
            return records, schedule, products, staff, warnings, datetime.now(MOSCOW).isoformat()

    return await cached(f'barber-month:{settings.yclients_company_id}:{first}', load, ttl=60)


def calculate(records, schedule, products, now, rules):
    start, end = period(now)
    now = now.astimezone(MOSCOW)
    masters = []
    for rule in rules:
        ident = int(rule['staff_id'])
        days = {}
        day = start.date()
        while day < end.date():
            key = day.isoformat()
            days[key] = {'date': key, 'completed_count': 0, 'completed_revenue': Decimal(0),
                         'future_count': 0, 'future_revenue': Decimal(0),
                         'product_sales': Decimal(0) if products is not None else None,
                         'working': None if schedule is None else False}
            day += timedelta(days=1)
        if schedule is not None:
            for row in schedule:
                key = str(row.get('date', ''))[:10]
                if int(row.get('staff_id') or row.get('staffId') or 0) == ident and key in days:
                    days[key]['working'] = days[key]['working'] or bool(row.get('slots'))
        seen = set()
        for record in records:
            if record.get('id') in seen:
                continue
            seen.add(record.get('id'))
            record_staff = record.get('staff_id') or (record.get('staff') or {}).get('id') or 0
            if record.get('deleted') or int(record_staff) != ident:
                continue
            dt = timestamp(record.get('datetime') or record.get('date'))
            if not start <= dt < end:
                continue
            attendance = visit_attendance(record)
            key = dt.date().isoformat()
            if dt <= now and attendance == 1:
                days[key]['completed_count'] += 1
                days[key]['completed_revenue'] += amount(record)
            elif dt > now and attendance in (0, 2):
                days[key]['future_count'] += 1
                days[key]['future_revenue'] += amount(record)
        today_iso = now.date().isoformat()
        for sale in products or []:
            same_master = sale['staff_id'] == ident
            in_period = sale['date'] in days and sale['date'] <= today_iso
            if same_master and in_period:
                days[sale['date']]['product_sales'] += money(sale['amount'])

        guarantee = money(rule['guarantee'])
        service_rate = Decimal(str(rule['service_rate']))
        product_rate = Decimal(str(rule['product_rate']))
        complete = schedule is not None and products is not None

        for row in days.values():
            row['commission'] = money(
                row['completed_revenue'] * service_rate
                + (row['product_sales'] or 0) * product_rate
            )
            # Выполненный визит доказывает отработанную смену, даже если
            # опубликованный график потом убрали.
            worked = bool(row['working'] or row['completed_count'])
            floor = guarantee if worked else Decimal(0)
            row['guarantee'] = floor if schedule is not None else None
            past_or_today = row['date'] <= today_iso
            row['salary'] = (
                max(row['commission'], floor) if complete and past_or_today else None
            )
            row['forecast'] = (
                max(row['commission'] + money(row['future_revenue'] * service_rate), floor)
                if complete
                else None
            )
            row['provisional'] = row['date'] >= today_iso

        # days передаётся аргументом, а не захватывается: замыкание внутри цикла
        # смотрело бы на переменную, которая к моменту вызова уже другая.
        def total(key, rows=days):
            return sum((r[key] or 0 for r in rows.values()), Decimal(0))
        counted = ('completed_count', 'completed_revenue', 'future_count', 'future_revenue')
        masters.append({'staff_id': ident, 'name': rule['name'], 'rule': rule,
                        **{key: total(key) for key in counted},
                        'product_sales': total('product_sales') if products is not None else None,
                        'earned': total('salary') if complete else None,
                        'forecast': total('forecast') if complete else None,
                        'days': list(days.values())})
    last_day = (end - timedelta(days=1)).date().isoformat()
    return {'month_start': start.date().isoformat(), 'month_end': last_day,
            'as_of': now.isoformat(), 'masters': masters}


def calculate_admin_sales(records, products, now, admin_staff):
    """Деньги, которые прошли не через трёх зарегистрированных барберов.

    Владелец нашёл в отчёте YCLIENTS реальную продажу товара администратором
    (Виктор, 1300 ₽) — её нет ни в одной строке дашборда «Записи за месяц»,
    потому что calculate() выше смотрит только на settings.barber_payroll_rules.
    Это не баг того дашборда: он про мастеров и их зарплату, администраторам
    зарплата так не считается. Но выручка салона — их продажи тоже, и прятать
    эти деньги молча нельзя.

    Отдельная, простая сводка: без графика, гаранта и прогноза — только то,
    что реально прошло. admin_staff — активные сотрудники не из rules
    (get_active_staff уже убрал скрытых, увольненных и «Лист Ожидания»).
    """
    admin_ids = {int(s['id']) for s in (admin_staff or []) if s.get('id') is not None}
    if not admin_ids:
        return {'masters': [], 'totals': {
            'completed_count': 0, 'completed_revenue': 0.0,
            'product_sales': None if products is None else 0.0,
        }}

    start, end = period(now)
    now = now.astimezone(MOSCOW)
    today_iso = now.date().isoformat()

    by_id: dict[int, dict] = {}
    seen = set()
    for record in records:
        if record.get('id') in seen:
            continue
        seen.add(record.get('id'))
        record_staff = int(record.get('staff_id') or (record.get('staff') or {}).get('id') or 0)
        if record.get('deleted') or record_staff not in admin_ids:
            continue
        dt = timestamp(record.get('datetime') or record.get('date'))
        if not start <= dt < end or dt > now or visit_attendance(record) != 1:
            continue
        row = by_id.setdefault(record_staff, {
            'completed_count': 0, 'completed_revenue': Decimal(0),
            'product_sales': Decimal(0) if products is not None else None,
        })
        row['completed_count'] += 1
        row['completed_revenue'] += amount(record)

    if products is not None:
        for sale in products:
            seller = int(sale.get('staff_id') or 0)
            if seller not in admin_ids or sale['date'] > today_iso:
                continue
            row = by_id.setdefault(seller, {
                'completed_count': 0, 'completed_revenue': Decimal(0),
                'product_sales': Decimal(0),
            })
            row['product_sales'] += money(sale['amount'])

    names = {int(s['id']): s.get('name') for s in admin_staff if s.get('id') is not None}
    rows = []
    for ident, agg in by_id.items():
        product_sales = agg['product_sales']
        rows.append({
            'staff_id': ident,
            'name': names.get(ident) or f'#{ident}',
            'completed_count': agg['completed_count'],
            'completed_revenue': float(agg['completed_revenue']),
            'product_sales': None if product_sales is None else float(product_sales),
        })
    rows.sort(key=lambda r: -(r['completed_revenue'] + (r['product_sales'] or 0)))

    totals = {
        'completed_count': sum(r['completed_count'] for r in rows),
        'completed_revenue': sum(r['completed_revenue'] for r in rows),
        'product_sales': None if products is None else sum(r['product_sales'] or 0 for r in rows),
    }
    return {'masters': rows, 'totals': totals}


async def report():
    now = datetime.now(MOSCOW)
    records, schedule, products, staff, warnings, updated = await source(now)
    result = calculate(records, schedule, products, now, settings.barber_payroll_rules)

    barber_ids = {int(r['staff_id']) for r in settings.barber_payroll_rules}
    admin_staff = [s for s in (staff or []) if int(s.get('id') or 0) not in barber_ids]
    result['admin_sales'] = calculate_admin_sales(records, products, now, admin_staff)

    result.update(warnings=warnings, updated_at=updated)
    return result
