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
} from "recharts";
import {
  TrendingUp,
  TrendingDown,
  Users,
  DollarSign,
  Percent,
  Clock,
  UserCheck,
  ShoppingBag,
  Zap,
} from "lucide-react";

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

const KPI_CARDS = [
  { key: "total_revenue", label: "Выручка", icon: DollarSign, prefix: "₽" },
  { key: "profit", label: "Прибыль", icon: TrendingUp, prefix: "₽" },
  { key: "avg_check", label: "Средний чек", icon: Zap, prefix: "₽" },
  { key: "new_clients", label: "Новые клиенты", icon: Users },
  { key: "repeat_clients", label: "Повторные", icon: UserCheck },
  {
    key: "retention_pct",
    label: "Возвращаемость",
    icon: Percent,
    suffix: "%",
  },
  {
    key: "cancellation_pct",
    label: "Отмены",
    icon: TrendingDown,
    suffix: "%",
  },
  { key: "product_sales", label: "Косметика", icon: ShoppingBag, prefix: "₽" },
];

function formatNumber(n: string | number): string {
  const num = typeof n === "string" ? parseFloat(n) : n;
  if (isNaN(num)) return "0";
  if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
  if (num >= 1000) return (num / 1000).toFixed(0) + "K";
  return String(Math.round(num));
}

function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/dashboard/")
      .then((r) => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-rubl-black flex items-center justify-center">
        <div className="animate-spin w-8 h-8 border-2 border-rubl-accent border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-rubl-black text-white">
      {/* Header */}
      <header className="border-b border-rubl-border px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl font-bold tracking-tight">
            Рубл<span className="text-rubl-accent">Ъ</span>
          </span>
          <span className="text-rubl-muted text-sm">AI Director</span>
        </div>
        <div className="text-rubl-muted text-sm">{data?.period}</div>
      </header>

      <main className="p-8 max-w-[1440px] mx-auto">
        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {KPI_CARDS.map((card) => {
            const value = data?.kpis?.[card.key] ?? "0";
            const isNegative =
              card.key === "cancellation_pct" && Number(value) > 15;

            return (
              <div
                key={card.key}
                className="bg-rubl-card border border-rubl-border rounded-xl p-5 hover:border-rubl-accent/30 transition-colors"
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-rubl-muted text-xs uppercase tracking-wider">
                    {card.label}
                  </span>
                  <card.icon
                    size={16}
                    className={
                      isNegative ? "text-rubl-negative" : "text-rubl-accent"
                    }
                  />
                </div>
                <div
                  className={`text-2xl font-bold ${
                    isNegative ? "text-rubl-negative" : ""
                  }`}
                >
                  {card.prefix}
                  {formatNumber(value)}
                  {card.suffix}
                </div>
              </div>
            );
          })}
        </div>

        {/* Revenue Chart */}
        <div className="bg-rubl-card border border-rubl-border rounded-xl p-6 mb-6">
          <h2 className="text-sm uppercase tracking-wider text-rubl-muted mb-4">
            Выручка по дням
          </h2>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data?.revenue_trend || []}>
              <defs>
                <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#d4a853" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#d4a853" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis
                dataKey="date"
                stroke="#737373"
                tick={{ fontSize: 11 }}
                tickFormatter={(d: string) =>
                  new Date(d).toLocaleDateString("ru", {
                    day: "numeric",
                    month: "short",
                  })
                }
              />
              <YAxis stroke="#737373" tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  background: "#1a1a1a",
                  border: "1px solid #333",
                  borderRadius: "8px",
                  color: "#fff",
                }}
              />
              <Area
                type="monotone"
                dataKey="revenue"
                stroke="#d4a853"
                fill="url(#revGrad)"
                strokeWidth={2}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Masters Table + Visits Chart */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Masters */}
          <div className="bg-rubl-card border border-rubl-border rounded-xl p-6">
            <h2 className="text-sm uppercase tracking-wider text-rubl-muted mb-4">
              Мастера
            </h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-rubl-muted text-xs uppercase border-b border-rubl-border">
                  <th className="text-left py-3 font-medium">Мастер</th>
                  <th className="text-right py-3 font-medium">Визитов</th>
                  <th className="text-right py-3 font-medium">Выручка</th>
                  <th className="text-right py-3 font-medium">Чек</th>
                </tr>
              </thead>
              <tbody>
                {data?.top_masters?.map((m) => (
                  <tr
                    key={m.name}
                    className="border-b border-rubl-border/50 hover:bg-white/5"
                  >
                    <td className="py-3 flex items-center gap-3">
                      {m.avatar_url ? (
                        <img
                          src={m.avatar_url}
                          alt={m.name}
                          className="w-8 h-8 rounded-full object-cover"
                        />
                      ) : (
                        <div className="w-8 h-8 rounded-full bg-rubl-accent/20 flex items-center justify-center text-rubl-accent text-xs">
                          {m.name[0]}
                        </div>
                      )}
                      <span className="font-medium">{m.name}</span>
                    </td>
                    <td className="text-right py-3">{m.visits}</td>
                    <td className="text-right py-3 font-medium">
                      {formatNumber(m.revenue)} ₽
                    </td>
                    <td className="text-right py-3 text-rubl-muted">
                      {formatNumber(m.avg_check)} ₽
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Visits Bar Chart */}
          <div className="bg-rubl-card border border-rubl-border rounded-xl p-6">
            <h2 className="text-sm uppercase tracking-wider text-rubl-muted mb-4">
              Визиты по дням
            </h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data?.revenue_trend || []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
                <XAxis
                  dataKey="date"
                  stroke="#737373"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(d: string) =>
                    new Date(d).toLocaleDateString("ru", { day: "numeric" })
                  }
                />
                <YAxis stroke="#737373" tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    background: "#1a1a1a",
                    border: "1px solid #333",
                    borderRadius: "8px",
                    color: "#fff",
                  }}
                />
                <Bar dataKey="visits" fill="#d4a853" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
