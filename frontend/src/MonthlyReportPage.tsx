import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, RefreshCw, X } from "lucide-react";

// ── Типы ответа /api/monthly-report ────────────────────────────────────────

type Num = number | null;

interface Мастер {
  staff_id: number;
  name: string;
  revenue: Num;
  visits: number;
  avg_check: Num;
  avg_check_prev: Num;
  avg_check_delta: Num;
  extra_services: {
    configured: boolean;
    count: Num;
    norm: number;
    pct: Num;
    met: boolean | null;
  };
  hours: Num;
  hours_note: string | null;
  hour_cost: Num;
  hour_cost_prev: Num;
  hour_cost_delta: Num;
  product_sales: Num;
  sales_ratio_pct: Num;
  sales_norm_pct: number;
  sales_met: boolean | null;
  sales_missing: Num;
  return_rate_pct: Num;
}

interface Звонки {
  total: number;
  booked_clicks: number;
  confirmed: number;
  not_confirmed: number;
  pending: number;
  error: number;
  no_booking: number;
  no_answer: number;
  discrepancies: number;
  button_accuracy_pct: Num;
  conv_contacts_pct: Num;
  conv_all_pct: Num;
}

interface Администратор {
  key: string;
  staff_id: number | null;
  name: string;
  made: { count: number; sum: Num } | null;
  closed: { count: number; sum: Num } | null;
  avg_check: Num;
  avg_check_prev: Num;
  avg_check_delta: Num;
  calls: Звонки;
}

interface Отчёт {
  month: string;
  state: "preliminary" | "final";
  label: string;
  generated_at: string;
  finalized_at: string | null;
  last_sync_at?: string | null;
  masters: Мастер[];
  admins: Администратор[];
  warnings: string[];
  admin_records_available?: boolean;
  from_snapshot?: boolean;
  snapshot_saved?: boolean;
}

interface СтрокаДетали {
  [ключ: string]: string | number | boolean | null;
}

// ── Форматирование ────────────────────────────────────────────────────────

const КАРТОЧКА =
  "rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5";
const НЕТ = "—";

const руб = (v: Num | undefined) =>
  v == null ? НЕТ : `${v.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`;
