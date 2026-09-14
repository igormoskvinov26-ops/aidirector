import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ComposedChart,
  Line,
} from "recharts";
import {
  Users,
  CreditCard,
  Sun,
  Moon,
  Save,
  CalendarClock,
  Wallet,
  RefreshCw,
} from "lucide-react";
import ClientBasePage from "./ClientBasePage";
import BarberMonthPage from "./BarberMonthPage";
import logo from "./assets/logo.png";

// ── Types ──
type Role = "owner" | "operator" | "master";

interface DailyFinancePoint {
  date: string;
  revenue: number;
  completed: number;
  scheduled: number;
  product_sales: number;
  total_visits: number;
  completed_visits: number;
  masters_count: number;
  margin_rub: number;
  margin_pct: number;
  break_even: number;
  /** Выручка, нужная в этот день для выполнения плана по прибыли. */
  revenue_for_plan: number;
  /** Границы зон для состава смены этого дня, округлены вверх до тысяч. */
  zone_low: number;
  zone_high: number;
  /** red — минус при любом раскладе, amber — решает распределение,
   *  green — плюс при любом. null у дней без выручки. */
  zone: "red" | "amber" | "green" | null;
  costs: { fixed: number; variable: number; master_commission: number; total: number };
}

interface PlanData {
  period: string;
  profit_target: number;
  margin_target_pct: number;
}

/** Ответ /api/finance/costs — структура расходов, задаётся владельцем. */
interface CostSettings {
  rent_monthly: number;
  utilities_monthly: number;
  manager_monthly: number;
  cleaning_monthly: number;
  taxes_monthly: number;
  other_fixed_monthly: number;
  admin_per_shift: number;
  admin_shifts_per_month: number;
  materials_pct: number;
  acquiring_pct: number;
  master_commission_pct: number;
  product_commission_pct: number;
  admin_monthly_total: number;
  fixed_monthly_total: number;
  fixed_daily: number;
  days_in_month: number;
  is_default: boolean;
}

/** Ответ /api/finance/plan-fact — сводка месяца и разбивка по составу смены. */
interface TodayMaster {
  name: string;
  services: number;
  products: number;
  payout: number;
  on_guarantee: boolean;
}

interface TodayDetail {
  masters: TodayMaster[];
  revenue: number;
  payout: number;
  fixed: number;
  variable: number;
  margin: number;
  break_even: number;
  to_break_even: number;
}

interface PlanFactRow {
  masters: number;
  break_even_daily: number;
  break_even_worst: number;
  plan_daily_required: number;
  plan_per_master: number;
  fact_daily_avg: number | null;
  fact_days: number;
  is_today: boolean;
}

interface PlanFactSummary {
  period: string;
  today: string;
  days_in_month: number;
  days_passed: number;
  days_left: number;
  masters_today: number;
  today_detail: TodayDetail;
  fact: {
    earned_total: number;
    services_amount: number;
    services_count: number;
    products_amount: number;
    products_units: number;
  };
  plan: {
    profit_target: number;
    profit_so_far: number;
    remaining: number;
    profit_needed_daily: number;
    completion_pct: number;
  };
  rows: PlanFactRow[];
}

const GOLD = "#d4a853";

// ── Navigation ──
// Какие разделы видит каждая роль. Ограничение продублировано на сервере:
// прятать пункты меню — это удобство, а не защита. Мастер, зашедший по
// прямому адресу, всё равно получит от сервера только свою строку.
const PAGES_BY_ROLE: Record<string, string[]> = {
  owner: ["planfact", "bookings", "payroll", "clients"],
  operator: ["payroll", "clients"],
  master: ["payroll"],
};

const NAV = [
  { id: "planfact", label: "План-факт", icon: CreditCard },
  { id: "bookings", label: "Будущие записи", icon: CalendarClock },
  { id: "payroll", label: "Расчёт ЗП", icon: Wallet },
  { id: "clients", label: "Клиенты", icon: Users },
];

// ── Components ──
function Spinner() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-black flex items-center justify-center">
      <div className="relative">
        <div className="w-8 h-8 border-2 border-rubl-accent/20 rounded-full" />
        <div className="w-8 h-8 border-2 border-transparent border-t-rubl-accent rounded-full animate-spin absolute inset-0" />
      </div>
    </div>
  );
}

const COST_FIELDS = [
  { key: "rent_monthly", label: "Аренда", unit: "₽ / мес" },
  { key: "utilities_monthly", label: "Коммуналка", unit: "₽ / мес" },
  { key: "manager_monthly", label: "Управляющий", unit: "₽ / мес" },
  { key: "cleaning_monthly", label: "Уборка", unit: "₽ / мес" },
  { key: "taxes_monthly", label: "Налоги", unit: "₽ / мес" },
  { key: "other_fixed_monthly", label: "Прочие постоянные", unit: "₽ / мес" },
  { key: "admin_per_shift", label: "Администратор", unit: "₽ / смена" },
  { key: "admin_shifts_per_month", label: "Смен администратора", unit: "в месяц" },
  { key: "materials_pct", label: "Расходники", unit: "% выручки" },
  { key: "acquiring_pct", label: "Эквайринг", unit: "% выручки" },
  { key: "master_commission_pct", label: "Мастеру с услуг", unit: "% выручки" },
  { key: "product_commission_pct", label: "Мастеру с косметики", unit: "% продаж" },
] as const;

