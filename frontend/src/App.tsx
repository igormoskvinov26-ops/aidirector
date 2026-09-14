import { useEffect, useMemo, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  ComposedChart,
  Line,
} from "recharts";
import {
  LayoutDashboard,
  Users,
  Scissors,
  CreditCard,
  Sparkles,
  TrendingDown,
  DollarSign,
  Percent,
  UserCheck,
  ShoppingBag,
  Zap,
  ChevronRight,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Sun,
  Moon,
  Save,
  RefreshCw,
} from "lucide-react";
import ClientBasePage from "./ClientBasePage";
import logo from "./assets/logo.png";

/**
 * First and last day of a month, as YYYY-MM-DD.
 * Day 0 of the next month is the last day of this one, so February gets 28/29
 * and April gets 30. The previous code hardcoded "-31" for every month, which
 * produced 31 February, 31 April, 31 June, 31 September and 31 November.
 */
function monthRange(year: number, month: number): { from: string; to: string } {
  const mm = String(month).padStart(2, "0");
  const lastDay = new Date(year, month, 0).getDate();
  return { from: `${year}-${mm}-01`, to: `${year}-${mm}-${String(lastDay).padStart(2, "0")}` };
}

// ── Types ──
interface DashboardData {
  period: string;
  kpis: Record<string, string | number>;
  revenue_trend: TrendPoint[];
  top_masters: MasterMetric[];
  cancellation_rate: number;
}

interface TrendPoint {
  date: string;
  revenue: string;
  visits: number;
  avg_check: string;
}

interface MasterMetric {
  name: string;
  avatar_url: string | null;
  visits: number;
  revenue: string;
  avg_check: string;
  retention_pct: number;
  product_sales: string;
}

// ── Utils ──
const fmt = (n: string | number): string => {
  const num = typeof n === "string" ? parseFloat(n) : n;
  if (isNaN(num)) return "0";
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + "M";
  if (num >= 1_000) return Math.round(num / 1000) + "K";
  return String(Math.round(num));
};

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
  materials_pct: number;
  acquiring_pct: number;
  master_commission_pct: number;
  master_min_guarantee: number;
  fixed_monthly_total: number;
  fixed_daily: number;
  days_in_month: number;
  is_default: boolean;
}

/** Ответ /api/finance/plan-fact — сводка месяца и разбивка по составу смены. */
interface PlanFactRow {
  masters: number;
  break_even_daily: number;
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
// Роль оператора видит единственный раздел. Ограничение продублировано на
// сервере: прятать пункты меню — это удобство, а не защита.
const OPERATOR_PAGES = ["clientbase"];

const NAV = [
  { id: "planfact", label: "План-факт", icon: CreditCard },
  { id: "dashboard", label: "Дашборд", icon: LayoutDashboard },
  { id: "masters", label: "Мастера", icon: Scissors },
  { id: "clients", label: "Клиенты", icon: Users },
  { id: "clientbase", label: "Клиентская база", icon: Users },
  { id: "ai", label: "AI Отчёт", icon: Sparkles },
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

function KpiCard({
  label,
  value,
  icon: Icon,
  prefix,
  suffix,
  trend,
  negative,
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  prefix?: string;
  suffix?: string;
  trend?: "up" | "down";
  negative?: boolean;
}) {
  return (
    <div className="group bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-5 hover:border-rubl-accent/30 transition-all duration-300 hover:shadow-lg hover:shadow-rubl-accent/5 cursor-default">
      <div className="flex items-center justify-between mb-4">
        <span className="text-gray-500 dark:text-zinc-500 text-xs font-medium uppercase tracking-widest">
          {label}
        </span>
        <div
          className={`w-9 h-9 rounded-xl flex items-center justify-center ${
            negative ? "bg-red-500/10" : "bg-rubl-accent/10"
          } group-hover:scale-110 transition-transform duration-300`}
        >
          <Icon
            size={17}
            className={negative ? "text-red-400" : "text-rubl-accent"}
          />
        </div>
      </div>
      <div className={`text-3xl font-bold tracking-tight ${negative ? "text-red-400" : "text-gray-900 dark:text-white"}`}>
        {prefix}
        {fmt(value)}
        {suffix}
      </div>
      {trend && (
        <div className={`flex items-center gap-1 mt-2 text-xs ${trend === "up" ? "text-emerald-400" : "text-red-400"}`}>
          {trend === "up" ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
          <span>vs прошлый период</span>
        </div>
      )}
    </div>
  );
}

// ── Pages ──

function DashboardPage({ data }: { data: DashboardData | null }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [localData, setLocalData] = useState(data);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (data) setLocalData(data);
  }, [data]);

  const changeMonth = async (y: number, m: number) => {
    setYear(y);
    setMonth(m);
    setLoading(true);
    const { from, to } = monthRange(y, m);
    try {
      const r = await fetch(`/api/dashboard/range?date_from=${from}&date_to=${to}`);
      const json = await r.json();
      setLocalData(json);
    } catch {}
    setLoading(false);
  };

  const monthNames = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
  ];

