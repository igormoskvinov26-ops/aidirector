import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Users,
  UserPlus,
  ShieldCheck,
  AlertTriangle,
  UserMinus,
  RotateCcw,
  Phone,
  MessageSquare,
  RefreshCw,
  Check,
  X,
  ClipboardList,
  Activity,
  ArrowRight,
  ChevronLeft,
  FileSpreadsheet,
  Upload,
  Download,
} from "lucide-react";

// ── Types ──
type Period = "day" | "week" | "month" | "quarter" | "year";

interface Flow {
  new: number;
  returned: number;
  became_risk: number;
  became_lost: number;
  inflow: number;
  outflow: number;
  net: number;
}

interface DashboardData {
  generatedAt: string;
  period: string;
  metrics: {
    active_base: number;
    new: number;
    became_regular: number;
    at_risk: number;
    lost: number;
    returned: number;
    total: number;
  };
  flow: Flow;
  segments: { code: string; label: string; count: number }[];
}

interface TimePoint {
  date: string;
  active_base: number;
  active: number;
  due: number;
  risk: number;
  late: number;
  lost: number;
}

interface SegmentClient {
  client_id: number;
  name: string | null;
  phone: string | null;
  segment: string;
  stable: boolean;
  days_since: number;
  r: number | null;
  interval_days: number | null;
  visits: number;
  last_visit: string;
}

interface Task {
  id: number;
  client_id: number;
  client_name: string;
  phone: string | null;
  group_code: string;
  priority: number;
  due_date: string;
  status: string;
  visits_count: number;
  last_visit: string | null;
  last_service: string | null;
  goal: string;
  phone_script: string;
  message_script: string;
}

const PERIODS: { id: Period; label: string }[] = [
  { id: "day", label: "День" },
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "quarter", label: "Квартал" },
  { id: "year", label: "Год" },
];

const SEGMENT_COLORS: Record<string, string> = {
  active: "#22c55e",
  due: "#d4a853",
  risk: "#e8bd69",
  late: "#f97316",
  lost: "#ef4444",
};

const GROUP_LABELS: Record<string, string> = {
  due: "Пора записываться",
  risk: "Зона риска",
  late: "Сильно задерживаются",
  lost: "Потерянные",
};

export default function ClientBasePage({ role }: { role: "owner" | "operator" | "master" }) {
  const [mode, setMode] = useState<"manager" | "admin">("manager");

  return (
    <div className="animate-in">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-1">Клиентская база</h1>
          <p className="text-gray-500 dark:text-zinc-500 text-sm">Здоровье базы, сегменты и рабочая очередь</p>
        </div>
        <div className="flex items-center gap-1 bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-1">
          <button
            onClick={() => setMode("manager")}
            className={`px-4 py-2 rounded-lg text-sm transition-all ${mode === "manager" ? "bg-gray-200 dark:bg-zinc-800 text-gray-900 dark:text-white font-medium" : "text-gray-500 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300"}`}
          >
            Управляющий
          </button>
          <button
            onClick={() => setMode("admin")}
            className={`px-4 py-2 rounded-lg text-sm transition-all ${mode === "admin" ? "bg-gray-200 dark:bg-zinc-800 text-gray-900 dark:text-white font-medium" : "text-gray-500 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300"}`}
          >
            Администратор
          </button>
        </div>
      </div>

      {mode === "manager" ? <ManagerView /> : <AdminView role={role} />}
    </div>
  );
}