function PlanFactPage() {
  const [hourly, setHourly] = useState<any[]>([]);
  const [daily, setDaily] = useState<DailyFinancePoint[]>([]);
  const [plan, setPlan] = useState<PlanData>({ period: "", profit_target: 0, margin_target_pct: 30 });
  const [summary, setSummary] = useState<PlanFactSummary | null>(null);
  const [costs, setCosts] = useState<CostSettings | null>(null);
  const [costsOpen, setCostsOpen] = useState(false);
  const [costsDraft, setCostsDraft] = useState<Record<string, string>>({});
  const [costsError, setCostsError] = useState("");
  const [planInput, setPlanInput] = useState("");
  const [loading, setLoading] = useState(true);

  const now = new Date();
  const todayStr = now.toISOString().split("T")[0];
  const currentPeriod = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const year = now.getFullYear();
  const monthStart = `${year}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  const monthEnd = `${year}-${String(now.getMonth() + 1).padStart(2, "0")}-${new Date(year, now.getMonth() + 1, 0).getDate()}`;

  const fetchData = async () => {
    setLoading(true);
    try {
      const [hRes, dRes, pRes, sRes, cRes] = await Promise.all([
        fetch(`/api/finance/hourly?date=${todayStr}`),
        fetch(`/api/finance/daily?date_from=${monthStart}&date_to=${monthEnd}`),
        fetch("/api/finance/plan"),
        fetch("/api/finance/plan-fact"),
        fetch("/api/finance/costs"),
      ]);
      setHourly(await hRes.json());
      setDaily(await dRes.json());
      const p = await pRes.json();
      setPlan(p);
      setPlanInput(p.profit_target > 0 ? String(Math.round(p.profit_target)) : "");
      setSummary(await sRes.json());
      const c: CostSettings = await cRes.json();
      setCosts(c);
      setCostsDraft(Object.fromEntries(COST_FIELDS.map((f) => [f.key, String(c[f.key])])));
    } catch (e) {
      console.error("Finance fetch error", e);
    }
    setLoading(false);
  };

  // Один раз при открытии вкладки. Перечитывание — по кнопке «Обновить
  // данные», поэтому fetchData намеренно не в зависимостях: иначе загрузка
  // пойдёт на каждую перерисовку.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchData(); }, []);

  const savePlan = async () => {
    const val = parseFloat(planInput);
    if (isNaN(val) || val <= 0) return;
    try {
      await fetch("/api/finance/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period: currentPeriod, profit_target: val, margin_target_pct: plan.margin_target_pct }),
      });
      setPlan({ ...plan, profit_target: val });
      await fetchData();
    } catch (e) {
      console.error("Plan save error", e);
    }
  };

  const saveCosts = async () => {
    setCostsError("");
    const body = Object.fromEntries(
      COST_FIELDS.map((f) => [f.key, parseFloat(costsDraft[f.key] || "0") || 0]),
    );
    try {
      const r = await fetch("/api/finance/costs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        // Сервер отвергает заведомо невозможную экономику — показываем его
        // причину, а не общее «не сохранилось».
        const detail = await r.json().catch(() => null);
        setCostsError(
          typeof detail?.detail === "string"
            ? detail.detail
            : "Не удалось сохранить: проверьте значения.",
        );
        return;
      }
      setCostsOpen(false);
      await fetchData();
    } catch (e) {
      console.error("Costs save error", e);
      setCostsError("Сервер не ответил.");
    }
  };

  const dailyPlan = summary?.rows.find((r) => r.is_today)?.plan_daily_required ?? 0;
  const breakEvenDaily = hourly.length > 0 ? hourly[0].break_even : 19500;
  const todayRevenue = hourly.reduce((s: number, h: any) => s + h.completed + h.scheduled, 0);
  const mastersToday = hourly.length > 0 ? hourly[0].masters_count : 0;

  const FMT = (n: number): string => {
    if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (Math.abs(n) >= 1_000) return Math.round(n / 1000) + "K";
    return String(Math.round(n));
  };
  const FMT_RUB = (n: number): string => FMT(n) + " ₽";
  // Точный формат для сводки и таблицы: округление до тысяч уместно на осях
  // графика, но не в числе «сколько нужно заработать, чтобы выйти в ноль».
  const RUB = (n: number): string => Math.round(n).toLocaleString("ru-RU") + " ₽";

  const nowHour = `${now.getHours()}:00`;

  const hourlyCumulative = useMemo(() => {
    let cumCompleted = 0;
    let cumScheduled = 0;
    let cumProducts = 0;
    return hourly.map((h) => {
      cumCompleted += h.completed;
      cumProducts += (h.product_sales || 0);
      cumScheduled += h.scheduled;
      return { ...h, services: cumCompleted, products: cumProducts, scheduled: cumScheduled };
    });
  }, [hourly]);


  const dailyCumulative = useMemo(() => {
    let cumServices = 0;
    let cumProducts = 0;
    let cumScheduled = 0;
    let cumBE = 0;
    let cumPlan = 0;
    return daily.map((d) => {
      cumServices += d.completed;
      cumProducts += (d.product_sales || 0);
      cumScheduled += d.scheduled;
      cumBE += d.break_even;
      cumPlan += d.revenue_for_plan || 0;
      const delta = d.completed + (d.product_sales || 0);
      return {
        ...d,
        services: cumServices,
        products: cumProducts,
        scheduled: cumScheduled,
        break_even: cumBE,
        daily_plan_cum: cumPlan,
        delta,
      };
    });
  }, [daily]);

  if (loading) return <Spinner />;

  return (
    <div className="animate-in">
      {/* Header with plan input */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-1">План-факт</h1>
          <p className="text-gray-500 dark:text-zinc-500 text-sm">Маржинальность, точка безубыточности, план/факт</p>
        </div>
        <div className="flex items-end gap-3">
          <div>
            {/* Единицы подписаны не случайно: раньше поле принимало голое
                число, и «500» вместо 500 000 молча превращалось в план
                в пятьсот рублей. */}
            <label className="block text-[11px] uppercase tracking-wider text-gray-500 dark:text-zinc-500 mb-1">
              План прибыли на месяц, ₽
            </label>
            <input
              type="number"
              value={planInput}
              onChange={(e) => setPlanInput(e.target.value)}
              placeholder="например, 500000"
              className="w-40 bg-gray-100 dark:bg-zinc-900 border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:border-rubl-accent"
            />
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5 border border-gray-300 dark:border-zinc-700 hover:border-rubl-accent px-4 py-2 rounded-lg text-sm transition-all disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Обновить данные
          </button>
          <button
            onClick={savePlan}
            className="flex items-center gap-1.5 bg-rubl-accent hover:bg-rubl-accent/90 text-black font-semibold px-4 py-2 rounded-lg text-sm transition-all"
          >
            <Save size={14} />
            Сохранить
          </button>
        </div>
      </div>

      {/* Сегодня — по фактической выработке каждого мастера. Никаких
          допущений: кто сколько сделал, уже известно. */}
      {summary?.today_detail && (
        <div
          className={`bg-white dark:bg-zinc-900/80 border rounded-2xl p-6 mb-6 ${
            summary.today_detail.margin >= 0
              ? "border-emerald-600/50"
              : "border-red-500/40"
          }`}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-3 mb-5">
            <h3 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">
              Сегодня — {summary.today}
            </h3>
            <span
              className={`text-sm font-semibold ${
                summary.today_detail.margin >= 0 ? "text-emerald-500" : "text-red-400"
              }`}
            >
              {summary.today_detail.margin >= 0
                ? `В плюсе на ${RUB(summary.today_detail.margin)}`
                : summary.today_detail.to_break_even > 0
                  ? `До нуля не хватает ${RUB(summary.today_detail.to_break_even)} по услугам`
                  : `Минус ${RUB(-summary.today_detail.margin)}`}
            </span>
          </div>

          {summary.today_detail.masters.length === 0 ? (
            <p className="text-sm text-gray-500 dark:text-zinc-500">
              Выполненных записей сегодня пока нет.
            </p>
          ) : (
            <div className="overflow-x-auto mb-5">
              <table className="w-full text-sm min-w-[520px]">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-gray-500 dark:text-zinc-500">
                    <th className="pb-2 pr-4 font-semibold">Мастер</th>
                    <th className="pb-2 px-4 font-semibold text-right">Услуги</th>
                    <th className="pb-2 px-4 font-semibold text-right">Косметика</th>
                    <th className="pb-2 pl-4 font-semibold text-right">К выплате</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.today_detail.masters.map((m) => (
                    <tr key={m.name} className="border-t border-gray-100 dark:border-zinc-800/60">
                      <td className="py-2.5 pr-4">
                        {m.name}
                        {m.on_guarantee && (
                          <span className="ml-2 text-[10px] uppercase tracking-wider text-amber-500 border border-amber-500/40 rounded px-1.5 py-0.5">
                            гарант
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-4 text-right">{RUB(m.services)}</td>
                      <td className="py-2.5 px-4 text-right text-gray-500 dark:text-zinc-500">
                        {m.products > 0 ? RUB(m.products) : "—"}
                      </td>
                      <td className="py-2.5 pl-4 text-right font-semibold">{RUB(m.payout)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 text-sm">
            <div>
              <div className="text-xs text-gray-500 dark:text-zinc-500">Заработано</div>
              <div className="font-semibold mt-1">{RUB(summary.today_detail.revenue)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 dark:text-zinc-500">Мастерам</div>
              <div className="font-semibold mt-1">− {RUB(summary.today_detail.payout)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 dark:text-zinc-500">Постоянные</div>
              <div className="font-semibold mt-1">− {RUB(summary.today_detail.fixed)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 dark:text-zinc-500">Расходники</div>
              <div className="font-semibold mt-1">− {RUB(summary.today_detail.variable)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 dark:text-zinc-500">Итог дня</div>
              <div
                className={`font-semibold mt-1 ${
                  summary.today_detail.margin >= 0 ? "text-emerald-500" : "text-red-400"
                }`}
              >
                {summary.today_detail.margin >= 0 ? "+" : "−"}
                {RUB(Math.abs(summary.today_detail.margin))}
              </div>
            </div>
          </div>

          <p className="text-xs text-gray-500 dark:text-zinc-500 mt-4 max-w-[80ch]">
            Считается по фактической выработке каждого: гарант платится
            персонально, поэтому две одинаковые общие суммы обходятся салону
            по-разному. Порог сегодня при сложившемся распределении —{" "}
            {RUB(summary.today_detail.break_even)} по услугам.
          </p>
        </div>
      )}

      {/* Сводка месяца и таблица по составу смены */}
      {summary && (
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6 mb-6">
          <div className="flex flex-wrap items-baseline justify-between gap-3 mb-5">
            <h3 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">
              С начала месяца — {summary.period}
            </h3>
            <span className="text-xs text-gray-500 dark:text-zinc-500">
              прошло {summary.days_passed} из {summary.days_in_month} дней · осталось {summary.days_left}
            </span>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
            <SumCard
              label="Заработано всего"
              value={RUB(summary.fact.earned_total)}
              note="выручка: услуги и косметика"
              accent
            />
            <SumCard
              label="Прибыль"
              value={RUB(summary.plan.profit_so_far)}
              note={
                summary.plan.profit_target > 0
                  ? `${summary.plan.completion_pct}% · ещё ${RUB(summary.plan.remaining)}`
                  : "план прибыли не задан"
              }
              accent
            />
            <SumCard
              label="Выполнено записей"
              value={String(summary.fact.services_count)}
              note={`на ${RUB(summary.fact.services_amount)}`}
            />
            <SumCard
              label="Продано косметики"
              value={`${summary.fact.products_units} шт`}
              note={`на ${RUB(summary.fact.products_amount)}`}
            />
            <SumCard
              label="Нужно прибыли в день"
              value={
                summary.plan.profit_needed_daily > 0
                  ? RUB(summary.plan.profit_needed_daily)
                  : "—"
              }
              note={
                summary.plan.profit_needed_daily > 0
                  ? `чтобы догнать план за ${summary.days_left} дн.`
                  : "задайте план прибыли"
              }
            />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-gray-500 dark:text-zinc-500">
                  <th className="pb-2 pr-4 font-semibold">Мастеров на смене</th>
                  <th className="pb-2 px-4 font-semibold">Маржинальность</th>
                  <th className="pb-2 px-4 font-semibold">План — нужна выручка</th>
                  <th className="pb-2 pl-4 font-semibold">Факт</th>
                </tr>
              </thead>
              <tbody>
                {summary.rows.map((row) => (
                  <tr
                    key={row.masters}
                    className={
                      row.is_today
                        ? "bg-rubl-accent/10 border-l-2 border-rubl-accent"
                        : "border-l-2 border-transparent"
                    }
                  >
                    <td className="py-3 pr-4">
                      <span className="font-semibold">{row.masters}</span>
                      {row.is_today && (
                        <span className="ml-2 text-[11px] text-rubl-accent uppercase tracking-wider">
                          сегодня
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      <div className="font-semibold">
                        {RUB(row.break_even_daily)}
                        {row.break_even_worst > row.break_even_daily && (
                          <span className="text-gray-500 dark:text-zinc-500 font-normal">
                            {" … "}{RUB(row.break_even_worst)}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-zinc-500">
                        {row.break_even_worst > row.break_even_daily
                          ? "при равной загрузке … если работает один"
                          : "день в ноль"}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      {row.plan_daily_required > 0 ? (
                        <>
                          <div className="font-semibold">{RUB(row.plan_daily_required)}</div>
                          <div className="text-xs text-gray-500 dark:text-zinc-500">
                            по {RUB(row.plan_per_master)} на мастера
                          </div>
                        </>
                      ) : (
                        <span className="text-gray-400 dark:text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-3 pl-4">
                      {row.fact_daily_avg !== null ? (
                        <>
                          <div
                            className={`font-semibold ${
                              row.fact_daily_avg >= row.break_even_daily
                                ? "text-emerald-500"
                                : "text-red-400"
                            }`}
                          >
                            {RUB(row.fact_daily_avg)}
                          </div>
                          <div className="text-xs text-gray-500 dark:text-zinc-500">
                            среднее за {row.fact_days} дн.
                          </div>
                        </>
                      ) : (
                        <span className="text-gray-400 dark:text-zinc-600">
                          таких смен не было
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Структура расходов — из неё считается порог безубыточности */}
      {costs && (
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6 mb-6">
          <button
            onClick={() => setCostsOpen(!costsOpen)}
            className="w-full flex flex-wrap items-baseline justify-between gap-3 text-left"
          >
            <h3 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">
              Расходы {costsOpen ? "▴" : "▾"}
            </h3>
            <span className="text-xs text-gray-500 dark:text-zinc-500">
              {RUB(costs.fixed_monthly_total)} в месяц, из них администратор{" "}
              {RUB(costs.admin_monthly_total)} за {costs.admin_shifts_per_month} смен ·{" "}
              <span className="text-gray-700 dark:text-zinc-300">
                итого {RUB(costs.fixed_daily)} в день
              </span>
              {" · мастеру "}{costs.master_commission_pct}% с услуг и{" "}
              {costs.product_commission_pct}% с косметики
            </span>
          </button>

          {costsOpen && (
            <>
              <p className="text-xs text-gray-500 dark:text-zinc-500 mt-4 max-w-[70ch]">
                Из этих чисел считается всё остальное: порог безубыточности,
                выручка под план и прибыль за месяц. Оплата администратора
                сначала переводится в месяц по числу смен, и только потом всё
                вместе делится на {costs.days_in_month} дней текущего месяца.
              </p>
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mt-4">
                {COST_FIELDS.map((f) => (
                  <label key={f.key} className="block">
                    <span className="block text-[11px] uppercase tracking-wider text-gray-500 dark:text-zinc-500 mb-1">
                      {f.label}
                    </span>
                    <input
                      type="number"
                      step="0.01"
                      value={costsDraft[f.key] ?? ""}
                      onChange={(e) =>
                        setCostsDraft({ ...costsDraft, [f.key]: e.target.value })
                      }
                      className="w-full bg-gray-100 dark:bg-zinc-950 border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:border-rubl-accent"
                    />
                    <span className="block text-[11px] text-gray-400 dark:text-zinc-600 mt-1">
                      {f.unit}
                    </span>
                  </label>
                ))}
              </div>
              {costsError && (
                <p className="text-sm text-red-400 mt-4">{costsError}</p>
              )}
              <div className="flex items-center gap-3 mt-5">
                <button
                  onClick={saveCosts}
                  className="flex items-center gap-1.5 bg-rubl-accent hover:bg-rubl-accent/90 text-black font-semibold px-4 py-2 rounded-lg text-sm transition-all"
                >
                  <Save size={14} />
                  Сохранить расходы
                </button>
                <button
                  onClick={() => {
                    setCostsDraft(
                      Object.fromEntries(
                        COST_FIELDS.map((f) => [f.key, String(costs[f.key])]),
                      ),
                    );
                    setCostsError("");
                  }}
                  className="text-sm text-gray-500 dark:text-zinc-500 hover:text-gray-800 dark:hover:text-zinc-300"
                >
                  Вернуть как было
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Chart 1: Hourly (Today) */}
      <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">
            Сегодня — {todayStr}
          </h3>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-zinc-400">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-rubl-accent" /> Услуги выполн.</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-emerald-500" /> Товары</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm border border-rubl-accent/30 bg-rubl-accent/25" /> Запланировано</span>
            <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-red-500 rounded-full" /> Безубыточность {FMT_RUB(breakEvenDaily)}</span>
            {dailyPlan > 0 && <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-emerald-400 rounded-full" /> План дня {FMT_RUB(dailyPlan)}</span>}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={hourlyCumulative} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis dataKey="hour" tick={{ fill: "#71717a", fontSize: 11 }} />
            <YAxis tick={{ fill: "#71717a", fontSize: 11 }} tickFormatter={(v) => FMT(v)} />
            <Tooltip
              contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: "12px", fontSize: 12 }}
              formatter={(value: any, name: any) => {
                if (name === "services") return [FMT_RUB(value), "Услуги (накопл.)"];
                if (name === "products") return [FMT_RUB(value), "Товары (накопл.)"];
                if (name === "scheduled") return [FMT_RUB(value), "Запланировано (накопл.)"];
                if (name === "break_even") return [FMT_RUB(value), "Мин. маржинальность"];
                return [value, name];
              }}
            />
            <Bar dataKey="services" stackId="rev" name="services" radius={[4, 4, 0, 0]} label={({ x, y, width, index, value }: any) => {
              const entry = hourlyCumulative[index];
              if (!entry || entry.hour !== nowHour) return null;
              return (
                <g>
                  <text x={x + width / 2} y={y - 8} fill="#000" fontSize={12} fontWeight={700} textAnchor="middle" stroke="#000" strokeWidth={3} paintOrder="stroke">{FMT_RUB(value)}</text>
                  <text x={x + width / 2} y={y - 8} fill="#f0c060" fontSize={12} fontWeight={700} textAnchor="middle">{FMT_RUB(value)}</text>
                </g>
              );
            }}>
              {hourlyCumulative.map((entry, i) => (
                <Cell key={i} fill={GOLD} stroke={entry.hour === nowHour ? "#22d3ee" : "transparent"} strokeWidth={entry.hour === nowHour ? 2 : 0} />
              ))}
            </Bar>
            <Bar dataKey="products" stackId="rev" fill="#22c55e" name="products" radius={[0, 0, 0, 0]} />
            <Bar dataKey="scheduled" stackId="rev" name="scheduled" radius={[4, 4, 0, 0]} label={({ x, y, width, index }: any) => {
              const entry = hourlyCumulative[index];
              if (!entry || entry.hour !== nowHour) return null;
              const total = entry.services + entry.products + entry.scheduled;
              return <text x={x + width / 2} y={y - 8} fill="#f0c060" fontSize={11} fontWeight={700} textAnchor="middle">{FMT_RUB(total)}</text>;
            }}>
              {hourlyCumulative.map((entry, i) => (
                <Cell key={i} fill={GOLD} fillOpacity={0.25} stroke={entry.hour === nowHour ? "#22d3ee" : GOLD} strokeWidth={entry.hour === nowHour ? 2 : 1} />
              ))}
            </Bar>
            <Line dataKey="break_even" stroke="#ef4444" strokeWidth={2.5} dot={false} name="break_even" />
            {dailyPlan > 0 && (
              <Line dataKey={() => dailyPlan} stroke="#22c55e" strokeWidth={2.5} dot={false} name="daily_plan" />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Chart 2: Daily (current month) */}
      <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">
            По дням — {currentPeriod}
          </h3>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-zinc-400">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-rubl-accent" /> Услуги выполн.</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-emerald-500" /> Товары</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm border border-rubl-accent/30 bg-rubl-accent/25" /> Запланировано</span>
            <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-red-500 rounded-full" /> Мин. марж. (накоп.)</span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="w-2 h-2 rounded-full bg-yellow-500" />
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              день: убыток · спорно · прибыль
            </span>
            {plan.profit_target > 0 && <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-emerald-400 rounded-full" /> Выручка под план (накоп.)</span>}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={dailyCumulative} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis dataKey="date" tick={{ fill: "#71717a", fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
            <YAxis tick={{ fill: "#71717a", fontSize: 11 }} tickFormatter={(v) => FMT(v)} />
            <Tooltip
              contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: "12px", fontSize: 12 }}
              formatter={(value: any, name: any) => {
                if (name === "services") return [FMT_RUB(value), "Услуги (накопл.)"];
                if (name === "products") return [FMT_RUB(value), "Товары (накопл.)"];
                if (name === "scheduled") return [FMT_RUB(value), "Запланировано (накопл.)"];
                if (name === "break_even") return [FMT_RUB(value), "Мин. маржинальность"];
                if (name === "daily_plan_cum") return [FMT_RUB(value), "Выручка под план (накопл.)"];
                return [value, name];
              }}
            />
            <Bar dataKey="services" stackId="rev" name="services" radius={[6, 6, 0, 0]} label={({ x, y, width, index }: any) => {
              const entry = dailyCumulative[index];
              const delta = entry?.delta || 0;
              if (delta <= 0) return null;
              // Три зоны: красная — день убыточен при любом распределении
              // выручки между мастерами, жёлтая — исход зависит от него,
              // зелёная — прибыль при любом. Границы считает сервер: они
              // зависят от того, сколько человек было на смене.
              const color =
                entry.zone === "green"
                  ? "#22c55e"
                  : entry.zone === "amber"
                    ? "#eab308"
                    : "#ef4444";
              return (
                <g>
                  <text x={x + width / 2} y={y - 6} fill="#000" fontSize={11} fontWeight={700} textAnchor="middle" stroke="#000" strokeWidth={3} paintOrder="stroke">{FMT_RUB(delta)}</text>
                  <text x={x + width / 2} y={y - 6} fill={color} fontSize={11} fontWeight={700} textAnchor="middle">{FMT_RUB(delta)}</text>
                </g>
              );
            }}>
              {dailyCumulative.map((entry, i) => (
                <Cell key={i} fill={GOLD} stroke={entry.date === todayStr ? "#22d3ee" : "transparent"} strokeWidth={entry.date === todayStr ? 2 : 0} />
              ))}
            </Bar>
            <Bar dataKey="products" stackId="rev" fill="#22c55e" name="products" radius={[0, 0, 0, 0]} />
            <Bar dataKey="scheduled" stackId="rev" name="scheduled" radius={[6, 6, 0, 0]} label={({ x, y, width, index }: any) => {
              const entry = dailyCumulative[index];
              if (!entry || entry.date !== todayStr) return null;
              const actual = entry.services + entry.products;
              if (actual <= 0) return null;
              return <text x={x + width / 2} y={y - 8} fill="#22d3ee" fontSize={11} fontWeight={700} textAnchor="middle">{FMT_RUB(actual)}</text>;
            }}>
              {dailyCumulative.map((entry, i) => (
                <Cell key={i} fill={GOLD} fillOpacity={0.25} stroke={entry.date === todayStr ? "#22d3ee" : GOLD} strokeWidth={entry.date === todayStr ? 2 : 1} />
              ))}
            </Bar>
            <Line dataKey="break_even" stroke="#ef4444" strokeWidth={2.5} dot={false} name="break_even" />
            {plan.profit_target > 0 && (
              <Line dataKey="daily_plan_cum" stroke="#22c55e" strokeWidth={2.5} dot={false} name="daily_plan_cum" />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* KPI mini-cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-4">
          <div className="text-xs text-gray-500 dark:text-zinc-500">Выручка сегодня</div>
          <div className="text-lg font-bold mt-1">{FMT_RUB(todayRevenue)}</div>
        </div>
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-4">
          <div className="text-xs text-gray-500 dark:text-zinc-500">Мастеров на смене</div>
          <div className="text-lg font-bold mt-1">{mastersToday}</div>
        </div>
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-4">
          <div className="text-xs text-gray-500 dark:text-zinc-500">Точка безубыточности</div>
          <div className="text-lg font-bold mt-1">{FMT_RUB(breakEvenDaily)}</div>
        </div>
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-4">
          <div className="text-xs text-gray-500 dark:text-zinc-500">План на день</div>
          <div className="text-lg font-bold mt-1">{dailyPlan > 0 ? FMT_RUB(dailyPlan) : "—"}</div>
        </div>
      </div>
    </div>
  );
}

/** Плитка сводки: крупное число и поясняющая строка под ним. */
function SumCard({
  label,
  value,
  note,
  accent,
}: {
  label: string;
  value: string;
  note: string;
  accent?: boolean;
}) {
  return (
    <div className="bg-gray-50 dark:bg-zinc-950/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-4">
      <div className="text-xs text-gray-500 dark:text-zinc-500">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${accent ? "text-rubl-accent" : ""}`}>{value}</div>
      <div className="text-xs text-gray-500 dark:text-zinc-500 mt-1">{note}</div>
    </div>
  );
}