const проц = (v: Num | undefined) =>
  v == null ? НЕТ : `${v.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
const время = (v: string | null | undefined) =>
  v
    ? new Date(v).toLocaleString("ru-RU", {
        timeZone: "Europe/Moscow",
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "нет данных";

function текущийМесяц(): string {
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Moscow" }));
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function Дельта({ v }: { v: Num }) {
  if (v == null) return <span className="text-muted-light dark:text-muted">{НЕТ}</span>;
  const вверх = v >= 0;
  return (
    <span className={вверх ? "text-profit" : "text-loss"}>
      {вверх ? "↑" : "↓"} {Math.abs(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%
    </span>
  );
}

function Норма({ ok, настроено = true }: { ok: boolean | null; настроено?: boolean }) {
  if (!настроено) return <span className="text-xs text-caution">не настроено</span>;
  if (ok == null) return <span className="text-muted-light dark:text-muted">{НЕТ}</span>;
  return ok ? (
    <span className="inline-flex items-center gap-1 text-profit">
      <Check size={14} /> норма
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-loss">
      <X size={14} /> ниже нормы
    </span>
  );
}

function Строка({
  название,
  children,
  onClick,
}: {
  название: string;
  children: React.ReactNode;
  onClick?: () => void;
}) {
  const содержимое = (
    <>
      <dt className="text-sm text-muted-light dark:text-muted">{название}</dt>
      <dd className="text-right">{children}</dd>
    </>
  );
  return onClick ? (
    <button
      onClick={onClick}
      className="w-full flex items-baseline justify-between gap-4 text-left hover:bg-milk-deep dark:hover:bg-panel-deep/60 rounded-lg px-2 -mx-2 py-1 transition-colors"
      title="Показать, из чего сложено"
    >
      {содержимое}
    </button>
  ) : (
    <div className="flex items-baseline justify-between gap-4 px-2 -mx-2 py-1">{содержимое}</div>
  );
}

// ── Страница ──────────────────────────────────────────────────────────────

export default function MonthlyReportPage() {
  const [месяц, setМесяц] = useState(текущийМесяц());
  const [вкладка, setВкладка] = useState<"masters" | "admins">("masters");
  const [отчёт, setОтчёт] = useState<Отчёт | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [грузим, setГрузим] = useState(false);
  const [детали, setДетали] = useState<{
    заголовок: string;
    вид: string;
    ключ: string;
  } | null>(null);

  const загрузить = useCallback(
    async (обновить: boolean) => {
      if (!месяц) return;
      setГрузим(true);
      setОшибка(null);
      try {
        const r = await fetch(
          `/api/monthly-report?month=${месяц}${обновить ? "&refresh=true" : ""}`,
        );
        if (!r.ok) {
          const тело = await r.json().catch(() => ({}));
          setОшибка(тело.detail || "Отчёт не построен");
          return;
        }
        setОтчёт(await r.json());
      } catch {
        setОшибка("Сервер не отвечает");
      } finally {
        setГрузим(false);
      }
    },
    [месяц],
  );

  useEffect(() => {
    setОтчёт(null);
    void загрузить(false);
  }, [загрузить]);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink-soft dark:text-cream">Месячный отчёт</h1>
          <p className="mt-1 text-sm text-muted-light dark:text-muted">
            Мастера и администраторы за календарный месяц · Москва
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-muted-light dark:text-muted">
            Месяц{" "}
            <input
              type="month"
              value={месяц}
              max={текущийМесяц()}
              onChange={(e) => e.target.value && setМесяц(e.target.value)}
              className="ml-1 rounded-xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-3 py-2 text-ink-soft dark:text-cream"
            />
          </label>
          <button
            disabled={грузим}
            onClick={() => void загрузить(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-milk-line dark:border-line px-4 py-2 disabled:opacity-50"
          >
            <RefreshCw size={14} className={грузим ? "animate-spin" : ""} />
            {грузим ? "Обновление…" : "Обновить данные"}
          </button>
        </div>
      </header>

      {отчёт && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-light dark:text-muted">
          <span
            className={`rounded-full px-3 py-1 font-medium ${
              отчёт.state === "final"
                ? "bg-profit/10 text-profit"
                : "bg-caution/10 text-caution"
            }`}
          >
            {отчёт.label}
          </span>
          <span>Данные YCLIENTS получены: {время(отчёт.generated_at)} МСК</span>
          <span>Последняя синхронизация базы: {время(отчёт.last_sync_at)} МСК</span>
          {отчёт.from_snapshot && <span>Сохранённый итог месяца</span>}
        </div>
      )}

      {ошибка && (
        <p role="alert" className="rounded-xl bg-loss/10 p-4 text-loss">
          {ошибка}
        </p>
      )}
      {отчёт?.warnings.map((w) => (
        <p
          key={w}
          role="status"
          className="flex items-start gap-2 rounded-xl bg-caution/10 p-4 text-sm text-caution"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          {w}
        </p>
      ))}

      <div className="flex gap-2">
        {(
          [
            ["masters", "Мастера"],
            ["admins", "Администраторы"],
          ] as const
        ).map(([id, подпись]) => (
          <button
            key={id}
            onClick={() => setВкладка(id)}
            className={`rounded-xl px-4 py-2 text-sm transition-colors ${
              вкладка === id
                ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream font-medium"
                : "text-muted-light dark:text-muted hover:bg-milk-deep dark:hover:bg-panel"
            }`}
          >
            {подпись}
          </button>
        ))}
      </div>

      {грузим && !отчёт && (
        <div className="flex items-center gap-2 text-sm text-muted-light dark:text-muted">
          <Loader2 size={16} className="animate-spin" /> Считаю отчёт по данным YCLIENTS…
        </div>
      )}

      {отчёт && вкладка === "masters" && (
        <div className="grid gap-4 xl:grid-cols-3">
          {отчёт.masters.map((м) => (
            <КарточкаМастера
              key={м.staff_id}
              м={м}
              onДопуслуги={() =>
                setДетали({
                  заголовок: `${м.name}: дополнительные услуги`,
                  вид: "extra_services",
                  ключ: String(м.staff_id),
                })
              }
              onВизиты={() =>
                setДетали({
                  заголовок: `${м.name}: выполненные визиты`,
                  вид: "visits",
                  ключ: String(м.staff_id),
                })
              }
            />
          ))}
        </div>
      )}

      {отчёт && вкладка === "admins" && (
        <div className="grid gap-4 xl:grid-cols-2">
          {отчёт.admins.length === 0 && (
            <div className={КАРТОЧКА + " text-sm text-muted-light dark:text-muted"}>
              Нет данных по администраторам: список не задан в «Настройки → Месячный отчёт»
              или за месяц не было звонков.
            </div>
          )}
          {отчёт.admins.map((а) => (
            <КарточкаАдмина
              key={а.key}
              а={а}
              onДетали={(вид, подпись) =>
                setДетали({ заголовок: `${а.name}: ${подпись}`, вид, ключ: а.key })
              }
            />
          ))}
        </div>
      )}

      {детали && <Детали месяц={месяц} {...детали} onЗакрыть={() => setДетали(null)} />}
    </section>
  );
}

// ── Карточки ──────────────────────────────────────────────────────────────

function КарточкаМастера({
  м,
  onДопуслуги,
  onВизиты,
}: {
  м: Мастер;
  onДопуслуги: () => void;
  onВизиты: () => void;
}) {
  const д = м.extra_services;
  return (
    <article className={КАРТОЧКА}>
      <h2 className="text-xl font-semibold uppercase tracking-wide">{м.name}</h2>
      <p className="mt-3 text-3xl font-semibold text-bronze dark:text-gold">{руб(м.revenue)}</p>
      <p className="text-xs text-muted-light dark:text-muted">выполнено услуг</p>
      <dl className="mt-4 space-y-1">
        <Строка название="Визитов" onClick={onВизиты}>
          {м.visits}
        </Строка>
        <Строка название="Средний чек">
          <span className="font-semibold">{руб(м.avg_check)}</span>{" "}
          <Дельта v={м.avg_check_delta} />
        </Строка>
        <Строка название="Доп. услуги" onClick={д.configured ? onДопуслуги : undefined}>
          {д.configured ? (
            <>
              <span className="font-semibold">
                {д.count} / {д.norm}
              </span>{" "}
              <span className="text-xs text-muted-light dark:text-muted">{проц(д.pct)}</span>{" "}
              <Норма ok={д.met} />
            </>
          ) : (
            <Норма ok={null} настроено={false} />
          )}
        </Строка>
        <Строка название="Стоимость часа">
          {м.hour_cost == null ? (
            <span title={м.hours_note ?? ""} className="text-muted-light dark:text-muted">
              нет данных
            </span>
          ) : (
            <>
              <span className="font-semibold">{руб(м.hour_cost)}/ч</span>{" "}
              <Дельта v={м.hour_cost_delta} />
            </>
          )}
        </Строка>
        <Строка название="Продажи">
          <span className="font-semibold">{м.product_sales == null ? "нет данных" : руб(м.product_sales)}</span>
        </Строка>
        <Строка название={`Продажи / услуги (норма ≥ ${м.sales_norm_pct}%)`}>
          <span className="font-semibold">{проц(м.sales_ratio_pct)}</span> <Норма ok={м.sales_met} />
          {м.sales_met === false && м.sales_missing != null && (
            <div className="text-xs text-muted-light dark:text-muted">
              не хватает {руб(м.sales_missing)}
            </div>
          )}
        </Строка>
        <Строка название="Возвратность">
          <span className="font-semibold">{проц(м.return_rate_pct)}</span>
        </Строка>
      </dl>
    </article>
  );
}

function КарточкаАдмина({
  а,
  onДетали,
}: {
  а: Администратор;
  onДетали: (вид: string, подпись: string) => void;
}) {
  const з = а.calls;
  return (
    <article className={КАРТОЧКА}>
      <h2 className="text-xl font-semibold uppercase tracking-wide">{а.name}</h2>
      <dl className="mt-4 space-y-1">
        <Строка название="Сделано записей" onClick={а.made ? () => onДетали("made", "созданные записи") : undefined}>
          {а.made ? (
            <span className="font-semibold">
              {а.made.count} шт. · {руб(а.made.sum)}
            </span>
          ) : (
            <span className="text-muted-light dark:text-muted">нет данных</span>
          )}
        </Строка>
        <Строка название="Закрыто записей" onClick={а.closed ? () => onДетали("closed", "закрытые записи") : undefined}>
          {а.closed ? (
            <span className="font-semibold">
              {а.closed.count} шт. · {руб(а.closed.sum)}
            </span>
          ) : (
            <span className="text-muted-light dark:text-muted">нет данных</span>
          )}
        </Строка>
        <Строка название="Средний чек">
          <span className="font-semibold">{руб(а.avg_check)}</span> <Дельта v={а.avg_check_delta} />
        </Строка>
      </dl>

      <h3 className="mt-5 mb-2 text-xs font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
        Обзвон
      </h3>
      <dl className="space-y-1">
        <Строка название="Результатов звонков">
          <span className="font-semibold">{з.total}</span>
        </Строка>
        <Строка название="«Записан» нажата">
          <span className="font-semibold">{з.booked_clicks}</span>
        </Строка>
        <Строка название="Подтверждено YCLIENTS" onClick={() => onДетали("confirmed", "подтверждённые звонки")}>
          <span className="font-semibold text-profit">{з.confirmed}</span>
        </Строка>
        <Строка название="Не подтверждено" onClick={() => onДетали("not_confirmed", "неподтверждённые звонки")}>
          <span className={з.not_confirmed ? "font-semibold text-loss" : "font-semibold"}>{з.not_confirmed}</span>
        </Строка>
        <Строка название="Ждут проверки" onClick={() => onДетали("pending", "звонки в ожидании")}>
          <span className="font-semibold">{з.pending}</span>
        </Строка>
        {з.error > 0 && (
          <Строка название="Не удалось проверить" onClick={() => onДетали("error", "звонки с ошибкой проверки")}>
            <span className="font-semibold text-caution">{з.error}</span>
          </Строка>
        )}
        <Строка название="Расхождения" onClick={() => onДетали("discrepancy", "расхождения результата")}>
          <span className={з.discrepancies ? "font-semibold text-caution" : "font-semibold"}>{з.discrepancies}</span>
        </Строка>
        <Строка название="Точность фиксации">
          <span className="font-semibold">{проц(з.button_accuracy_pct)}</span>
        </Строка>
        <Строка название="Конверсия дозвонившихся">
          <span className="font-semibold">{проц(з.conv_contacts_pct)}</span>
        </Строка>
        <Строка название="Конверсия всех попыток">
          <span className="font-semibold">{проц(з.conv_all_pct)}</span>
        </Строка>
      </dl>
      <p className="mt-3 text-xs text-muted-light dark:text-muted">
        Нажатие «Записан» засчитывается, только когда в YCLIENTS найдена новая запись клиента,
        созданная после звонка.
      </p>
    </article>
  );
}

// ── Детализация ───────────────────────────────────────────────────────────

const ПОДПИСИ: Record<string, string> = {
  record_id: "Запись",
  at: "Когда",
  created_at: "Создана",
  visit_at: "Визит",
  client_id: "Клиент (id)",
  client: "Клиент",
  admin: "Администратор",
  button: "Кнопка",
  record_found: "Запись найдена",
  reason: "Причина",
  amount: "Сумма, ₽",
  service: "Услуга",
  quantity: "Кол-во",
};

function значение(ключ: string, v: string | number | boolean | null): string {
  if (v == null || v === "") return НЕТ;
  if (typeof v === "boolean") return v ? "да" : "нет";
  if (["at", "created_at", "visit_at"].includes(ключ) && typeof v === "string") return время(v);
  return String(v);
}

function Детали({
  месяц,
  заголовок,
  вид,
  ключ,
  onЗакрыть,
}: {
  месяц: string;
  заголовок: string;
  вид: string;
  ключ: string;
  onЗакрыть: () => void;
}) {
  const [строки, setСтроки] = useState<СтрокаДетали[] | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);

  useEffect(() => {
    let отменено = false;
    (async () => {
      try {
        const r = await fetch(
          `/api/monthly-report/drilldown?month=${месяц}&kind=${вид}&key=${encodeURIComponent(ключ)}`,
        );
        if (!r.ok) {
          const тело = await r.json().catch(() => ({}));
          if (!отменено) setОшибка(тело.detail || "Не удалось получить список");
          return;
        }
        const тело = await r.json();
        if (!отменено) setСтроки(тело.rows);
      } catch {
        if (!отменено) setОшибка("Сервер не отвечает");
      }
    })();
    return () => {
      отменено = true;
    };
  }, [месяц, вид, ключ]);

  const колонки = строки && строки.length ? Object.keys(строки[0]).filter((k) => k in ПОДПИСИ) : [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-6"
      role="dialog"
      aria-label={заголовок}
    >
      <div className="max-h-[85vh] w-full max-w-5xl overflow-auto rounded-t-2xl sm:rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5">
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold">{заголовок}</h2>
          <button onClick={onЗакрыть} aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>
        {ошибка && <p className="text-loss">{ошибка}</p>}
        {!строки && !ошибка && (
          <div className="flex items-center gap-2 text-sm text-muted-light dark:text-muted">
            <Loader2 size={16} className="animate-spin" /> Загружаю…
          </div>
        )}
        {строки && строки.length === 0 && (
          <p className="text-sm text-muted-light dark:text-muted">Записей нет.</p>
        )}
        {строки && строки.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-light dark:text-muted">
                  {колонки.map((к) => (
                    <th key={к} className="p-2 font-medium whitespace-nowrap">
                      {ПОДПИСИ[к]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {строки.map((с, i) => (
                  <tr key={i} className="border-t border-milk-line dark:border-line">
                    {колонки.map((к) => (
                      <td key={к} className="p-2 align-top">
                        {значение(к, с[к])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
