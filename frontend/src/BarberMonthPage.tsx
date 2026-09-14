import { useEffect, useState } from 'react';
type Money = number | string | null;
type Day = {date: string; completed_count: number; completed_revenue: Money; product_sales: Money; commission: Money; guarantee: Money; salary: Money; forecast: Money; provisional: boolean; working: boolean | null};
type Master = {staff_id: number; name: string; completed_count: number; completed_revenue: Money; future_count: number; future_revenue: Money; product_sales: Money; earned?: Money; forecast?: Money; days?: Day[]; rule?: {guarantee: number}};
type Totals = {completed_count: number; completed_revenue: Money; future_count: number; future_revenue: Money; product_sales: Money; earned: Money; forecast: Money};
type Report = {month_start: string; month_end: string; as_of: string; updated_at: string; warnings: string[]; masters: Master[]; scope?: 'all' | 'own'; totals?: Totals};
const rub = (v: Money | undefined) => v == null ? 'Нет данных' : `${Number(v).toLocaleString('ru-RU', {maximumFractionDigits: 2})} ₽`;
const date = (v: string) => new Date(`${v}T12:00:00+03:00`).toLocaleDateString('ru-RU', {day:'numeric', month:'long', timeZone:'Europe/Moscow'});
const box = 'rounded-2xl border border-gray-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5';
export default function BarberMonthPage({payroll = false}: {payroll?: boolean}) {
  const [data, setData] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    async function load() {
      if (running) return;
      running = true; setBusy(true);
      try {
        const response = await fetch(`/api/barbers/${payroll ? 'payroll' : 'future'}`, {signal: controller.signal});
        if (!response.ok) throw new Error('Не удалось обновить данные YCLIENTS. Попробуйте ещё раз.');
        const result: Report = await response.json();
        if (!controller.signal.aborted) { setData(result); setError(''); }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Ошибка загрузки'); }
      finally {running = false; if (!controller.signal.aborted) setBusy(false);}
    }
    void load();
    const timer = window.setInterval(() => {if (!document.hidden) void load();}, 60000);
    return () => {controller.abort(); window.clearInterval(timer);};
  }, [payroll, revision]);
  return <section className="space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4"><div>
      <h1 className="text-2xl font-semibold">{payroll ? 'Расчёт ЗП' : 'Будущие записи'}</h1>
      <p className="mt-2 text-sm text-gray-500 dark:text-zinc-400">{data ? `Текущий месяц: ${date(data.month_start)} — ${date(data.month_end)}` : 'Текущий месяц · Москва'}</p>
    </div><button disabled={busy} onClick={() => setRevision(v => v + 1)} className="rounded-xl border border-gray-300 dark:border-zinc-700 px-4 py-2 disabled:opacity-50">{busy ? 'Обновление…' : 'Обновить'}</button></header>
    {error && <p role="alert" className="rounded-xl bg-red-500/10 p-4 text-red-600 dark:text-red-300">{error} {data && 'Ниже — данные последнего успешного обновления.'}</p>}
    {data?.warnings.map(w => <p key={w} role="status" className="rounded-xl bg-amber-500/10 p-4 text-amber-700 dark:text-amber-200">{w}</p>)}
    <p className="text-sm text-gray-500 dark:text-zinc-400">{payroll ? 'За день: большее из двух — 40% услуг + 10% косметики или гарант за рабочую смену. Сегодняшняя сумма предварительная. Прогноз учитывает текущие записи и опубликованные смены, но не новые записи и будущие продажи.' : 'Выполненные визиты и косметика — с начала месяца. Будущие записи — с текущего момента до конца месяца. Отмены и неявки исключены.'}</p>
    {/* Итог по всем мастерам. Приходит только тем, кому положено видеть чужие
        суммы: мастеру сервер его не отдаёт вовсе. */}
    {payroll && data?.totals && data.scope === 'all' && <div className={box}>
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">Итого по всем мастерам</h2>
      <dl className="grid grid-cols-2 gap-5 lg:grid-cols-4">
        <div><dt className="text-sm text-gray-500 dark:text-zinc-400">Начислено</dt><dd className="mt-1 text-2xl font-semibold text-rubl-accent">{rub(data.totals.earned)}</dd></div>
        <div><dt className="text-sm text-gray-500 dark:text-zinc-400">Прогноз за месяц</dt><dd className="mt-1 text-xl">{rub(data.totals.forecast)}</dd></div>
        <div><dt className="text-sm text-gray-500 dark:text-zinc-400">Выполнено записей</dt><dd className="mt-1 text-xl">{data.totals.completed_count} на {rub(data.totals.completed_revenue)}</dd></div>
        <div><dt className="text-sm text-gray-500 dark:text-zinc-400">Будущих записей</dt><dd className="mt-1 text-xl">{data.totals.future_count} на {rub(data.totals.future_revenue)}</dd></div>
      </dl>
    </div>}

    {payroll && data?.scope === 'own' && <p className="text-sm text-gray-500 dark:text-zinc-400">Показан расчёт по вам. Суммы других мастеров недоступны.</p>}

    <div className="grid gap-4 xl:grid-cols-3">{data?.masters.map(m => <article key={m.staff_id} className={box}>
      <h2 className="mb-5 text-xl font-semibold">{m.name}</h2>
      {payroll ? <dl className="space-y-5">
        <div><dt className="text-sm text-gray-500 dark:text-zinc-400">Начислено, включая сегодня*</dt><dd className="mt-1 text-2xl font-semibold text-rubl-accent">{rub(m.earned)}</dd></div>
        <div><dt className="text-sm text-gray-500 dark:text-zinc-400">Прогноз за весь месяц</dt><dd className="mt-1 text-xl">{rub(m.forecast)}</dd></div>
        <div><dt className="text-sm text-gray-500 dark:text-zinc-400">Гарант за смену</dt><dd>{rub(m.rule?.guarantee)}</dd></div>
      </dl> : <dl className="space-y-4">
        <Metric label="Выполнено записей" value={String(m.completed_count)} />
        <Metric label="Сумма выполненных" value={rub(m.completed_revenue)} />
        <Metric label="Будущих записей" value={String(m.future_count)} />
        <Metric label="Сумма будущих" value={rub(m.future_revenue)} />
        <Metric label="Продано косметики" value={rub(m.product_sales)} />
      </dl>}
    </article>)}</div>
    {payroll && data?.masters.map(m => <details key={m.staff_id} className={box}>
      <summary className="cursor-pointer font-semibold">{m.name} · расчёт по дням</summary>
      <div className="overflow-x-auto mt-4"><table className="w-full text-sm whitespace-nowrap text-right">
        <thead><tr className="text-gray-500 dark:text-zinc-400">{['День', 'Смена', 'Услуги выполнено', 'Косметика', 'Проценты', 'Гарант', 'Начислено*', 'Прогноз дня'].map(h => <th key={h} className="p-3 font-medium">{h}</th>)}</tr></thead>
        <tbody>{m.days?.map(d => <tr key={d.date} className="border-t border-gray-200 dark:border-zinc-800">
          <td className="p-3">{date(d.date)}{d.provisional ? ' *' : ''}</td><td className="p-3">{d.working == null ? 'Нет данных' : d.working ? 'Да' : d.completed_count ? 'По визитам' : '—'}</td>
          <td className="p-3">{rub(d.completed_revenue)}</td><td className="p-3">{rub(d.product_sales)}</td><td className="p-3">{rub(d.commission)}</td><td className="p-3">{rub(d.guarantee)}</td><td className="p-3 font-medium">{d.date > data.as_of.slice(0,10) ? '—' : rub(d.salary)}</td><td className="p-3">{rub(d.forecast)}</td>
        </tr>)}</tbody>
      </table></div>
    </details>)}
    {payroll && <p className="text-xs text-gray-500 dark:text-zinc-400">* Сегодняшний гарант рассчитан при условии полной смены. Суммы до удержаний и выплат. Прогноз не гарантирует получение выручки; смены, ещё не внесённые в YCLIENTS, не учтены.</p>}
    {data && <p className="text-xs text-gray-500 dark:text-zinc-400">Данные получены {new Date(data.updated_at).toLocaleString('ru-RU', {timeZone:'Europe/Moscow'})} МСК · автоматическое обновление раз в минуту</p>}
  </section>;
}
function Metric({label, value}: {label: string; value: string}) {
  return <div className="flex items-baseline justify-between gap-4"><dt className="text-sm text-gray-500 dark:text-zinc-400">{label}</dt><dd className="text-lg font-semibold whitespace-nowrap">{value}</dd></div>;
}