  const prevMonth = () => {
    if (month === 1) changeMonth(year - 1, 12);
    else changeMonth(year, month - 1);
  };
  const nextMonth = () => {
    if (month === 12) changeMonth(year + 1, 1);
    else changeMonth(year, month + 1);
  };

  if (!localData) return null;

  return (
    <div className="animate-in">      
      {/* Month selector */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-1">Дашборд</h1>
          <p className="text-gray-500 dark:text-zinc-500 text-sm">{localData.period}</p>
        </div>
        <div className="flex items-center gap-3 bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-1">
          <button onClick={prevMonth} className="p-2 hover:bg-gray-200 dark:hover:bg-zinc-800 rounded-lg text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-white transition-colors">
            ←
          </button>
          <span className="text-sm font-medium min-w-[120px] text-center">
            {monthNames[month - 1]} {year}
          </span>
          <button onClick={nextMonth} className="p-2 hover:bg-gray-200 dark:hover:bg-zinc-800 rounded-lg text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-white transition-colors">
            →
          </button>
        </div>
      </div>

      {loading && (
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-20 rounded-2xl">
          <div className="w-6 h-6 border-2 border-rubl-accent/20 border-t-rubl-accent rounded-full animate-spin" />
        </div>
      )}

      {/* KPI Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <KpiCard label="Выручка" value={String(localData.kpis.total_revenue)} icon={DollarSign} prefix="₽" trend="up" />
        <KpiCard label="Средний чек" value={String(localData.kpis.avg_check)} icon={Zap} prefix="₽" />
        <KpiCard label="Записей" value={String(localData.kpis.total_visits)} icon={Activity} />
        <KpiCard label="Новые клиенты" value={String(localData.kpis.new_clients)} icon={UserCheck} />
        <KpiCard label="Повторные" value={String(localData.kpis.repeat_clients)} icon={Users} />
        <KpiCard label="Возвращаемость" value={String(localData.kpis.retention_pct)} icon={Percent} suffix="%" trend="up" />
        <KpiCard
          label="Отмены"
          value={String(localData.kpis.cancellation_pct)}
          icon={TrendingDown}
          suffix="%"
          negative={Number(localData.kpis.cancellation_pct) > 15}
          trend={Number(localData.kpis.cancellation_pct) > 15 ? "down" : "up"}
        />
        <KpiCard label="Косметика" value={String(localData.kpis.product_sales)} icon={ShoppingBag} prefix="₽" />
      </div>

      {/* Revenue Chart */}
      <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6 mb-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-500">Выручка</h2>
            <p className="text-xs text-gray-400 dark:text-zinc-600 mt-1">Динамика по дням</p>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={localData.revenue_trend || []}>
            <defs>
              <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={GOLD} stopOpacity={0.25} />
                <stop offset="100%" stopColor={GOLD} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f1f1f" vertical={false} />
            <XAxis
              dataKey="date"
              stroke="#525252"
              tick={{ fontSize: 11, fill: "#737373" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(d: string) =>
                new Date(d).toLocaleDateString("ru", { day: "numeric", month: "short" })
              }
            />
            <YAxis
              stroke="#525252"
              tick={{ fontSize: 11, fill: "#737373" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid #27272a",
                borderRadius: "12px",
                color: "#fff",
                boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
              }}
            />
            <Area type="monotone" dataKey="revenue" stroke={GOLD} fill="url(#revGrad)" strokeWidth={2} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Masters + Visits */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-500 mb-5">
            Топ мастера
          </h2>
          <div className="space-y-1">
            {localData.top_masters?.map((m, i) => (
              <div
                key={m.name}
                className="flex items-center gap-4 p-3 rounded-xl hover:bg-white/5 transition-colors group"
              >
                <span className="text-xs text-gray-400 dark:text-zinc-600 w-5 font-mono">{i + 1}</span>
                {m.avatar_url ? (
                  <img src={m.avatar_url} className="w-10 h-10 rounded-xl object-cover ring-1 ring-zinc-700" />
                ) : (
                  <div className="w-10 h-10 rounded-xl bg-rubl-accent/10 flex items-center justify-center text-rubl-accent font-bold text-sm">
                    {m.name[0]}
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{m.name}</div>
                  <div className="text-xs text-gray-500 dark:text-zinc-500">{m.visits} визитов</div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-semibold">{fmt(m.revenue)} ₽</div>
                  <div className="text-xs text-gray-500 dark:text-zinc-500">чек {fmt(m.avg_check)} ₽</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-500 mb-5">
            Визиты по дням
          </h2>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={localData.revenue_trend || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f1f1f" vertical={false} />
              <XAxis
                dataKey="date"
                stroke="#525252"
                tick={{ fontSize: 11, fill: "#737373" }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(d: string) =>
                  new Date(d).toLocaleDateString("ru", { day: "numeric" })
                }
              />
              <YAxis
                stroke="#525252"
                tick={{ fontSize: 11, fill: "#737373" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  background: "#18181b",
                  border: "1px solid #27272a",
                  borderRadius: "12px",
                  color: "#fff",
                }}
              />
              <Bar dataKey="visits" fill={GOLD} radius={[6, 6, 0, 0]} maxBarSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function MastersPage({ data }: { data: DashboardData | null }) {
  if (!data) return null;
  return (
    <div className="animate-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Мастера</h1>
        <p className="text-gray-500 dark:text-zinc-500 text-sm">Эффективность и загрузка</p>
      </div>

      <div className="space-y-3">
        {data.top_masters?.map((m) => (
          <div key={m.name} className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-5 hover:border-rubl-accent/20 transition-all">
            <div className="flex items-center gap-5">
              {m.avatar_url ? (
                <img src={m.avatar_url} className="w-14 h-14 rounded-2xl object-cover ring-1 ring-zinc-700" />
              ) : (
                <div className="w-14 h-14 rounded-2xl bg-rubl-accent/10 flex items-center justify-center text-rubl-accent font-bold text-xl">
                  {m.name[0]}
                </div>
              )}
              <div className="flex-1">
                <div className="font-semibold text-lg">{m.name}</div>
                <div className="flex gap-6 mt-3">
                  <Metric label="Визитов" value={String(m.visits)} />
                  <Metric label="Выручка" value={`${fmt(m.revenue)} ₽`} />
                  <Metric label="Средний чек" value={`${fmt(m.avg_check)} ₽`} />
                  <Metric label="Возврат" value={`${m.retention_pct}%`} />
                  <Metric label="Косметика" value={`${fmt(m.product_sales)} ₽`} />
                </div>
              </div>
              <ChevronRight size={18} className="text-gray-400 dark:text-zinc-600" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-500 dark:text-zinc-500">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

function ClientsPage() {
  return (
    <div className="animate-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Клиенты</h1>
        <p className="text-gray-500 dark:text-zinc-500 text-sm">RFM-анализ и сегментация</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <SegmentCard title="VIP" description=">5 визитов, >50K ₽" count={0} color={GOLD} />
        <SegmentCard title="Активные" description="2–4 визита" count={0} color="#22c55e" />
        <SegmentCard title="Потерянные" description=">60 дней без визита" count={0} color="#ef4444" />
        <SegmentCard title="Новые" description="Первый визит <30 дн" count={0} color="#3b82f6" />
        <SegmentCard title="Спящие" description="30–60 дн без визита" count={0} color="#eab308" />
        <SegmentCard title="Одноразовые" description="1 визит, >90 дн" count={0} color="#737373" />
      </div>

      <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-500 mb-4">
          Распределение клиентов
        </h2>
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie
              data={[
                { name: "VIP", value: 0, color: GOLD },
                { name: "Активные", value: 0, color: "#22c55e" },
                { name: "Новые", value: 0, color: "#3b82f6" },
                { name: "Потерянные", value: 0, color: "#ef4444" },
                { name: "Спящие", value: 0, color: "#eab308" },
              ]}
              cx="50%"
              cy="50%"
              innerRadius={70}
              outerRadius={110}
              paddingAngle={4}
              dataKey="value"
            >
              {[GOLD, "#22c55e", "#3b82f6", "#ef4444", "#eab308"].map((c) => (
                <Cell key={c} fill={c} stroke="transparent" />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid #27272a",
                borderRadius: "12px",
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function SegmentCard({
  title,
  description,
  count,
  color,
}: {
  title: string;
  description: string;
  count: number;
  color: string;
}) {
  return (
    <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-5 hover:border-zinc-700 transition-all">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
        <span className="font-semibold text-sm">{title}</span>
      </div>
      <div className="text-3xl font-bold mb-1">{count}</div>
      <div className="text-xs text-gray-500 dark:text-zinc-500">{description}</div>
    </div>
  );
}

/** Поля структуры расходов: подпись, единица и ключ в ответе сервера. */
const COST_FIELDS = [
  { key: "rent_monthly", label: "Аренда", unit: "₽ / мес" },
  { key: "utilities_monthly", label: "Коммуналка", unit: "₽ / мес" },
  { key: "manager_monthly", label: "Управляющий", unit: "₽ / мес" },
  { key: "cleaning_monthly", label: "Уборка", unit: "₽ / мес" },
  { key: "taxes_monthly", label: "Налоги", unit: "₽ / мес" },
  { key: "other_fixed_monthly", label: "Прочие постоянные", unit: "₽ / мес" },
  { key: "admin_per_shift", label: "Администратор", unit: "₽ / смена" },
  { key: "materials_pct", label: "Расходники", unit: "% выручки" },
  { key: "acquiring_pct", label: "Эквайринг", unit: "% выручки" },
  { key: "master_commission_pct", label: "Мастеру", unit: "% выручки" },
  { key: "master_min_guarantee", label: "Гарант мастера", unit: "₽ / смена" },
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

  // Порог «сделал план» для подписи над столбцом: выручка сегодняшнего дня,
  // нужная при текущем составе смены.
  const dailyPlanRequired = summary?.rows.find((r) => r.is_today)?.plan_daily_required ?? 0;

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
                      <div className="font-semibold">{RUB(row.break_even_daily)}</div>
                      <div className="text-xs text-gray-500 dark:text-zinc-500">день в ноль</div>
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
              оклады и аренда {RUB(costs.fixed_monthly_total)} в месяц,
              администратор {RUB(costs.admin_per_shift)} за смену ·{" "}
              <span className="text-gray-700 dark:text-zinc-300">
                итого {RUB(costs.fixed_daily)} в день
              </span>
              {" · мастеру "}{costs.master_commission_pct}% с гарантом {RUB(costs.master_min_guarantee)}
            </span>
          </button>

          {costsOpen && (
            <>
              <p className="text-xs text-gray-500 dark:text-zinc-500 mt-4 max-w-[70ch]">
                Из этих чисел считается всё остальное: порог безубыточности,
                выручка под план и прибыль за месяц. Месячные суммы делятся на
                {" "}{costs.days_in_month} дней текущего месяца, а оплата
                администратора добавляется целиком: она возникает в каждый
                рабочий день, а не размазывается по календарю.
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
              let color = "#ef4444";
              if (delta >= dailyPlanRequired) color = "#22c55e";
              else if (delta >= breakEvenDaily) color = "#0891b2";
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

function AIPage() {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const generate = async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/ai/quick?days=30");
      const json = await r.json();
      setReport(json);
    } catch (e) {
      setReport({ report: "Ошибка генерации. Проверьте DEEPSEEK_API_KEY в .env" });
    }
    setLoading(false);
  };

  return (
    <div className="animate-in">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-1">AI Директор</h1>
          <p className="text-gray-500 dark:text-zinc-500 text-sm">Управленческий отчёт на основе метрик</p>
        </div>
        <button
          onClick={generate}
          disabled={loading}
          className="flex items-center gap-2 bg-rubl-accent hover:bg-rubl-accent/90 text-black font-semibold px-5 py-2.5 rounded-xl transition-all disabled:opacity-50"
        >
          <Sparkles size={16} />
          {loading ? "Анализирую..." : "Сгенерировать отчёт"}
        </button>
      </div>

      {report && (
        <div className="space-y-4">
          {/* Insights */}
          {report.insights?.length > 0 && (
            <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
              <h3 className="text-sm font-semibold uppercase tracking-widest text-rubl-accent mb-4">
                Главные выводы
              </h3>
              <ul className="space-y-2">
                {report.insights.map((s: string, i: number) => (
                  <li key={i} className="flex items-start gap-3 text-sm text-gray-700 dark:text-zinc-300">
                    <span className="text-rubl-accent mt-1">•</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Risks + Opportunities */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {report.risks?.length > 0 && (
              <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
                <h3 className="text-sm font-semibold uppercase tracking-widest text-red-400 mb-4">
                  Риски
                </h3>
                <ul className="space-y-2">
                  {report.risks.map((s: string, i: number) => (
                    <li key={i} className="flex items-start gap-3 text-sm text-gray-700 dark:text-zinc-300">
                      <span className="text-red-400 mt-1">⚠</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {report.opportunities?.length > 0 && (
              <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
                <h3 className="text-sm font-semibold uppercase tracking-widest text-emerald-400 mb-4">
                  Возможности
                </h3>
                <ul className="space-y-2">
                  {report.opportunities.map((s: string, i: number) => (
                    <li key={i} className="flex items-start gap-3 text-sm text-gray-700 dark:text-zinc-300">
                      <span className="text-emerald-400 mt-1">+</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Actions */}
          {report.actions_tomorrow?.length > 0 && (
            <div className="bg-rubl-accent/5 border border-rubl-accent/20 rounded-2xl p-6">
              <h3 className="text-sm font-semibold uppercase tracking-widest text-rubl-accent mb-4">
                Что сделать завтра
              </h3>
              <ul className="space-y-2">
                {report.actions_tomorrow.map((s: string, i: number) => (
                  <li key={i} className="flex items-start gap-3 text-sm text-zinc-200">
                    <span className="text-rubl-accent font-bold">{i + 1}.</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Full Report */}
          {report.report && (
            <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
              <h3 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-500 mb-4">
                Полный отчёт
              </h3>
              <p className="text-sm text-gray-700 dark:text-zinc-300 leading-relaxed whitespace-pre-line">{report.report}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── App ──
export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState<"owner" | "operator">("operator");
  const [page, setPage] = useState("planfact");
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
    // Роль выясняем до всего остального: от неё зависит и меню, и то, какие
    // запросы вообще имеет смысл делать. Оператору дашборд не запрашиваем —
    // сервер на него ответит 403.
    (async () => {
      let resolved: "owner" | "operator" = "operator";
      try {
        const r = await fetch("/api/me");
        if (r.ok) {
          const body = await r.json();
          resolved = body.role === "owner" ? "owner" : "operator";
        }
      } catch (err) {
        console.error("Не удалось определить роль:", err);
      }
      setRole(resolved);

      if (resolved !== "owner") {
        setPage("clientbase");
        setLoading(false);
        return;
      }

      const now = new Date();
      const { from, to } = monthRange(now.getFullYear(), now.getMonth() + 1);
      try {
        const r = await fetch(`/api/dashboard/range?date_from=${from}&date_to=${to}`);
        setData(await r.json());
      } catch (err) {
        console.error("API не доступен:", err);
        setData({
          period: "API не доступен",
          kpis: {},
          revenue_trend: [],
          top_masters: [],
          cancellation_rate: 0,
        });
      } finally {
        setLoading(false);
      }
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
            {NAV.filter(
              (item) => role === "owner" || OPERATOR_PAGES.includes(item.id),
            ).map((item) => {
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
          <div className="text-xs text-gray-400 dark:text-zinc-600 mt-3">v1.0.0</div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 ml-60 p-8 min-h-screen">
        <div className="max-w-[1280px] mx-auto">
          {role === "owner" && page === "dashboard" && <DashboardPage data={data} />}
          {role === "owner" && page === "masters" && <MastersPage data={data} />}
          {role === "owner" && page === "clients" && <ClientsPage />}
          {page === "clientbase" && <ClientBasePage />}
          {role === "owner" && page === "planfact" && <PlanFactPage />}
          {role === "owner" && page === "ai" && <AIPage />}
        </div>
      </main>
    </div>
  );
}
