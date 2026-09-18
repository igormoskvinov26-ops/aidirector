import { useEffect, useState } from "react";
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
  StickyNote,
  Save,
} from "lucide-react";
import { useDark, палитраГрафика, шкалаСегментов } from "./тема";
import { ClientCounters } from "./ClientCounters";
import { MetricChart, type MetricPoint, type ТонГрафика } from "./MetricChart";

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
  /** Заметка администратора, например «перезвонить завтра». Живёт на
   *  клиенте, а не на этой конкретной задаче: задачи обзвона пересобираются
   *  каждый день заново, а заметка должна это пережить. */
  admin_note: string | null;
}

const PERIODS: { id: Period; label: string }[] = [
  { id: "day", label: "День" },
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "quarter", label: "Квартал" },
  { id: "year", label: "Год" },
];

// Шкала сегментов живёт в тема.ts: она зависит от темы, и подбирать её
// пришлось расчётом. Причины и числа — там же.

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
          <p className="text-muted-light dark:text-muted text-sm">Здоровье базы, сегменты и рабочая очередь</p>
        </div>
        <div className="flex items-center gap-1 bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-1">
          <button
            onClick={() => setMode("manager")}
            className={`px-4 py-2 rounded-lg text-sm transition-all ${mode === "manager" ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream font-medium" : "text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"}`}
          >
            Управляющий
          </button>
          <button
            onClick={() => setMode("admin")}
            className={`px-4 py-2 rounded-lg text-sm transition-all ${mode === "admin" ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream font-medium" : "text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"}`}
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
  const тёмная = useDark();
  const шкала = шкалаСегментов(тёмная);
  const [period, setPeriod] = useState<Period>("month");
  const [data, setData] = useState<DashboardData | null>(null);
  const [timeseries, setTimeseries] = useState<TimePoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncState, setSyncState] = useState<{ is_stale: boolean; last_snapshot_at: string | null } | null>(null);
  const [selectedSegment, setSelectedSegment] = useState<string | null>(null);
  const [clients, setClients] = useState<SegmentClient[]>([]);
  const [clientsLoading, setClientsLoading] = useState(false);
  // Динамика по дням для клика на плитку — решение владельца 18.09.2026.
  // Не зависит от периода вверху страницы: у самой истории глубина своя.
  const [metricHistory, setMetricHistory] = useState<Record<string, MetricPoint[]>>({});
  const [selectedMetric, setSelectedMetric] = useState<
    { key: string; label: string; тон: ТонГрафика } | null
  >(null);

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

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/client-base/metric-history");
        if (r.ok) setMetricHistory((await r.json()).series ?? {});
      } catch {
        // молча: это дополнение к графику, не он сам
      }
    })();
  }, []);

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

  // Цвет плиток — статусный, а не «шесть разных оттенков ради различимости».
  //
  // Прежде здесь стояли зелёный, золотой, голубой, песочный, красный и
  // салатовый: голубой и салатовый вне палитры бренда, а шесть равноправных
  // цветов заставляли владельца запоминать, какой что значит.
  //
  // У сегментов есть смысл, и он трёхчастный: хорошо, тревожно, плохо. Его и
  // показываем. Что именно за сегмент, говорят иконка и подпись рядом —
  // различать плитки цветом не требуется, они не марки на одном графике.
  // seg — поле в timeseries с историей по дням для этой плитки. У «Новые»,
  // «Стали постоянными» и «Вернули» такой истории нет: это метрики за период
  // (сколько за месяц/квартал), а не число «на сегодня», и день за днём их
  // пока не считаем — клика на них поэтому нет.
  const cards = [
    { label: "Активная база", value: m?.active_base ?? 0, icon: Users, тон: "профит", seg: "active_base" },
    { label: "Новые", value: m?.new ?? 0, icon: UserPlus, тон: "акцент", seg: null },
    { label: "Стали постоянными", value: m?.became_regular ?? 0, icon: ShieldCheck, тон: "профит", seg: null },
    { label: "В зоне риска", value: m?.at_risk ?? 0, icon: AlertTriangle, тон: "внимание", seg: "risk" },
    { label: "Потеряны", value: m?.lost ?? 0, icon: UserMinus, тон: "убыток", seg: "lost" },
    { label: "Вернули", value: m?.returned ?? 0, icon: RotateCcw, тон: "профит", seg: null },
  ] as const;

  const ТОН: Record<string, string> = {
    профит: "text-profit",
    акцент: "text-bronze dark:text-gold",
    внимание: "text-caution",
    убыток: "text-loss",
  };
  const ТОН_ГРАФИКА: Record<string, ТонГрафика> = {
    профит: "profit",
    убыток: "loss",
    акцент: "accent",
    внимание: "accent",
  };
  const КОЛЬЦО: Record<string, string> = {
    профит: "ring-profit",
    убыток: "ring-loss",
    акцент: "ring-bronze dark:ring-gold",
    внимание: "ring-caution",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-1">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              onClick={() => setPeriod(p.id)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-all ${period === p.id ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream font-medium" : "text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"}`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <button
          onClick={runSync}
          className="flex items-center gap-2 text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream px-3 py-2 rounded-lg border border-milk-line dark:border-line hover:border-bronze dark:hover:border-gold transition-all"
        >
          <RefreshCw size={14} />
          Синхронизировать
        </button>
      </div>

      {/* Те же два счётчика, что на «Записях за месяц» — решение владельца
          18.09.2026. Отдельно от плиток сегментации ниже: «Потеряны» там —
          другая методика (личный цикл клиента), а не тот же показатель. */}
      <ClientCounters
        selected={selectedMetric?.key ?? null}
        onSelect={(key, label, тон) => setSelectedMetric({ key, label, тон })}
      />

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        {cards.map((c) => {
          const key = c.seg ? `segment:${c.seg}` : null;
          const активна = key !== null && selectedMetric?.key === key;
          return (
            <div
              key={c.label}
              onClick={key ? () => setSelectedMetric({ key, label: c.label, тон: ТОН_ГРАФИКА[c.тон] }) : undefined}
              className={`bg-milk-card dark:bg-panel/80 border rounded-2xl p-4 ${key ? "cursor-pointer transition-shadow hover:shadow-md" : ""} ${активна ? `ring-2 border-transparent ${КОЛЬЦО[c.тон]}` : "border-milk-line dark:border-line"}`}
            >
              <div className="flex items-center gap-2 mb-3">
                <c.icon size={16} className={ТОН[c.тон]} />
                <span className="text-muted-light dark:text-muted text-[11px] font-medium uppercase tracking-widest">{c.label}</span>
              </div>
              <div className="text-2xl font-bold tabular-nums">{c.value}</div>
            </div>
          );
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_0.8fr]">
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <Activity
              size={16}
              className={
                !selectedMetric || selectedMetric.тон === "profit"
                  ? "text-profit"
                  : selectedMetric.тон === "loss"
                  ? "text-loss"
                  : "text-bronze dark:text-gold"
              }
            />
            <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              {selectedMetric ? selectedMetric.label : "Пульс базы"}
            </h2>
            {selectedMetric && (
              <button
                onClick={() => setSelectedMetric(null)}
                className="ml-auto text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
              >
                ← Пульс базы
              </button>
            )}
          </div>
          <MetricChart
            points={
              !selectedMetric
                ? timeseries.map((p) => ({ date: p.date, value: p.active_base }))
                : selectedMetric.key.startsWith("segment:")
                ? timeseries.map((p) => ({
                    date: p.date,
                    value: Number((p as unknown as Record<string, number>)[selectedMetric.key.slice(8)] ?? 0),
                  }))
                : metricHistory[selectedMetric.key] ?? []
            }
            label={selectedMetric ? selectedMetric.label : "Активная база"}
            тон={selectedMetric ? selectedMetric.тон : "profit"}
          />
        </div>

        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted mb-4">Баланс движения</h2>
          <div className="flex items-end justify-between gap-4 border-b border-milk-line dark:border-line pb-4">
            <div>
              <div className="text-xs text-muted-light dark:text-muted">Вошли</div>
              <div className="text-3xl font-bold text-profit">+{flow?.inflow ?? 0}</div>
            </div>
            <ArrowRight size={18} className="mb-1 text-muted-light dark:text-muted" />
            <div className="text-right">
              <div className="text-xs text-muted-light dark:text-muted">Вышли</div>
              <div className="text-3xl font-bold text-caution">−{flow?.outflow ?? 0}</div>
            </div>
          </div>
          <div className="mt-4 space-y-2 text-sm">
            <FlowRow label="Новые клиенты" value={`+${flow?.new ?? 0}`} positive />
            <FlowRow label="Вернулись" value={`+${flow?.returned ?? 0}`} positive />
            <FlowRow label="Перешли в риск" value={`−${flow?.became_risk ?? 0}`} />
            <FlowRow label="Стали потерянными" value={`−${flow?.became_lost ?? 0}`} />
          </div>
          <div className="mt-4 rounded-xl bg-milk-deep dark:bg-panel-deep/60 px-4 py-3">
            <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">Чистый прирост</div>
            <div className={`text-2xl font-bold ${(flow?.net ?? 0) >= 0 ? "text-profit" : "text-loss"}`}>
              {(flow?.net ?? 0) >= 0 ? "+" : ""}{flow?.net ?? 0}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted mb-4">Карта сегментов на сегодня</h2>

        <div className="flex h-3 overflow-hidden rounded-full bg-milk-deep dark:bg-panel-deep">
          {(data?.segments ?? []).map((s) => (
            <span key={s.code} style={{ width: `${total ? (s.count / total) * 100 : 0}%`, background: шкала[s.code] }} />
          ))}
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {(data?.segments ?? []).map((s) => (
            <button
              key={s.code}
              onClick={() => openSegment(s.code)}
              className={`bg-milk dark:bg-panel/60 border rounded-xl p-4 text-left transition-all ${selectedSegment === s.code ? "border-bronze dark:border-gold" : "border-milk-line dark:border-line hover:border-milk-line dark:hover:border-line"}`}
            >
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full" style={{ background: шкала[s.code] }} />
                <p className="text-sm font-medium text-ink-soft dark:text-cream">{s.label}</p>
              </div>
              <p className="mt-3 text-2xl font-semibold tabular-nums">{s.count}</p>
              <p className="mt-1 text-xs text-muted-light dark:text-muted">{total ? Math.round((s.count / total) * 100) : 0}% базы</p>
            </button>
          ))}
        </div>

        <p className="mt-4 text-xs text-muted-light dark:text-muted">
          Всего в базе <span className="font-semibold text-ink-soft dark:text-cream">{total}</span> клиентов · нажмите на сегмент, чтобы увидеть список
        </p>
      </div>

      {selectedSegment && (
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <button onClick={() => setSelectedSegment(null)} className="text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream">
                <ChevronLeft size={18} />
              </button>
              <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
                {шкала[selectedSegment] && <span className="mr-2 size-2 rounded-full inline-block" style={{ background: шкала[selectedSegment] }} />}
                {GROUP_LABELS[selectedSegment] || selectedSegment} · {clients.length}
              </h2>
            </div>
          </div>
          {clientsLoading ? (
            <Spinner />
          ) : clients.length === 0 ? (
            <div className="text-muted-light dark:text-muted text-center py-8">Клиентов в этом сегменте нет</div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {clients.map((c) => (
                <div key={c.client_id} className="bg-milk dark:bg-panel/60 border border-milk-line dark:border-line rounded-xl p-4">
                  <div className="font-medium">{c.name || "—"}</div>
                  <div className="text-sm text-muted-light dark:text-muted">{c.phone || "—"}</div>
                  <div className="mt-2 flex items-center gap-3 text-xs text-muted-light dark:text-muted">
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
        <div className="flex items-center gap-2 text-xs text-muted-light dark:text-muted">
          <span className={`size-1.5 rounded-full ${syncState.is_stale ? "bg-loss" : "bg-profit"}`} />
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
      <span className="text-muted-light dark:text-muted">{label}</span>
      <span className={`font-semibold tabular-nums ${positive ? "text-profit" : "text-caution"}`}>{value}</span>
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

  // Заметка живёт на клиенте (см. модель), не на задаче — но обновляем её
  // локально по id задачи: с этой карточки её и правят.
  const saveNote = async (id: number, clientId: number, note: string): Promise<boolean> => {
    try {
      const r = await fetch(`/api/client-base/clients/${clientId}/note`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      });
      if (!r.ok) return false;
      const body = await r.json();
      setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, admin_note: body.admin_note } : t)));
      return true;
    } catch {
      return false;
    }
  };

  const groups = ["due", "risk", "late", "lost"];
  const filtered = filter === "all" ? tasks : tasks.filter((t) => t.group_code === filter);

  const counts: Record<string, number> = {};
  for (const t of tasks) counts[t.group_code] = (counts[t.group_code] || 0) + 1;

  if (loading) return <Spinner />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-1 bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-1 w-fit">
        <button
          onClick={() => setFilter("all")}
          className={`px-3 py-1.5 rounded-lg text-xs transition-all ${filter === "all" ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream" : "text-muted-light dark:text-muted"}`}
        >
          Все ({tasks.length})
        </button>
        {groups.map((g) => (
          <button
            key={g}
            onClick={() => setFilter(g)}
            className={`px-3 py-1.5 rounded-lg text-xs transition-all ${filter === g ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream" : "text-muted-light dark:text-muted"}`}
          >
            {GROUP_LABELS[g]} ({counts[g] || 0})
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 text-sm text-muted-light dark:text-muted">
        <ClipboardList size={16} />
        <span>{filtered.length} клиентов требуют действия</span>
      </div>

      <CallJournal role={role} refreshKey={journalKey} />

      {filtered.length === 0 ? (
        <div className="bg-milk dark:bg-panel/60 border border-milk-line dark:border-line rounded-2xl p-10 text-center text-muted-light dark:text-muted">
          Все задачи обработаны. Так держать!
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((t) => (
            <TaskCard
              key={t.id}
              task={t}
              busy={busy === t.id}
              onOutcome={(o, c) => recordOutcome(t.id, o, c)}
              onSaveNote={(note) => saveNote(t.id, t.client_id, note)}
            />
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
  onSaveNote,
}: {
  task: Task;
  busy: boolean;
  onOutcome: (outcome: string, channel: string) => void;
  onSaveNote: (note: string) => Promise<boolean>;
}) {
  const тёмная = useDark();
  const [noteDraft, setNoteDraft] = useState(task.admin_note ?? "");
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteSaved, setNoteSaved] = useState(false);
  const noteChanged = noteDraft !== (task.admin_note ?? "");

  const handleSaveNote = async () => {
    setNoteSaving(true);
    const ok = await onSaveNote(noteDraft);
    setNoteSaving(false);
    setNoteSaved(ok);
  };
  // Цвет точки — шаг шкалы сегментов. Незнакомый сегмент получает цвет
  // подписей: он ничего не утверждает, а выдумывать шестой шаг нельзя.
  const color = шкалаСегментов(тёмная)[task.group_code] || палитраГрафика(тёмная).ось;
  return (
    <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-5 hover:border-bronze/40 dark:hover:border-gold/40 transition-all">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="size-2.5 rounded-full shrink-0 mt-1" style={{ background: color }} />
          <div>
            <div className="font-semibold text-lg">{task.client_name}</div>
            <div className="text-sm text-muted-light dark:text-muted">{task.phone || "—"}</div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-light dark:text-muted">
              <span>{task.visits_count} визит{plural(task.visits_count)}</span>
              {task.last_visit && <span>· {formatDate(task.last_visit)}</span>}
              {task.last_service && <span>· {task.last_service}</span>}
            </div>
          </div>
        </div>
        <span className="text-xs text-muted-light dark:text-muted bg-milk-deep dark:bg-panel-deep/80 rounded-full px-3 py-1">{GROUP_LABELS[task.group_code]}</span>
      </div>

      <div className="mt-4 text-sm text-muted-light dark:text-muted">
        <span className="text-muted-light dark:text-muted uppercase text-[11px] tracking-widest">Цель: </span>
        {task.goal}
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="bg-milk dark:bg-panel/60 border border-milk-line dark:border-line rounded-xl p-3">
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-muted-light dark:text-muted mb-1.5">
            <Phone size={12} /> Скрипт звонка
          </div>
          <p className="text-sm text-ink-soft dark:text-cream leading-relaxed">{task.phone_script}</p>
        </div>
        <div className="bg-milk dark:bg-panel/60 border border-milk-line dark:border-line rounded-xl p-3">
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-muted-light dark:text-muted mb-1.5">
            <MessageSquare size={12} /> Вариант сообщения
          </div>
          <p className="text-sm text-ink-soft dark:text-cream leading-relaxed">{task.message_script}</p>
        </div>
      </div>

      {/* Заметка администратора: не привязана к сегодняшнему звонку, живёт на
          клиенте и переживает завтрашнюю пересборку очереди — «перезвонить
          завтра», написанное сегодня, снова окажется здесь. */}
      <div className="mt-3 bg-milk dark:bg-panel/60 border border-milk-line dark:border-line rounded-xl p-3">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-muted-light dark:text-muted mb-1.5">
          <StickyNote size={12} /> Комментарий администратора
        </div>
        <textarea
          value={noteDraft}
          onChange={(e) => {
            setNoteDraft(e.target.value);
            setNoteSaved(false);
          }}
          placeholder="например, перезвонить завтра"
          rows={2}
          className="w-full bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-lg px-3 py-2 text-sm text-ink-soft dark:text-cream placeholder:text-muted-light dark:placeholder:text-muted focus:outline-none focus:border-bronze dark:focus:border-gold resize-none"
        />
        <div className="mt-2 flex items-center gap-2">
          <button
            disabled={noteSaving || !noteChanged}
            onClick={handleSaveNote}
            className="flex items-center gap-1.5 border border-milk-line dark:border-line hover:border-bronze dark:hover:border-gold px-3 py-1.5 rounded-lg text-xs transition-all disabled:opacity-40"
          >
            <Save size={12} /> {noteSaving ? "Сохраняю…" : "Сохранить"}
          </button>
          {!noteChanged && noteSaved && <span className="text-xs text-profit">Сохранено</span>}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          disabled={busy}
          onClick={() => onOutcome("booked", "phone")}
          className="flex items-center gap-1.5 bg-profit hover:bg-profit text-milk-card text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
        >
          <Check size={14} /> Записан
        </button>
        <button
          disabled={busy}
          onClick={() => onOutcome("no_booking", "phone")}
          className="flex items-center gap-1.5 bg-milk-line dark:bg-line hover:bg-milk-line dark:hover:bg-line text-ink-soft dark:text-cream text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
        >
          <X size={14} /> Без записи
        </button>
        <button
          disabled={busy}
          onClick={() => onOutcome("no_answer", "phone")}
          className="flex items-center gap-1.5 bg-milk-deep dark:bg-panel-deep hover:bg-milk-line dark:hover:bg-line text-ink-soft dark:text-cream text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
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
        <div className="w-8 h-8 border-2 border-bronze/20 dark:border-gold/20 rounded-full" />
        <div className="w-8 h-8 border-2 border-transparent border-t-bronze dark:border-t-gold rounded-full animate-spin absolute inset-0" />
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
    <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <FileSpreadsheet size={18} className="text-profit" />
          <div>
            <p className="text-sm font-medium text-ink-soft dark:text-cream">Журнал обзвона</p>
            <p className="text-xs text-muted-light dark:text-muted">
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
              className="flex items-center gap-2 text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream px-3 py-2 rounded-lg border border-milk-line dark:border-line hover:border-bronze dark:hover:border-gold transition-all"
            >
              <Download size={14} />
              Скачать Excel
            </a>
          )}
          {role === "owner" && (
            <label
              className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg border border-milk-line dark:border-line transition-all ${
                uploading
                  ? "text-muted-light dark:text-muted"
                  : "cursor-pointer text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream hover:border-bronze dark:hover:border-gold"
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
        <p className="mt-3 text-xs text-muted-light dark:text-muted">{message}</p>
      )}
    </div>
  );
}
