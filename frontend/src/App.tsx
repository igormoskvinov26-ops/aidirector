import { useEffect, useState } from "react";
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
} from "recharts";
import {
  LayoutDashboard,
  Users,
  Scissors,
  CreditCard,
  Sparkles,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Percent,
  UserCheck,
  ShoppingBag,
  Zap,
  ChevronRight,
  BarChart3,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";

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

const GOLD = "#d4a853";

// ── Navigation ──
const NAV = [
  { id: "dashboard", label: "Дашборд", icon: LayoutDashboard },
  { id: "masters", label: "Мастера", icon: Scissors },
  { id: "clients", label: "Клиенты", icon: Users },
  { id: "finance", label: "Финансы", icon: CreditCard },
  { id: "ai", label: "AI Отчёт", icon: Sparkles },
];

// ── Components ──
function Spinner() {
  return (
    <div className="min-h-screen bg-black flex items-center justify-center">
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
    <div className="group bg-zinc-900/80 border border-zinc-800 rounded-2xl p-5 hover:border-rubl-accent/30 transition-all duration-300 hover:shadow-lg hover:shadow-rubl-accent/5 cursor-default">
      <div className="flex items-center justify-between mb-4">
        <span className="text-zinc-500 text-xs font-medium uppercase tracking-widest">
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
      <div className={`text-3xl font-bold tracking-tight ${negative ? "text-red-400" : "text-white"}`}>
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
  if (!data) return null;

  return (
    <div className="animate-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Дашборд</h1>
        <p className="text-zinc-500 text-sm">{data.period}</p>
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <KpiCard label="Выручка" value={String(data.kpis.total_revenue)} icon={DollarSign} prefix="₽" trend="up" />
        <KpiCard label="Средний чек" value={String(data.kpis.avg_check)} icon={Zap} prefix="₽" />
        <KpiCard label="Записей" value={String(data.kpis.total_visits)} icon={Activity} />
        <KpiCard label="Новые клиенты" value={String(data.kpis.new_clients)} icon={UserCheck} />
        <KpiCard label="Повторные" value={String(data.kpis.repeat_clients)} icon={Users} />
        <KpiCard label="Возвращаемость" value={String(data.kpis.retention_pct)} icon={Percent} suffix="%" trend="up" />
        <KpiCard
          label="Отмены"
          value={String(data.kpis.cancellation_pct)}
          icon={TrendingDown}
          suffix="%"
          negative={Number(data.kpis.cancellation_pct) > 15}
          trend={Number(data.kpis.cancellation_pct) > 15 ? "down" : "up"}
        />
        <KpiCard label="Косметика" value={String(data.kpis.product_sales)} icon={ShoppingBag} prefix="₽" />
      </div>

      {/* Revenue Chart */}
      <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6 mb-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-500">Выручка</h2>
            <p className="text-xs text-zinc-600 mt-1">Динамика по дням</p>
          </div>
          <div className="flex gap-2">
            <span className="text-xs text-zinc-600 bg-zinc-800 px-3 py-1 rounded-lg">30 дней</span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={data.revenue_trend || []}>
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
        {/* Top Masters */}
        <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-500 mb-5">
            Топ мастера
          </h2>
          <div className="space-y-1">
            {data.top_masters?.map((m, i) => (
              <div
                key={m.name}
                className="flex items-center gap-4 p-3 rounded-xl hover:bg-white/5 transition-colors group"
              >
                <span className="text-xs text-zinc-600 w-5 font-mono">{i + 1}</span>
                {m.avatar_url ? (
                  <img src={m.avatar_url} className="w-10 h-10 rounded-xl object-cover ring-1 ring-zinc-700" />
                ) : (
                  <div className="w-10 h-10 rounded-xl bg-rubl-accent/10 flex items-center justify-center text-rubl-accent font-bold text-sm">
                    {m.name[0]}
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{m.name}</div>
                  <div className="text-xs text-zinc-500">{m.visits} визитов</div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-semibold">{fmt(m.revenue)} ₽</div>
                  <div className="text-xs text-zinc-500">чек {fmt(m.avg_check)} ₽</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Visits Chart */}
        <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-500 mb-5">
            Визиты по дням
          </h2>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={data.revenue_trend || []}>
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
        <p className="text-zinc-500 text-sm">Эффективность и загрузка</p>
      </div>

      <div className="space-y-3">
        {data.top_masters?.map((m) => (
          <div key={m.name} className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-5 hover:border-rubl-accent/20 transition-all">
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
              <ChevronRight size={18} className="text-zinc-600" />
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
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

function ClientsPage() {
  return (
    <div className="animate-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Клиенты</h1>
        <p className="text-zinc-500 text-sm">RFM-анализ и сегментация</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <SegmentCard title="VIP" description=">5 визитов, >50K ₽" count={0} color={GOLD} />
        <SegmentCard title="Активные" description="2–4 визита" count={0} color="#22c55e" />
        <SegmentCard title="Потерянные" description=">60 дней без визита" count={0} color="#ef4444" />
        <SegmentCard title="Новые" description="Первый визит <30 дн" count={0} color="#3b82f6" />
        <SegmentCard title="Спящие" description="30–60 дн без визита" count={0} color="#eab308" />
        <SegmentCard title="Одноразовые" description="1 визит, >90 дн" count={0} color="#737373" />
      </div>

      <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-500 mb-4">
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
    <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-5 hover:border-zinc-700 transition-all">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
        <span className="font-semibold text-sm">{title}</span>
      </div>
      <div className="text-3xl font-bold mb-1">{count}</div>
      <div className="text-xs text-zinc-500">{description}</div>
    </div>
  );
}

function FinancePage() {
  return (
    <div className="animate-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Финансы</h1>
        <p className="text-zinc-500 text-sm">P&L и ключевые показатели</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <KpiCard label="Выручка" value="0" icon={DollarSign} prefix="₽" />
        <KpiCard label="Прибыль" value="0" icon={TrendingUp} prefix="₽" trend="up" />
        <KpiCard label="Расходы" value="0" icon={TrendingDown} prefix="₽" />
        <KpiCard label="EBITDA" value="0" icon={BarChart3} prefix="₽" />
        <KpiCard label="ФОТ" value="0" icon={Users} prefix="₽" />
        <KpiCard label="Аренда" value="0" icon={CreditCard} prefix="₽" />
        <KpiCard label="Маркетинг" value="0" icon={Zap} prefix="₽" />
        <KpiCard label="Маржа" value="0" icon={Percent} suffix="%" />
      </div>

      <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-500 mb-4">
          P&L — Прибыли и убытки
        </h2>
        <div className="space-y-3">
          <PLLine label="Выручка" value="0 ₽" />
          <PLLine label="— Себестоимость" value="0 ₽" negative />
          <PLLine label="Валовая прибыль" value="0 ₽" bold />
          <div className="border-t border-zinc-800 my-2" />
          <PLLine label="— ФОТ" value="0 ₽" negative />
          <PLLine label="— Аренда" value="0 ₽" negative />
          <PLLine label="— Маркетинг" value="0 ₽" negative />
          <PLLine label="— Прочие расходы" value="0 ₽" negative />
          <div className="border-t border-zinc-800 my-2" />
          <PLLine label="Чистая прибыль" value="0 ₽" bold accent />
        </div>
      </div>
    </div>
  );
}

function PLLine({
  label,
  value,
  negative,
  bold,
  accent,
}: {
  label: string;
  value: string;
  negative?: boolean;
  bold?: boolean;
  accent?: boolean;
}) {
  return (
    <div className={`flex justify-between py-2 ${bold ? "font-semibold" : ""}`}>
      <span className={accent ? "text-rubl-accent" : "text-zinc-400"}>{label}</span>
      <span className={negative ? "text-red-400" : accent ? "text-rubl-accent font-bold" : "text-white"}>
        {value}
      </span>
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
          <p className="text-zinc-500 text-sm">Управленческий отчёт на основе метрик</p>
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
            <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
              <h3 className="text-sm font-semibold uppercase tracking-widest text-rubl-accent mb-4">
                Главные выводы
              </h3>
              <ul className="space-y-2">
                {report.insights.map((s: string, i: number) => (
                  <li key={i} className="flex items-start gap-3 text-sm text-zinc-300">
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
              <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
                <h3 className="text-sm font-semibold uppercase tracking-widest text-red-400 mb-4">
                  Риски
                </h3>
                <ul className="space-y-2">
                  {report.risks.map((s: string, i: number) => (
                    <li key={i} className="flex items-start gap-3 text-sm text-zinc-300">
                      <span className="text-red-400 mt-1">⚠</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {report.opportunities?.length > 0 && (
              <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
                <h3 className="text-sm font-semibold uppercase tracking-widest text-emerald-400 mb-4">
                  Возможности
                </h3>
                <ul className="space-y-2">
                  {report.opportunities.map((s: string, i: number) => (
                    <li key={i} className="flex items-start gap-3 text-sm text-zinc-300">
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
            <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6">
              <h3 className="text-sm font-semibold uppercase tracking-widest text-zinc-500 mb-4">
                Полный отчёт
              </h3>
              <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-line">{report.report}</p>
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
  const [page, setPage] = useState("dashboard");

  useEffect(() => {
    fetch("/api/dashboard/")
      .then((r) => r.json())
      .then(setData)
      .catch((err) => {
        console.error("API не доступен:", err);
        setData({
          period: "API не доступен",
          kpis: {},
          revenue_trend: [],
          top_masters: [],
          cancellation_rate: 0,
        });
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;

  return (
    <div className="min-h-screen bg-black text-white flex">
      {/* Sidebar */}
      <aside className="w-60 border-r border-zinc-800/50 flex flex-col fixed h-full bg-black/80 backdrop-blur-xl z-10">
        <div className="p-6">
          <div className="flex items-center gap-2.5 mb-8">
            <div className="w-8 h-8 rounded-lg bg-rubl-accent flex items-center justify-center text-black font-bold text-sm">
              Р
            </div>
            <div>
              <div className="text-sm font-bold tracking-tight leading-none">
                Рубл<span className="text-rubl-accent">Ъ</span>
              </div>
              <div className="text-[10px] text-zinc-500 mt-0.5">AI Director</div>
            </div>
          </div>

          <nav className="space-y-1">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = page === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setPage(item.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-200 ${
                    active
                      ? "bg-zinc-800/80 text-white font-medium"
                      : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900"
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

        <div className="mt-auto p-6 border-t border-zinc-800/50">
          <div className="text-xs text-zinc-600">v1.0.0</div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 ml-60 p-8 min-h-screen">
        <div className="max-w-[1280px] mx-auto">
          {page === "dashboard" && <DashboardPage data={data} />}
          {page === "masters" && <MastersPage data={data} />}
          {page === "clients" && <ClientsPage />}
          {page === "finance" && <FinancePage />}
          {page === "ai" && <AIPage />}
        </div>
      </main>
    </div>
  );
}