/** Ответ /api/bookings/upcoming. */
interface BookingRecord {
  id: number;
  time: string;
  client: string;
  phone: string;
  is_new_client: boolean;
  total_visits: number;
  master: string;
  services: string[];
  amount: number;
  comment: string;
}

interface BookingDay {
  date: string;
  count: number;
  amount: number;
  masters: string[];
  records: BookingRecord[];
}

interface UpcomingBookings {
  from: string;
  to: string;
  days_ahead: number;
  total_count: number;
  total_amount: number;
  days: BookingDay[];
}

const HORIZONS = [
  { days: 7, label: "Неделя" },
  { days: 14, label: "Две недели" },
  { days: 30, label: "Месяц" },
];

const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];

/** Дата как «15 сентября, вторник» — в списке на месяц иначе не сориентироваться. */
function humanDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const month = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
  ][d.getMonth()];
  return `${d.getDate()} ${month}, ${WEEKDAYS[d.getDay()]}`;
}

function BookingsPage() {
  const [data, setData] = useState<UpcomingBookings | null>(null);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(true);

  const load = async (horizon: number) => {
    setLoading(true);
    try {
      const r = await fetch(`/api/bookings/upcoming?days=${horizon}`);
      setData(await r.json());
    } catch (e) {
      console.error("Bookings fetch error", e);
    }
    setLoading(false);
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(days); }, [days]);

  const RUB = (n: number): string => Math.round(n).toLocaleString("ru-RU") + " ₽";
  const todayIso = new Date().toISOString().slice(0, 10);

  if (loading && !data) return <Spinner />;

  return (
    <div className="animate-in">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-1">Будущие записи</h1>
          <p className="text-gray-500 dark:text-zinc-500 text-sm">
            Кто придёт, когда и на какую сумму. Отменённые и неявки сюда не попадают.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {HORIZONS.map((h) => (
            <button
              key={h.days}
              onClick={() => setDays(h.days)}
              className={`px-3 py-2 rounded-lg text-sm border transition-all ${
                days === h.days
                  ? "border-rubl-accent text-rubl-accent"
                  : "border-gray-300 dark:border-zinc-700 text-gray-500 dark:text-zinc-500 hover:border-gray-400"
              }`}
            >
              {h.label}
            </button>
          ))}
          <button
            onClick={() => load(days)}
            disabled={loading}
            className="flex items-center gap-1.5 border border-gray-300 dark:border-zinc-700 hover:border-rubl-accent px-4 py-2 rounded-lg text-sm transition-all disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Обновить
          </button>
        </div>
      </div>

      {data && (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          <SumCard
            label="Записей впереди"
            value={String(data.total_count)}
            note={`с ${data.from} по ${data.to}`}
            accent
          />
          <SumCard
            label="На сумму"
            value={RUB(data.total_amount)}
            note="если все дойдут"
          />
          <SumCard
            label="Дней с записями"
            value={String(data.days.length)}
            note={`из ${data.days_ahead} впереди`}
          />
        </div>
      )}

      {data && data.days.length === 0 && (
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-10 text-center">
          <p className="text-gray-500 dark:text-zinc-500">
            На ближайшие {data.days_ahead} дней записей нет.
          </p>
        </div>
      )}

      <div className="space-y-4">
        {data?.days.map((day) => (
          <div
            key={day.date}
            className={`bg-white dark:bg-zinc-900/80 border rounded-2xl p-6 ${
              day.date === todayIso
                ? "border-rubl-accent"
                : "border-gray-200 dark:border-zinc-800"
            }`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-3 mb-4">
              <h3 className="text-sm font-semibold uppercase tracking-widest text-gray-600 dark:text-zinc-300">
                {humanDate(day.date)}
                {day.date === todayIso && (
                  <span className="ml-2 text-rubl-accent">сегодня</span>
                )}
              </h3>
              <span className="text-xs text-gray-500 dark:text-zinc-500">
                {day.count} записей на {RUB(day.amount)} · {day.masters.join(", ")}
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-gray-500 dark:text-zinc-500">
                    <th className="pb-2 pr-4 font-semibold">Время</th>
                    <th className="pb-2 px-4 font-semibold">Клиент</th>
                    <th className="pb-2 px-4 font-semibold">Мастер</th>
                    <th className="pb-2 px-4 font-semibold">Услуги</th>
                    <th className="pb-2 pl-4 font-semibold text-right">Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {day.records.map((r) => (
                    <tr key={r.id} className="border-t border-gray-100 dark:border-zinc-800/60">
                      <td className="py-3 pr-4 font-semibold whitespace-nowrap">{r.time}</td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span>{r.client}</span>
                          {r.is_new_client && (
                            <span className="text-[10px] uppercase tracking-wider text-rubl-accent border border-rubl-accent/40 rounded px-1.5 py-0.5">
                              новый
                            </span>
                          )}
                        </div>
                        {r.phone && (
                          <a
                            href={`tel:${r.phone}`}
                            className="text-xs text-gray-500 dark:text-zinc-500 hover:text-rubl-accent"
                          >
                            {r.phone}
                          </a>
                        )}
                      </td>
                      <td className="py-3 px-4 text-gray-600 dark:text-zinc-400">{r.master}</td>
                      <td className="py-3 px-4 text-gray-600 dark:text-zinc-400">
                        {r.services.length ? r.services.join(", ") : "—"}
                        {r.comment && (
                          <div className="text-xs text-gray-400 dark:text-zinc-600 mt-0.5">
                            {r.comment}
                          </div>
                        )}
                      </td>
                      <td className="py-3 pl-4 text-right font-semibold whitespace-nowrap">
                        {RUB(r.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState<Role>("master");
  const [userName, setUserName] = useState<string | null>(null);
  const [page, setPage] = useState("payroll");
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("rubl-theme") === "light" ? "light" : "dark";
    }
    return "dark";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("rubl-theme", theme);
  }, [theme]);

  useEffect(() => {
    // Роль выясняем до всего остального: от неё зависит и меню, и то, какая
    // вкладка откроется. Данные каждая вкладка грузит сама — общей загрузки
    // здесь больше нет.
    (async () => {
      // Роль по умолчанию — самая узкая: если сервер не ответил, лучше
      // показать меньше, чем случайно показать чужое.
      let resolved: Role = "master";
      try {
        const r = await fetch("/api/me");
        if (r.ok) {
          const body = await r.json();
          if (body.role === "owner" || body.role === "operator" || body.role === "master") {
            resolved = body.role;
          }
          setUserName(body.name ?? null);
        }
      } catch (err) {
        console.error("Не удалось определить роль:", err);
      }
      setRole(resolved);
      setPage(PAGES_BY_ROLE[resolved][0]);
      setLoading(false);
    })();
  }, []);

  if (loading) return <Spinner />;

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-black text-gray-900 dark:text-white flex">
      {/* Sidebar */}
      <aside className="w-60 border-r border-gray-200 dark:border-zinc-800/50 flex flex-col fixed h-full bg-white/90 dark:bg-black/80 backdrop-blur-xl z-10">
        <div className="p-6">
          <div className="flex items-center gap-2.5 mb-8">
            <img src={logo} alt="РублЪ" className="h-12 w-auto object-contain" />
            <div>
              <div className="text-sm font-bold tracking-tight leading-none">
                Рубл<span className="text-rubl-accent">Ъ</span>
              </div>
              <div className="text-[10px] text-gray-500 dark:text-zinc-500 mt-0.5">AI Director</div>
            </div>
          </div>

          <nav className="space-y-1">
            {NAV.filter((item) => PAGES_BY_ROLE[role].includes(item.id)).map((item) => {
              const Icon = item.icon;
              const active = page === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setPage(item.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-200 ${
                    active
                      ? "bg-gray-100 dark:bg-zinc-800/80 text-gray-900 dark:text-white font-medium"
                      : "text-gray-500 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-900"
                  }`}
                >
                  <Icon size={18} className={active ? "text-rubl-accent" : ""} />
                  {item.label}
                  {active && (
                    <span className="ml-auto w-1.5 h-1.5 rounded-full bg-rubl-accent" />
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="mt-auto p-6 border-t border-gray-200 dark:border-zinc-800/50">
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-900 transition-colors"
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          </button>
          {/* Кто вошёл. Мастеру это важнее всего: он должен видеть, что перед
              ним его собственный расчёт, а не чужой. */}
          <div className="text-xs text-gray-400 dark:text-zinc-600 mt-3">
            {userName
              ? userName
              : role === "owner"
                ? "Владелец"
                : role === "operator"
                  ? "Администратор"
                  : "Мастер"}
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 ml-60 p-8 min-h-screen">
        <div className="max-w-[1280px] mx-auto">
          {/* Каждая страница показывается, только если роль её действительно
              имеет. Список ролей один, и меню, и маршрутизация читают его. */}
          {PAGES_BY_ROLE[role].includes(page) && (
            <>
              {page === "planfact" && <PlanFactPage />}
              {page === "bookings" && <BookingsPage />}
              {page === "payroll" && <BarberMonthPage payroll />}
              {page === "clients" && <ClientBasePage />}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