function ManagerView() {
  const [period, setPeriod] = useState<Period>("month");
  const [data, setData] = useState<DashboardData | null>(null);
  const [timeseries, setTimeseries] = useState<TimePoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncState, setSyncState] = useState<{ is_stale: boolean; last_snapshot_at: string | null } | null>(null);
  const [selectedSegment, setSelectedSegment] = useState<string | null>(null);
  const [clients, setClients] = useState<SegmentClient[]>([]);
  const [clientsLoading, setClientsLoading] = useState(false);

  const fetchData = async (p: Period) => {
    setLoading(true);
    try {
      const days = p === "year" ? 365 : p === "quarter" ? 90 : p === "month" ? 30 : p === "week" ? 7 : 1;
      const [dRes, tRes] = await Promise.all([
        fetch(`/api/client-base/dashboard?period=${p}`),
        fetch(`/api/client-base/timeseries?days=${days}`),
      ]);
      setData(await dRes.json());
      setTimeseries(await tRes.json());
    } catch {
      setData(null);
    }
    setLoading(false);
  };

  const fetchStatus = async () => {
    try {
      const r = await fetch("/api/client-base/sync/status");
      setSyncState(await r.json());
    } catch {}
  };

  useEffect(() => {
    fetchData(period);
    fetchStatus();
  }, [period]);

  const runSync = async () => {
    try {
      await fetch("/api/client-base/sync", { method: "POST" });
      await fetchData(period);
      await fetchStatus();
    } catch {}
  };

  const openSegment = async (code: string) => {
    setSelectedSegment(code);
    setClientsLoading(true);
    try {
      const r = await fetch(`/api/client-base/clients?segment=${code}`);
      setClients(await r.json());
    } catch {
      setClients([]);
    }
    setClientsLoading(false);
  };

  if (loading) return <Spinner />;

  const m = data?.metrics;
  const flow = data?.flow;
  const total = m?.total ?? 0;

  const cards = [
    { label: "Активная база", value: m?.active_base ?? 0, icon: Users, color: "#22c55e" },
    { label: "Новые", value: m?.new ?? 0, icon: UserPlus, color: "#d4a853" },
    { label: "Стали постоянными", value: m?.became_regular ?? 0, icon: ShieldCheck, color: "#38bdf8" },
    { label: "В зоне риска", value: m?.at_risk ?? 0, icon: AlertTriangle, color: "#e8bd69" },
    { label: "Потеряны", value: m?.lost ?? 0, icon: UserMinus, color: "#ef4444" },
    { label: "Вернули", value: m?.returned ?? 0, icon: RotateCcw, color: "#a3e635" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-1">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              onClick={() => setPeriod(p.id)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-all ${period === p.id ? "bg-gray-200 dark:bg-zinc-800 text-gray-900 dark:text-white font-medium" : "text-gray-500 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300"}`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <button
          onClick={runSync}
          className="flex items-center gap-2 text-xs text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-white px-3 py-2 rounded-lg border border-gray-200 dark:border-zinc-800 hover:border-rubl-accent transition-all"
        >
          <RefreshCw size={14} />
          Синхронизировать
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        {cards.map((c) => (
          <div key={c.label} className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <c.icon size={16} style={{ color: c.color }} />
              <span className="text-gray-500 dark:text-zinc-500 text-[11px] font-medium uppercase tracking-widest">{c.label}</span>
            </div>
            <div className="text-2xl font-bold tabular-nums">{c.value}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_0.8fr]">
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <Activity size={16} className="text-emerald-500" />
            <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">Пульс базы</h2>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={timeseries} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <defs>
                <linearGradient id="pulseFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#22c55e" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="#22c55e" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#d4d4d4" vertical={false} className="dark:hidden" />
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} className="hidden dark:block" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#999" }} tickLine={false} axisLine={false} tickFormatter={(d) => d.slice(5)} minTickGap={24} />
              <YAxis tick={{ fontSize: 11, fill: "#999" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: "12px", fontSize: 12 }} />
              <Area type="monotone" dataKey="active_base" name="Активная база" stroke="#22c55e" strokeWidth={2.5} fill="url(#pulseFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400 mb-4">Баланс движения</h2>
          <div className="flex items-end justify-between gap-4 border-b border-gray-200 dark:border-zinc-800 pb-4">
            <div>
              <div className="text-xs text-gray-500 dark:text-zinc-500">Вошли</div>
              <div className="text-3xl font-bold text-emerald-500">+{flow?.inflow ?? 0}</div>
            </div>
            <ArrowRight size={18} className="mb-1 text-gray-300 dark:text-zinc-600" />
            <div className="text-right">
              <div className="text-xs text-gray-500 dark:text-zinc-500">Вышли</div>
              <div className="text-3xl font-bold text-amber-500">−{flow?.outflow ?? 0}</div>
            </div>
          </div>
          <div className="mt-4 space-y-2 text-sm">
            <FlowRow label="Новые клиенты" value={`+${flow?.new ?? 0}`} positive />
            <FlowRow label="Вернулись" value={`+${flow?.returned ?? 0}`} positive />
            <FlowRow label="Перешли в риск" value={`−${flow?.became_risk ?? 0}`} />
            <FlowRow label="Стали потерянными" value={`−${flow?.became_lost ?? 0}`} />
          </div>
          <div className="mt-4 rounded-xl bg-gray-100 dark:bg-zinc-800/60 px-4 py-3">
            <div className="text-[11px] uppercase tracking-widest text-gray-500 dark:text-zinc-500">Чистый прирост</div>
            <div className={`text-2xl font-bold ${(flow?.net ?? 0) >= 0 ? "text-emerald-500" : "text-red-500"}`}>
              {(flow?.net ?? 0) >= 0 ? "+" : ""}{flow?.net ?? 0}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400 mb-4">Карта сегментов на сегодня</h2>

        <div className="flex h-3 overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800">
          {(data?.segments ?? []).map((s) => (
            <span key={s.code} style={{ width: `${total ? (s.count / total) * 100 : 0}%`, background: SEGMENT_COLORS[s.code] }} />
          ))}
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {(data?.segments ?? []).map((s) => (
            <button
              key={s.code}
              onClick={() => openSegment(s.code)}
              className={`bg-gray-50 dark:bg-zinc-900/60 border rounded-xl p-4 text-left transition-all ${selectedSegment === s.code ? "border-rubl-accent" : "border-gray-200 dark:border-zinc-800 hover:border-gray-300 dark:hover:border-zinc-600"}`}
            >
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full" style={{ background: SEGMENT_COLORS[s.code] }} />
                <p className="text-sm font-medium text-gray-700 dark:text-zinc-300">{s.label}</p>
              </div>
              <p className="mt-3 text-2xl font-semibold tabular-nums">{s.count}</p>
              <p className="mt-1 text-xs text-gray-400 dark:text-zinc-600">{total ? Math.round((s.count / total) * 100) : 0}% базы</p>
            </button>
          ))}
        </div>

        <p className="mt-4 text-xs text-gray-400 dark:text-zinc-600">
          Всего в базе <span className="font-semibold text-gray-700 dark:text-zinc-300">{total}</span> клиентов · нажмите на сегмент, чтобы увидеть список
        </p>
      </div>

      {selectedSegment && (
        <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <button onClick={() => setSelectedSegment(null)} className="text-gray-500 dark:text-zinc-500 hover:text-gray-900 dark:hover:text-white">
                <ChevronLeft size={18} />
              </button>
              <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 dark:text-zinc-400">
                {SEGMENT_COLORS[selectedSegment] && <span className="mr-2 size-2 rounded-full inline-block" style={{ background: SEGMENT_COLORS[selectedSegment] }} />}
                {GROUP_LABELS[selectedSegment] || selectedSegment} · {clients.length}
              </h2>
            </div>
          </div>
          {clientsLoading ? (
            <Spinner />
          ) : clients.length === 0 ? (
            <div className="text-gray-500 dark:text-zinc-500 text-center py-8">Клиентов в этом сегменте нет</div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {clients.map((c) => (
                <div key={c.client_id} className="bg-gray-50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-4">
                  <div className="font-medium">{c.name || "—"}</div>
                  <div className="text-sm text-gray-500 dark:text-zinc-500">{c.phone || "—"}</div>
                  <div className="mt-2 flex items-center gap-3 text-xs text-gray-500 dark:text-zinc-500">
                    <span>{c.days_since} дн. назад</span>
                    {c.stable && c.interval_days && <span>· цикл {c.interval_days} дн.</span>}
                    <span>· визитов {c.visits}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {syncState && (
        <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-zinc-500">
          <span className={`size-1.5 rounded-full ${syncState.is_stale ? "bg-red-500" : "bg-emerald-500"}`} />
          {syncState.last_snapshot_at
            ? `Снимок сегментов: ${syncState.last_snapshot_at}${syncState.is_stale ? " (устарел)" : ""}`
            : "Снимков ещё нет"}
        </div>
      )}
    </div>
  );
}

function FlowRow({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-gray-500 dark:text-zinc-400">{label}</span>
      <span className={`font-semibold tabular-nums ${positive ? "text-emerald-500" : "text-amber-500"}`}>{value}</span>
    </div>
  );
}

function AdminView({ role }: { role: "owner" | "operator" | "master" }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [busy, setBusy] = useState<number | null>(null);
  const [journalKey, setJournalKey] = useState(0);

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/client-base/tasks?status=open");
      setTasks(await r.json());
    } catch {
      setTasks([]);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const recordOutcome = async (id: number, outcome: string, channel: string) => {
    setBusy(id);
    try {
      await fetch(`/api/client-base/tasks/${id}/outcome`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outcome, channel, actor_id: "admin" }),
      });
      setTasks((prev) => prev.filter((t) => t.id !== id));
      setJournalKey((k) => k + 1);
    } catch {}
    setBusy(null);
  };

  const groups = ["due", "risk", "late", "lost"];
  const filtered = filter === "all" ? tasks : tasks.filter((t) => t.group_code === filter);

  const counts: Record<string, number> = {};
  for (const t of tasks) counts[t.group_code] = (counts[t.group_code] || 0) + 1;

  if (loading) return <Spinner />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-1 bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-xl p-1 w-fit">
        <button
          onClick={() => setFilter("all")}
          className={`px-3 py-1.5 rounded-lg text-xs transition-all ${filter === "all" ? "bg-gray-200 dark:bg-zinc-800 text-gray-900 dark:text-white" : "text-gray-500 dark:text-zinc-500"}`}
        >
          Все ({tasks.length})
        </button>
        {groups.map((g) => (
          <button
            key={g}
            onClick={() => setFilter(g)}
            className={`px-3 py-1.5 rounded-lg text-xs transition-all ${filter === g ? "bg-gray-200 dark:bg-zinc-800 text-gray-900 dark:text-white" : "text-gray-500 dark:text-zinc-500"}`}
          >
            {GROUP_LABELS[g]} ({counts[g] || 0})
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-zinc-400">
        <ClipboardList size={16} />
        <span>{filtered.length} клиентов требуют действия</span>
      </div>

      <CallJournal role={role} refreshKey={journalKey} />

      {filtered.length === 0 ? (
        <div className="bg-gray-50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-2xl p-10 text-center text-gray-500 dark:text-zinc-500">
          Все задачи обработаны. Так держать!
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((t) => (
            <TaskCard key={t.id} task={t} busy={busy === t.id} onOutcome={(o, c) => recordOutcome(t.id, o, c)} />
          ))}
        </div>
      )}
    </div>
  );
}

function TaskCard({
  task,
  busy,
  onOutcome,
}: {
  task: Task;
  busy: boolean;
  onOutcome: (outcome: string, channel: string) => void;
}) {
  const color = SEGMENT_COLORS[task.group_code] || "#71717a";
  return (
    <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-5 hover:border-rubl-accent/40 transition-all">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="size-2.5 rounded-full shrink-0 mt-1" style={{ background: color }} />
          <div>
            <div className="font-semibold text-lg">{task.client_name}</div>
            <div className="text-sm text-gray-500 dark:text-zinc-500">{task.phone || "—"}</div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-500 dark:text-zinc-500">
              <span>{task.visits_count} визит{plural(task.visits_count)}</span>
              {task.last_visit && <span>· {formatDate(task.last_visit)}</span>}
              {task.last_service && <span>· {task.last_service}</span>}
            </div>
          </div>
        </div>
        <span className="text-xs text-gray-500 dark:text-zinc-500 bg-gray-100 dark:bg-zinc-800/80 rounded-full px-3 py-1">{GROUP_LABELS[task.group_code]}</span>
      </div>

      <div className="mt-4 text-sm text-gray-600 dark:text-zinc-400">
        <span className="text-gray-400 dark:text-zinc-600 uppercase text-[11px] tracking-widest">Цель: </span>
        {task.goal}
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="bg-gray-50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-3">
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-gray-400 dark:text-zinc-600 mb-1.5">
            <Phone size={12} /> Скрипт звонка
          </div>
          <p className="text-sm text-gray-700 dark:text-zinc-300 leading-relaxed">{task.phone_script}</p>
        </div>
        <div className="bg-gray-50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-3">
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-gray-400 dark:text-zinc-600 mb-1.5">
            <MessageSquare size={12} /> Вариант сообщения
          </div>
          <p className="text-sm text-gray-700 dark:text-zinc-300 leading-relaxed">{task.message_script}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          disabled={busy}
          onClick={() => onOutcome("booked", "phone")}
          className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
        >
          <Check size={14} /> Записан
        </button>
        <button
          disabled={busy}
          onClick={() => onOutcome("no_booking", "phone")}
          className="flex items-center gap-1.5 bg-gray-300 dark:bg-zinc-700 hover:bg-gray-400 dark:hover:bg-zinc-600 text-gray-900 dark:text-white text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
        >
          <X size={14} /> Без записи
        </button>
        <button
          disabled={busy}
          onClick={() => onOutcome("no_answer", "phone")}
          className="flex items-center gap-1.5 bg-gray-200 dark:bg-zinc-800 hover:bg-gray-300 dark:hover:bg-zinc-700 text-gray-700 dark:text-zinc-300 text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
        >
          <Phone size={14} /> Не дозвонились
        </button>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div className="min-h-[40vh] flex items-center justify-center">
      <div className="relative">
        <div className="w-8 h-8 border-2 border-rubl-accent/20 rounded-full" />
        <div className="w-8 h-8 border-2 border-transparent border-t-rubl-accent rounded-full animate-spin absolute inset-0" />
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

function plural(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "а";
  return "ов";
}


// ── Журнал обзвона ──
//
// Результаты звонков лежат в базе, но база — внутри контейнера, и человеку её
// не открыть. Журнал — обычный файл: его видно, можно посчитать в Excel и
// перенести в новую установку.

interface JournalStatus {
  exists: boolean;
  rows: number;
  path: string;
}

function CallJournal({
  role,
  refreshKey,
}: {
  role: "owner" | "operator" | "master";
  refreshKey: number;
}) {
  const [status, setStatus] = useState<JournalStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = async () => {
    try {
      const r = await fetch("/api/client-base/journal/status");
      setStatus(await r.json());
    } catch {
      setStatus(null);
    }
  };

  useEffect(() => {
    load();
  }, [refreshKey]);

  const importJournal = async (file: File) => {
    setUploading(true);
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await fetch("/api/client-base/journal/import", { method: "POST", body: form });
      const body = await r.json();
      if (!r.ok) {
        setMessage(body.detail || "Не удалось загрузить журнал");
      } else {
        setMessage(
          `Добавлено строк: ${body["добавлено"]}, пропущено повторов: ${body["пропущено_дублей"]}`,
        );
        await load();
      }
    } catch {
      setMessage("Не удалось загрузить журнал");
    }
    setUploading(false);
  };

  return (
    <div className="bg-white dark:bg-zinc-900/80 border border-gray-200 dark:border-zinc-800 rounded-2xl p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <FileSpreadsheet size={18} className="text-emerald-500" />
          <div>
            <p className="text-sm font-medium text-gray-800 dark:text-zinc-200">Журнал обзвона</p>
            <p className="text-xs text-gray-500 dark:text-zinc-500">
              {status?.exists
                ? `${status.rows} записей. Файл лежит в папке output рядом с проектом.`
                : "Пока пуст — появится после первого отмеченного звонка."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status?.exists && (
            <a
              href="/api/client-base/journal"
              className="flex items-center gap-2 text-xs text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-white px-3 py-2 rounded-lg border border-gray-200 dark:border-zinc-800 hover:border-rubl-accent transition-all"
            >
              <Download size={14} />
              Скачать Excel
            </a>
          )}
          {role === "owner" && (
            <label
              className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg border border-gray-200 dark:border-zinc-800 transition-all ${
                uploading
                  ? "text-gray-400 dark:text-zinc-600"
                  : "cursor-pointer text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-white hover:border-rubl-accent"
              }`}
            >
              <Upload size={14} />
              {uploading ? "Загружаю…" : "Загрузить журнал"}
              <input
                type="file"
                accept=".xlsx"
                className="hidden"
                disabled={uploading}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) importJournal(file);
                }}
              />
            </label>
          )}
        </div>
      </div>

      {message && (
        <p className="mt-3 text-xs text-gray-600 dark:text-zinc-400">{message}</p>
      )}
    </div>
  );
}
