import { Fragment, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
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
  Activity,
  ArrowRight,
  ChevronLeft,
  FileSpreadsheet,
  Upload,
  Download,
  PhoneOff,
  UserRound,
  CalendarClock,
  CheckCircle2,
  XCircle,
  Clock,
  Search,
  LayoutList,
  Table2,
  Columns3,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useDark, палитраГрафика, шкалаСегментов } from "./тема";
import { ClientCounters } from "./ClientCounters";
import { MetricChart, type MetricPoint, type ТонГрафика } from "./MetricChart";
import { Телефон } from "./Телефон";
import { СОБЫТИЕ, забратьФокус } from "./фокус";
import ЖурналОбзвона from "./ЖурналОбзвона";

// ── Types ──
type Period = "day" | "week" | "month" | "quarter" | "year";

interface Flow {
  new: number;
  returned: number;
  at_risk_now: number;
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
  do_not_call?: boolean;
}

interface Task {
  id: number;
  client_id: number;
  client_name: string;
  phone: string | null;
  yclients_url: string | null;
  group_code: string;
  priority: number;
  due_date: string;
  status: string;
  visits_count: number;
  last_visit: string | null;
  /** Дней с последней выполненной записи. */
  days_since_visit: number | null;
  /** Есть запись вперёд. */
  future_booking: boolean;
  /** Сегодня 60-й день без визита и записи нет: дозвонимся — не потеряем. */
  lost_today: boolean;
  last_service: string | null;
  goal: string;
  phone_script: string;
  message_script: string;
  /** Заметка администратора, например «перезвонить завтра». Живёт на
   *  клиенте, а не на этой конкретной задаче: задачи обзвона пересобираются
   *  каждый день заново, а заметка должна это пережить. */
  admin_note: string | null;
  /** Когда дозвонились в последний раз и чем кончилось. Приходит с сервера,
   *  чтобы очередь можно было отсортировать «обзвонённые — вниз». */
  last_call_at: string | null;
  last_call_outcome: string | null;
  called_today: boolean;
  tags: Тег[];
  last_master: { staff_id: number; name: string } | null;
  services: string[];
  contacts: { total: number; year: number; booked: number };
  /** Плановый перезвон: дата, причина и признак «срок настал». */
  next_contact_at: string | null;
  next_contact_note: string | null;
  callback_due: boolean;
  script_source?: string;
  /** Варианты разговора: начало, ветки по причине ухода, завершение. */
  scripts: ВариантСкрипта[];
  call_status: string | null;
  last_call_by: string | null;
  days_since_call: number | null;
  loyalty: string | null;
}

export interface ВариантСкрипта {
  variant: string;
  title: string;
  hint: string;
  phone: string;
  message: string;
}

/** Статусы последнего общения. Ставятся кнопками, вручную не правятся;
 *  в карточке показываются цветным стикером рядом с именем. */
const СТАТУСЫ: { code: string; label: string; chip: string }[] = [
  { code: "booked", label: "Записан", chip: "bg-profit/15 text-profit" },
  { code: "callback", label: "Перезвонить", chip: "bg-bronze/15 text-bronze-ink dark:text-gold" },
  { code: "no_booking", label: "Без записи", chip: "bg-caution/15 text-caution" },
  { code: "no_answer", label: "Не дозвонились", chip: "bg-milk-deep dark:bg-panel-deep text-muted-light dark:text-muted" },
  { code: "do_not_call", label: "Не звонить", chip: "bg-loss/15 text-loss" },
];

const ЛАМПЫ: { code: string; color: string; title: string }[] = [
  { code: "green", color: "#2f9e5f", title: "Лояльный: разговор прошёл тепло" },
  { code: "yellow", color: "#d0a03c", title: "Нейтральный" },
  { code: "red", color: "#e0564b", title: "Разговор был на негативе" },
];

/** Палитра для новых тегов: админ создаёт тег одной кнопкой, цвет берём сами. */
const ЦВЕТА_ТЕГОВ = ["#9a6a36", "#1f6e41", "#8a6412", "#a83329", "#4a6fa5", "#6b4a8f"];

export interface Тег {
  id: number;
  code: string;
  name: string;
  color: string | null;
  exclude_from_calls: boolean;
  promo: boolean;
  clients?: number;
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
  callback: "Перезвонить",
  new: "Новые",
  became_regular: "Стали постоянными",
  returned: "Вернули",
  due: "Пора записываться",
  risk: "Зона риска",
  late: "Сильно задерживаются",
  lost: "Потерянные",
  manual: "Из поиска",
  losing: "Теряем сегодня",
};

/** Число дней с последней записи — крупно и цветом: сколько ещё до потери. */
export function Дни({ task, компактно = false }: { task: { days_since_visit: number | null; lost_today: boolean }; компактно?: boolean }) {
  const д = task.days_since_visit;
  if (д == null) return <span className="text-muted-light dark:text-muted">—</span>;
  const цвет = task.lost_today
    ? "bg-loss text-milk-card shadow-[0_0_12px_rgba(224,86,75,0.55)]"
    : д > 60
      ? "bg-loss/15 text-loss"
      : д >= 45
        ? "bg-caution/15 text-caution"
        : "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream";
  const подсказка = task.lost_today ? "Сегодня 60-й день без визита: запишем сегодня — не попадёт в потерянные" : `${д} дн. с последней записи`;
  if (компактно)
    return (
      <span title={подсказка} className={`inline-flex items-baseline gap-1 rounded-lg px-2 py-1 tabular-nums ${цвет}`}>
        <b className="text-lg leading-none">{д}</b>
        <span className="text-[10px] opacity-80">дн.</span>
      </span>
    );
  return (
    <span
      title={подсказка}
      className={`inline-flex min-w-[4rem] flex-col items-center justify-center rounded-xl px-2.5 py-2 tabular-nums leading-none ${цвет}`}
    >
      <b className="text-2xl">{д}</b>
      <span className="mt-0.5 text-[9px] uppercase tracking-wider opacity-80">{task.lost_today ? "теряем" : "дн."}</span>
    </span>
  );
}

type Админ = { staff_id: number; name: string };

type Режим = "manager" | "admin" | "returned" | "calls";

const ВКЛАДКИ: { id: Режим; label: string }[] = [
  { id: "manager", label: "Сводка" },
  { id: "admin", label: "Клиентская база" },
  // Возвращённые — по ним считается мотивация администраторов (11.10.2026).
  { id: "returned", label: "Возвращённые" },
  { id: "calls", label: "Журнал обзвона" },
];

export default function ClientBasePage({ role }: { role: "owner" | "operator" | "master" }) {
  const [mode, setMode] = useState<Режим>(role === "operator" ? "admin" : "manager");
  const [былаБаза, setБылаБаза] = useState(false);
  useEffect(() => { if (mode === "admin") setБылаБаза(true); }, [mode]);
  // «К клиенту» из журнала обзвона — открыть базу.
  useEffect(() => {
    const on = () => setMode("admin");
    window.addEventListener(СОБЫТИЕ, on);
    return () => window.removeEventListener(СОБЫТИЕ, on);
  }, []);

  return (
    <div className="animate-in">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Клиентская база</h1>
        <div className="flex items-center gap-1 bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-1">
          {ВКЛАДКИ.map((в) => (
            <button
              key={в.id}
              onClick={() => setMode(в.id)}
              className={`px-4 py-2 rounded-lg text-sm transition-all ${mode === в.id ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream font-medium" : "text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"}`}
            >
              {в.label}
            </button>
          ))}
        </div>
      </div>

      {mode === "calls" ? (
        <ЖурналОбзвона role={role} />
      ) : mode === "returned" ? (
        <ВозвращённыеView />
      ) : mode === "manager" ? (
        <ManagerView />
      ) : null}
      {/* База, раз открытая, остаётся загруженной: переход к клиенту из
          журнала — мгновенный, без повторной выгрузки тысяч строк. */}
      {былаБаза && (
        <div hidden={mode !== "admin"}>
          <РабочееМесто role={role} видим={mode === "admin"} />
        </div>
      )}
    </div>
  );
}

// Кто звонит — спрашиваем при каждом открытии Пульта (решение владельца
// 04.10.2026): за стойкой админы меняются. Между вкладками выбор помнится,
// перезагрузка страницы спрашивает снова.
let запомненныйАдмин: number | null = null;

/** Обзвон администратора: выбор себя → очередь с поиском по телефону. */
export function РабочееМесто({ role, видим = true }: { role: "owner" | "operator" | "master"; видим?: boolean }) {
  const [admins, setAdmins] = useState<Админ[] | null>(null);
  const [adminId, setAdminIdRaw] = useState<number | null>(запомненныйАдмин);
  const setAdminId = (id: number | null) => {
    запомненныйАдмин = id;
    setAdminIdRaw(id);
  };
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/client-base/admins");
        setAdmins(r.ok ? await r.json() : []);
      } catch {
        setAdmins([]);
      }
    })();
  }, []);
  const выбранный = admins?.find((a) => a.staff_id === adminId) ?? null;

  if (admins === null) return <Spinner />;
  // Обзвон пишется на конкретного админа: пока он себя не выбрал, базы не видно.
  if (admins.length > 0 && !выбранный) return <ВыборАдмина admins={admins} onPick={setAdminId} />;
  return <AdminView role={role} выбранный={выбранный} видим={видим} onChangeAdmin={() => setAdminId(null)} />;
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
    setSelectedSegment(null); // список «за период» от прежнего периода больше не верен
  }, [period]);
  const списокРеф = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selectedSegment) списокРеф.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selectedSegment]);

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
      const r = await fetch(`/api/client-base/clients?segment=${code}&period=${period}`);
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
  // seg — поле в timeseries с историей по дням: клик показывает график.
  // list — у «Новые», «Стали постоянными», «Вернули» истории по дням нет (это
  // события за период), поэтому клик открывает список этих клиентов.
  // Решение владельца 04.10.2026: кликабельны все плитки.
  const cards = [
    { label: "Активная база", value: m?.active_base ?? 0, icon: Users, тон: "профит", seg: "active_base", list: null },
    { label: "Новые", value: m?.new ?? 0, icon: UserPlus, тон: "акцент", seg: null, list: "new" },
    { label: "Стали постоянными", value: m?.became_regular ?? 0, icon: ShieldCheck, тон: "профит", seg: null, list: "became_regular" },
    { label: "В зоне риска", value: m?.at_risk ?? 0, icon: AlertTriangle, тон: "внимание", seg: "risk", list: null },
    { label: "Потеряны", value: m?.lost ?? 0, icon: UserMinus, тон: "убыток", seg: "lost", list: null },
    { label: "Вернули", value: m?.returned ?? 0, icon: RotateCcw, тон: "профит", seg: null, list: "returned" },
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
          const активна = (key !== null && selectedMetric?.key === key) || (c.list !== null && selectedSegment === c.list);
          return (
            <button
              key={c.label}
              onClick={() => (key ? setSelectedMetric({ key, label: c.label, тон: ТОН_ГРАФИКА[c.тон] }) : c.list && openSegment(c.list))}
              title={key ? "Показать динамику" : "Показать список клиентов за период"}
              className={`text-left bg-milk-card dark:bg-panel/80 border rounded-2xl p-4 cursor-pointer transition-shadow hover:shadow-md ${активна ? `ring-2 border-transparent ${КОЛЬЦО[c.тон]}` : "border-milk-line dark:border-line"}`}
            >
              <div className="flex items-center gap-2 mb-3">
                <c.icon size={16} className={ТОН[c.тон]} />
                <span className="text-muted-light dark:text-muted text-[11px] font-medium uppercase tracking-widest">{c.label}</span>
              </div>
              <div className="text-2xl font-bold tabular-nums">{c.value}</div>
            </button>
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
            <FlowRow label="Стали потерянными" value={`−${flow?.became_lost ?? 0}`} />
          </div>
          {/* Зона риска — состояние, а не выход: клиент ещё наш, поэтому в
              арифметику баланса не входит (правка 16.10.2026). */}
          <div className="mt-2 flex items-center justify-between text-sm text-muted-light dark:text-muted">
            <span>Сейчас в зоне риска</span>
            <span className="tabular-nums text-caution">{flow?.at_risk_now ?? 0}</span>
          </div>
          <div className="mt-4 rounded-xl bg-milk-deep dark:bg-panel-deep/60 px-4 py-3">
            <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
              Чистый прирост <span className="normal-case tracking-normal">= пульс базы за период</span>
            </div>
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
        <div ref={списокРеф} className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6 scroll-mt-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <button onClick={() => setSelectedSegment(null)} className="text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream">
                <ChevronLeft size={18} />
              </button>
              <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
                {шкала[selectedSegment] && <span className="mr-2 size-2 rounded-full inline-block" style={{ background: шкала[selectedSegment] }} />}
                {GROUP_LABELS[selectedSegment] || selectedSegment}
                {["new", "became_regular", "returned"].includes(selectedSegment) && ` за ${PERIODS.find((x) => x.id === period)?.label.toLowerCase()}`} · {clients.length}
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
                  <div className="flex items-center gap-2 font-medium">
                    {c.name || "—"}
                    {c.do_not_call && (
                      <span className="inline-flex items-center gap-1 rounded border border-loss/40 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-loss">
                        <PhoneOff size={10} /> не звонить
                        <button
                          title="Снять пометку"
                          className="ml-1 underline normal-case"
                          onClick={async () => {
                            const r = await fetch(`/api/client-base/clients/${c.client_id}/do-not-call`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ value: false }),
                            });
                            if (r.ok) setClients((prev) => prev.map((x) => (x.client_id === c.client_id ? { ...x, do_not_call: false } : x)));
                          }}
                        >
                          снять
                        </button>
                      </span>
                    )}
                  </div>
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

function ВыборАдмина({ admins, onPick }: { admins: Админ[]; onPick: (id: number) => void }) {
  return (
    <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel/80 p-8 text-center">
      <UserRound size={28} className="mx-auto mb-3 text-bronze dark:text-gold" />
      <h2 className="text-lg font-semibold text-ink-soft dark:text-cream">Кто сегодня звонит?</h2>
      <p className="mt-1 text-sm text-muted-light dark:text-muted">
        Выберите себя — база откроется, и каждый звонок запишется на вас.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        {admins.map((a) => (
          <button
            key={a.staff_id}
            onClick={() => onPick(a.staff_id)}
            className="min-w-[10rem] rounded-xl border border-milk-line dark:border-line px-6 py-4 text-base font-medium hover:border-bronze dark:hover:border-gold hover:bg-milk-deep dark:hover:bg-panel-deep transition-all"
          >
            {a.name}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Строка всей клиентской базы (GET /api/client-base/base). */
interface БазаСтрока {
  client_id: number;
  name: string;
  phone: string | null;
  yclients_url: string | null;
  group_code: string;
  task_id: number | null;
  in_queue: boolean;
  called_today: boolean;
  priority: number;
  visits_count: number;
  last_visit: string | null;
  days_since_visit: number | null;
  future_booking: boolean;
  lost_today: boolean;
  call_status: string | null;
  last_call_at: string | null;
  last_call_by: string | null;
  next_contact_at: string | null;
  callback_due: boolean;
  tags: Тег[];
  last_master: { staff_id: number; name: string } | null;
  loyalty: string | null;
  admin_note: string | null;
  do_not_call: boolean;
}

const ПАЧКА = 200;

function AdminView({
  role, выбранный, видим, onChangeAdmin,
}: {
  role: "owner" | "operator" | "master";
  выбранный: Админ | null;
  видим: boolean;
  onChangeAdmin: () => void;
}) {
  const [строки, setСтроки] = useState<БазаСтрока[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [карточки, setКарточки] = useState<Record<number, Task>>({});
  const [открыта, setОткрыта] = useState<number | null>(null);
  const [фокус, setФокус] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [сбойБазы, setСбойБазы] = useState<string | null>(null);
  const [сбойКарточки, setСбойКарточки] = useState<Record<number, string>>({});
  const [filter, setFilter] = useState<string>("all");
  const [busy, setBusy] = useState<number | null>(null);
  const тёмнаяАдмин = useDark();
  const [теги, setТеги] = useState<Тег[]>([]);
  const [ошибки, setОшибки] = useState<Record<number, string>>({});
  const [поиск, setПоиск] = useState("");
  const цифрыПоиска = поиск.replace(/\D/g, "");
  const [фильтры, setФильтры] = useState<Record<string, string>>({});
  const [показано, setПоказано] = useState(ПАЧКА);
  // Представление: таблица всей базы или лента карточек сегодняшней очереди
  // (запрос владельца 29.10.2026). Выбор помнится в этом браузере.
  const [видны, setВидны] = useКолонки();
  const [вид, setВидRaw] = useState<"table" | "cards">(() => {
    try { return localStorage.getItem("rubl-queue-view") === "cards" ? "cards" : "table"; } catch { return "table"; }
  });
  const setВид = (v: "table" | "cards") => {
    setВидRaw(v);
    try { localStorage.setItem("rubl-queue-view", v); } catch { /* не критично */ }
  };
  const [сорт, setСорт] = useState<Сортировка>({ key: null, dir: -1 });

  const послать = async (url: string, тело: unknown, clientId: number): Promise<boolean> => {
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(тело),
      });
      if (!r.ok) {
        let текст = `Сервер ответил ${r.status}`;
        try {
          текст = (await r.json()).detail || текст;
        } catch {
          /* тело не json — оставляем код ответа */
        }
        setОшибки((п) => ({ ...п, [clientId]: текст }));
        return false;
      }
      setОшибки((п) => {
        const { [clientId]: _, ...прочие } = п;
        return прочие;
      });
      return true;
    } catch {
      setОшибки((п) => ({ ...п, [clientId]: "Пульт не отвечает — проверьте, запущен ли он" }));
      return false;
    }
  };
  const админ = encodeURIComponent(выбранный?.name ?? "");

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/client-base/tags");
        setТеги(r.ok ? await r.json() : []);
      } catch {
        setТеги([]);
      }
    })();
  }, []);

  const загрузитьКарточку = async (clientId: number) => {
    try {
      const r = await fetch(`/api/client-base/clients/${clientId}/card?admin=${админ}`);
      if (r.ok) {
        const к: Task = await r.json();
        setКарточки((п) => ({ ...п, [clientId]: к }));
        setСбойКарточки((п) => { const { [clientId]: _, ...прочие } = п; return прочие; });
      } else {
        // Не крутить загрузку вечно: сказать, что карточка не открылась.
        setСбойКарточки((п) => ({ ...п, [clientId]: `Карточка не открылась: сервер ответил ${r.status}` }));
      }
    } catch {
      setСбойКарточки((п) => ({ ...п, [clientId]: "Карточка не открылась: Пульт не отвечает" }));
    }
  };

  /** Перечитать базу (и очередь для ленты, и открытую карточку). */
  const обновить = async (спиннер = false, clientId?: number) => {
    if (спиннер) setLoading(true);
    try {
      const r = await fetch("/api/client-base/base");
      // Не ответила — оставляем то, что уже на экране, и говорим об этом.
      // Раньше сбой обновления стирал таблицу: найденный клиент «пропадал».
      if (!r.ok) throw new Error(`сервер ответил ${r.status}`);
      const d: { rows: БазаСтрока[]; yclients_url: string | null } = await r.json();
      // Ссылку в YCLIENTS собираем здесь из одного шаблона: в каждой строке
      // ответа она раздувала его в пять раз.
      for (const s of d.rows) {
        const ц = (s.phone ?? "").replace(/\D/g, "").slice(-10);
        s.yclients_url = d.yclients_url && ц.length === 10 ? d.yclients_url.replace("{phone}", "8" + ц) : null;
      }
      setСтроки(d.rows);
      setСбойБазы(null);
    } catch (e) {
      setСбойБазы(`База не обновилась (${e instanceof Error ? e.message : "нет связи"}) — показаны прежние данные`);
    }
    if (вид === "cards") {
      try {
        const r = await fetch(`/api/client-base/tasks?status=open&admin=${админ}`);
        if (r.ok) setTasks(await r.json());
      } catch { /* очередь остаётся прежней */ }
    }
    const к = clientId ?? открыта;
    if (к != null) await загрузитьКарточку(к);
    setLoading(false);
  };

  useEffect(() => {
    обновить(true);
  }, [вид]);

  // Вкладку снова открыли — тихо подтянуть свежее, показывая то, что уже есть.
  const первый = useRef(true);
  useEffect(() => {
    if (первый.current) { первый.current = false; return; }
    if (видим) обновить(false);
  }, [видим]);

  // Переход из журнала обзвона: показать этого клиента раскрытым.
  useEffect(() => {
    const применить = (id: number | null) => {
      if (id == null) return;
      setВид("table");
      setФокус(id);
      setОткрыта(id);
      загрузитьКарточку(id);
    };
    применить(забратьФокус());
    const on = () => применить(забратьФокус());
    window.addEventListener(СОБЫТИЕ, on);
    return () => window.removeEventListener(СОБЫТИЕ, on);
  }, []);

  const раскрыть = (clientId: number) => {
    if (открыта === clientId) {
      setОткрыта(null);
      return;
    }
    setОткрыта(clientId);
    загрузитьКарточку(clientId);
  };

  /** Номер задачи для кнопок: клиента не из очереди сначала ставим в неё. */
  const задачаДля = async (карточка: Task): Promise<number | null> => {
    if (карточка.id) return карточка.id;
    try {
      const r = await fetch(`/api/client-base/clients/${карточка.client_id}/open`, { method: "POST" });
      return r.ok ? (await r.json()).task_id : null;
    } catch {
      return null;
    }
  };

  const recordOutcome = async (карточка: Task, outcome: string, channel: string,
                               next_contact?: string | null, comment?: string) => {
    const cid = карточка.client_id;
    setBusy(cid);
    const id = await задачаДля(карточка);
    if (id == null) {
      setОшибки((п) => ({ ...п, [cid]: "Не удалось поставить клиента в очередь" }));
      setBusy(null);
      return;
    }
    const ок = await послать(`/api/client-base/tasks/${id}/outcome`, {
      outcome,
      channel,
      next_contact: next_contact ?? null,
      comment: comment ?? null,
      actor_id: выбранный?.name ?? "admin",
      admin_staff_id: выбранный?.staff_id ?? null,
    }, cid);
    if (ок) await обновить(false, cid);
    setBusy(null);
  };

  const запланировать = async (clientId: number, дата: string | null, заметка: string) => {
    if (await послать(`/api/client-base/clients/${clientId}/next-contact`,
                      { date: дата, note: заметка, actor: выбранный?.name ?? "admin" }, clientId)) {
      await обновить(false, clientId);
    }
  };

  const светофор = async (clientId: number, value: string) => {
    if (await послать(`/api/client-base/clients/${clientId}/loyalty`,
                      { value, actor: выбранный?.name ?? "admin" }, clientId)) {
      await обновить(false, clientId);
    }
  };

  const переключитьТег = async (clientId: number, tagId: number, value: boolean) => {
    if (await послать(`/api/client-base/clients/${clientId}/tags/${tagId}`,
                      { value, actor: выбранный?.name ?? "admin" }, clientId)) {
      await обновить(false, clientId);
    }
  };

  /** Новый тег заводит сам администратор — прямо в строке тегов на карточке. */
  const создатьТег = async (clientId: number, name: string) => {
    try {
      const r = await fetch("/api/client-base/tags", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          code: `t${Date.now().toString(36)}`,
          color: ЦВЕТА_ТЕГОВ[теги.length % ЦВЕТА_ТЕГОВ.length],
        }),
      });
      if (!r.ok) return;
      const тег = await r.json();
      setТеги((прежние) => [...прежние, тег]);
      await переключитьТег(clientId, тег.id, true);
    } catch { /* тег не создан — кнопка просто ничего не сделала */ }
  };

  const saveNote = async (clientId: number, note: string): Promise<boolean> => {
    try {
      const r = await fetch(`/api/client-base/clients/${clientId}/note`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      });
      if (!r.ok) return false;
      await обновить(false, clientId);
      return true;
    } catch {
      return false;
    }
  };

  const совпадает = (phone: string | null) => {
    const ц = (phone ?? "").replace(/\D/g, "");
    return ц.includes(цифрыПоиска) || (цифрыПоиска[0] === "8" && ц.includes("7" + цифрыПоиска.slice(1)));
  };
  const подЧип = (r: { in_queue: boolean; lost_today: boolean; called_today: boolean; callback_due: boolean; group_code: string }) =>
    filter === "all" ? true
      : filter === "queue" ? r.in_queue
        : filter === "lost_today" ? r.lost_today && !r.called_today
          : filter === "callback" ? r.callback_due
            : r.group_code === filter;

  // Поиск и переход из журнала важнее чипов: ищут конкретного человека.
  const отобраны = фокус != null
    ? строки.filter((r) => r.client_id === фокус)
    : цифрыПоиска
      ? строки.filter((r) => совпадает(r.phone))
      : строки.filter((r) => подЧип(r) && подходит(r, фильтры));
  const упорядочено = отсортироватьБазу(отобраны, сорт);
  // Поиск по телефону всегда ищет по всей базе и показывает таблицу — даже
  // в ленте карточек, где видна только сегодняшняя очередь. Иначе клиент не
  // из очереди «не находился» (замечание 02.11.2026: салон работает лентой).
  const таблицей = вид === "table" || !!цифрыПоиска;

  const сколько = (f: (r: БазаСтрока) => boolean) => строки.filter(f).length;
  const чипы = [
    { code: "all", label: "Вся база", n: строки.length },
    { code: "queue", label: "Обзвон сегодня", n: сколько((r) => r.in_queue) },
    { code: "callback", label: "Перезвонить", n: сколько((r) => r.callback_due) },
    ...["due", "risk", "late", "lost"].map((g) => ({ code: g, label: GROUP_LABELS[g], n: сколько((r) => r.group_code === g) })),
  ].filter((ч) => ч.code === "all" || ч.n > 0 || filter === ч.code);
  const теряем = сколько((r) => r.lost_today && !r.called_today);
  const осталось = сколько((r) => r.in_queue && !r.called_today);

  if (loading) return <Spinner />;

  const шкала = шкалаСегментов(тёмнаяАдмин);
  const карточкаЗадачи = (t: Task) => (
    <TaskCard
      key={t.client_id}
      task={t}
      busy={busy === t.client_id}
      onOutcome={(o, c, дата, коммент) => recordOutcome(t, o, c, дата, коммент)}
      onSaveNote={(note) => saveNote(t.client_id, note)}
      теги={теги}
      onTag={(tagId, value) => переключитьТег(t.client_id, tagId, value)}
      onPlan={(дата, заметка) => запланировать(t.client_id, дата, заметка)}
      onLoyalty={(цвет) => светофор(t.client_id, цвет)}
      onCreateTag={(имя) => создатьТег(t.client_id, имя)}
      ошибка={ошибки[t.client_id]}
    />
  );

  return (
    <div className="space-y-4">
      {/* Поиск — главное на экране: клиент звонит сам, и его надо найти за секунды. */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative flex-1 min-w-[260px]">
          <Search size={18} className="pointer-events-none absolute left-3.5 top-1/2 z-10 -translate-y-1/2 text-muted-light dark:text-muted" />
          <input
            value={поиск}
            onChange={(e) => { setПоиск(e.target.value); setФокус(null); setПоказано(ПАЧКА); }}
            inputMode="tel"
            placeholder="Поиск по телефону — любые цифры, например последние 4"
            className="w-full rounded-xl border border-milk-line dark:border-line bg-white dark:bg-panel/80 pl-10 pr-10 py-3 text-base text-ink-soft dark:text-cream placeholder:text-muted-light dark:placeholder:text-muted focus:outline-none focus:border-bronze dark:focus:border-gold"
          />
          {поиск && (
            <button onClick={() => setПоиск("")} aria-label="Очистить поиск"
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream">
              <X size={18} />
            </button>
          )}
        </label>
        {выбранный && (
          <div className="flex items-center gap-2 text-sm text-muted-light dark:text-muted">
            <span>Звонит <b className="text-ink-soft dark:text-cream">{выбранный.name}</b></span>
            <button onClick={onChangeAdmin} className="underline underline-offset-2 hover:text-ink-soft dark:hover:text-cream">
              сменить
            </button>
          </div>
        )}
      </div>

      {сбойБазы && (
        <div className="rounded-xl border border-loss/40 bg-loss/5 px-4 py-2 text-sm text-loss">{сбойБазы}</div>
      )}
      {фокус != null ? (
        <div className="flex items-center gap-3 rounded-xl border border-bronze/40 bg-bronze/5 px-4 py-2 text-sm">
          <span>Клиент из журнала обзвона</span>
          <button onClick={() => { setФокус(null); setОткрыта(null); }} className="underline underline-offset-2">
            показать всю базу
          </button>
        </div>
      ) : !цифрыПоиска && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {(теряем > 0 || filter === "lost_today") && (
            <button
              onClick={() => setFilter(filter === "lost_today" ? "all" : "lost_today")}
              title="Сегодня 60-й день без визита и записи нет. Запишем сегодня — не попадут в потерянные за день"
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 font-semibold transition-all ${
                filter === "lost_today" ? "bg-loss text-milk-card" : "bg-loss/15 text-loss hover:bg-loss/25"
              }`}
            >
              Теряем сегодня <b className="tabular-nums">{теряем}</b>
            </button>
          )}
          {чипы.map((g) => (
            <button
              key={g.code}
              onClick={() => { setFilter(g.code); setПоказано(ПАЧКА); }}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 transition-all ${
                filter === g.code
                  ? "border-bronze dark:border-gold bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream"
                  : "border-milk-line dark:border-line bg-milk-card dark:bg-panel text-ink-soft/80 dark:text-cream/80 hover:border-bronze/60 dark:hover:border-gold/60"
              }`}
            >
              {шкала[g.code] && <span className="size-2 rounded-full" style={{ background: шкала[g.code] }} />}
              {g.label}
              <b className="tabular-nums">{g.n}</b>
            </button>
          ))}
          <span className="ml-auto text-sm text-muted-light dark:text-muted">в очереди осталось обзвонить <b className="text-ink-soft dark:text-cream tabular-nums">{осталось}</b></span>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-light dark:text-muted">
        <span>
          {таблицей ? `${упорядочено.length} клиент${plural(упорядочено.length)}` : `${tasks.length} в очереди на сегодня`}
          {Object.values(фильтры).some(Boolean) && таблицей && (
            <button onClick={() => setФильтры({})} className="ml-3 inline-flex items-center gap-1 underline underline-offset-2">
              <X size={12} /> сбросить фильтры колонок
            </button>
          )}
        </span>
        <span className="flex items-center gap-2">
        {таблицей && <ВыборКолонок видны={видны} setВидны={setВидны} />}
        <button
          onClick={() => setВид(вид === "table" ? "cards" : "table")}
          title={вид === "table" ? "Лента карточек сегодняшней очереди" : "Таблица всей базы"}
          className="inline-flex items-center gap-1.5 rounded-lg border border-milk-line dark:border-line px-3 py-1.5 text-xs text-ink-soft dark:text-cream hover:border-bronze dark:hover:border-gold"
        >
          {вид === "table" ? <LayoutList size={14} /> : <Table2 size={14} />}
          Поменять представление
        </button>
        </span>
      </div>

      {таблицей ? (
        упорядочено.length === 0 && !Object.values(фильтры).some(Boolean) ? (
          <div className="rounded-2xl border border-milk-line dark:border-line p-10 text-center text-muted-light dark:text-muted">
            {цифрыПоиска ? "Клиент с такими цифрами не найден" : "Здесь пусто"}
          </div>
        ) : (
          <>
            <ТаблицаБазы
              видны={видны}
              видим={видим}
              строки={упорядочено.slice(0, показано)}
              варианты={строки}
              сорт={сорт}
              setСорт={setСорт}
              фильтры={фильтры}
              setФильтры={(ф) => { setФильтры(ф); setПоказано(ПАЧКА); }}
              открыта={открыта}
              раскрыть={раскрыть}
              карточка={(cid) => (карточки[cid] ? карточкаЗадачи(карточки[cid])
                : сбойКарточки[cid] ? <div className="rounded-xl border border-loss/40 bg-loss/5 px-4 py-3 text-sm text-loss">{сбойКарточки[cid]}</div>
                  : <Spinner />)}
            />
            {упорядочено.length > показано && (
              <button onClick={() => setПоказано(показано + ПАЧКА)}
                      className="w-full rounded-xl border border-milk-line dark:border-line py-2 text-sm text-muted-light dark:text-muted hover:border-bronze dark:hover:border-gold">
                Показать ещё {Math.min(ПАЧКА, упорядочено.length - показано)} из {упорядочено.length - показано}
              </button>
            )}
          </>
        )
      ) : tasks.length === 0 ? (
        <div className="rounded-2xl border border-milk-line dark:border-line p-10 text-center text-muted-light dark:text-muted">
          Все задачи обработаны. Так держать!
        </div>
      ) : (
        <div className="space-y-3">
          {отсортировать(tasks.filter((t) => !цифрыПоиска || совпадает(t.phone)).filter((t) => подЧип({ ...t, in_queue: true })), сорт)
            .map((t) => карточкаЗадачи(t))}
        </div>
      )}
      {role === "owner" && <CallJournal role={role} refreshKey={0} />}
    </div>
  );
}

type Сортировка = { key: string | null; dir: 1 | -1 };

/** Лента очереди сортируется только по дням с последней записи. */
function отсортировать(tasks: Task[], сорт: Сортировка): Task[] {
  if (сорт.key !== "days") return tasks;
  return [...tasks].sort((a, b) => ((a.days_since_visit ?? -1) - (b.days_since_visit ?? -1)) * сорт.dir);
}

const статусЗвонка = (code: string | null) => СТАТУСЫ.find((x) => x.code === code);
const ГРУППЫ_ВСЕ: Record<string, string> = { ...GROUP_LABELS, active: "Активные", no_visits: "Без визитов" };

/** Колонки таблицы базы. Основные видны сразу, остальные — через «+».
 *  ``текст`` — по нему фильтр колонки; ``список`` — фильтр выпадающим списком. */
const КОЛОНКИ: {
  id: string;
  label: string;
  основная: boolean;
  список?: boolean;
  ключ: (r: БазаСтрока) => number | string;
  текст: (r: БазаСтрока) => string;
  ячейка: (r: БазаСтрока) => ReactNode;
}[] = [
  { id: "days", label: "Дней", основная: true, ключ: (r) => r.days_since_visit ?? -1,
    текст: (r) => String(r.days_since_visit ?? ""), ячейка: (r) => <Дни task={r} компактно /> },
  { id: "last_visit", label: "Последняя запись", основная: true, ключ: (r) => r.last_visit ?? "",
    текст: (r) => (r.last_visit ? formatDate(r.last_visit) : ""), ячейка: (r) => (r.last_visit ? formatDate(r.last_visit) : "—") },
  { id: "name", label: "Имя", основная: true, ключ: (r) => r.name ?? "", текст: (r) => r.name ?? "",
    ячейка: (r) => (
      <span className="flex items-center gap-2">
        <span className="text-base font-semibold text-ink-soft dark:text-cream">{r.name}</span>
        {r.lost_today && !r.called_today && (
          <span className="rounded-full bg-loss px-2 py-0.5 text-[10px] font-bold uppercase text-milk-card">теряем сегодня</span>
        )}
        {r.do_not_call && <span className="text-[10px] font-bold uppercase text-loss">не звонить</span>}
      </span>
    ) },
  { id: "phone", label: "Телефон", основная: true, ключ: (r) => r.phone ?? "", текст: (r) => r.phone ?? "",
    ячейка: (r) => <Телефон phone={r.phone} yclientsUrl={r.yclients_url} крупно /> },
  { id: "group", label: "Группа", основная: true, список: true, ключ: (r) => ГРУППЫ_ВСЕ[r.group_code] ?? r.group_code,
    текст: (r) => ГРУППЫ_ВСЕ[r.group_code] ?? r.group_code,
    ячейка: (r) => (
      <span className="inline-flex items-center gap-1.5 text-[13px] text-ink-soft/85 dark:text-cream/85">
        {r.in_queue && <span className="size-1.5 shrink-0 rounded-full bg-bronze dark:bg-gold" title="В очереди обзвона на сегодня" />}
        {ГРУППЫ_ВСЕ[r.group_code] ?? r.group_code}
      </span>
    ) },
  { id: "status", label: "Статус", основная: true, список: true, ключ: (r) => r.call_status ?? "",
    текст: (r) => статусЗвонка(r.call_status)?.label ?? "Не звонили",
    ячейка: (r) => {
      const с = статусЗвонка(r.call_status);
      return с
        ? <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${с.chip}`}>{с.label}</span>
        : <span className="text-[13px] text-muted-light dark:text-muted">Не звонили</span>;
    } },
  { id: "last_call", label: "Последний звонок", основная: true, ключ: (r) => r.last_call_at ?? "",
    текст: (r) => (r.last_call_at ? formatDate(r.last_call_at.slice(0, 10)) : ""),
    ячейка: (r) => (r.last_call_at ? formatDate(r.last_call_at.slice(0, 10)) : "—") },
  { id: "next", label: "След. звонок", основная: true, ключ: (r) => r.next_contact_at ?? "",
    текст: (r) => (r.next_contact_at ? formatDate(r.next_contact_at) : ""),
    ячейка: (r) => (r.next_contact_at ? formatDate(r.next_contact_at) : "—") },
  { id: "tags", label: "Хэштеги", основная: true, список: true, ключ: (r) => r.tags.map((x) => x.name).join(" "),
    текст: (r) => r.tags.map((x) => x.name).join(" "),
    ячейка: (r) => (
      <span className="flex flex-wrap gap-1">
        {r.tags.map((x) => <span key={x.id} className="text-xs font-medium" style={{ color: x.color ?? undefined }}>#{x.name}</span>)}
      </span>
    ) },
  { id: "last_call_by", label: "Кто звонил", основная: false, список: true, ключ: (r) => r.last_call_by ?? "",
    текст: (r) => r.last_call_by ?? "", ячейка: (r) => r.last_call_by ?? "—" },
  { id: "master", label: "Мастер", основная: false, список: true, ключ: (r) => r.last_master?.name ?? "",
    текст: (r) => r.last_master?.name ?? "", ячейка: (r) => r.last_master?.name ?? "—" },
  { id: "visits", label: "Визитов", основная: false, ключ: (r) => r.visits_count,
    текст: (r) => String(r.visits_count), ячейка: (r) => r.visits_count },
  { id: "future", label: "Запись вперёд", основная: false, список: true, ключ: (r) => (r.future_booking ? 1 : 0),
    текст: (r) => (r.future_booking ? "есть" : "нет"), ячейка: (r) => (r.future_booking ? <span className="text-profit">есть</span> : "—") },
  { id: "loyalty", label: "Светофор", основная: false, список: true,
    ключ: (r) => ["green", "yellow", "red"].indexOf(r.loyalty ?? ""),
    текст: (r) => ЛАМПЫ.find((x) => x.code === r.loyalty)?.title.split(":")[0] ?? "",
    ячейка: (r) => {
      const л = ЛАМПЫ.find((x) => x.code === r.loyalty);
      return л ? <span className="inline-block size-3 rounded-full" style={{ background: л.color }} title={л.title} /> : "—";
    } },
  { id: "note", label: "Комментарий", основная: false, ключ: (r) => r.admin_note ?? "",
    текст: (r) => r.admin_note ?? "", ячейка: (r) => <span className="line-clamp-2 text-xs">{r.admin_note ?? ""}</span> },
];

/** Строка проходит фильтры колонок. Телефон ищется по цифрам, тег — по имени. */
function подходит(r: БазаСтрока, фильтры: Record<string, string>): boolean {
  return Object.entries(фильтры).every(([id, v]) => {
    if (!v) return true;
    const к = КОЛОНКИ.find((x) => x.id === id);
    if (!к) return true;
    if (id === "tags") return r.tags.some((t) => t.name === v);
    if (к.список) return к.текст(r) === v;
    if (id === "phone") {
      const ц = v.replace(/\D/g, "");
      return ц ? (r.phone ?? "").replace(/\D/g, "").includes(ц) : true;
    }
    return к.текст(r).toLowerCase().includes(v.toLowerCase());
  });
}

function отсортироватьБазу(строки: БазаСтрока[], сорт: Сортировка): БазаСтрока[] {
  const к = КОЛОНКИ.find((x) => x.id === сорт.key)?.ключ;
  if (!к) return строки;
  return [...строки].sort((a, b) => {
    const x = к(a), y = к(b);
    return (x < y ? -1 : x > y ? 1 : 0) * сорт.dir;
  });
}

/** Какие колонки видны. Выбор помнится в браузере. */
function useКолонки() {
  const [видны, setRaw] = useState<string[]>(() => {
    try {
      const v = JSON.parse(localStorage.getItem("rubl-base-columns") ?? "null");
      if (Array.isArray(v)) return v;
    } catch { /* нет сохранённого */ }
    return КОЛОНКИ.filter((к) => к.основная).map((к) => к.id);
  });
  const set = (v: string[]) => {
    setRaw(v);
    try { localStorage.setItem("rubl-base-columns", JSON.stringify(v)); } catch { /* не критично */ }
  };
  return [видны, set] as const;
}

/** Кнопка «Колонки» над таблицей — раньше «+» сидел в последней колонке
 *  и уезжал за край экрана (замечание владельца 30.10.2026). */
function ВыборКолонок({ видны, setВидны }: { видны: string[]; setВидны: (v: string[]) => void }) {
  const [открыт, setОткрыт] = useState(false);
  return (
    <span className="relative">
      <button onClick={() => setОткрыт(!открыт)} title="Добавить или убрать колонки"
              className="inline-flex items-center gap-1.5 rounded-lg border border-milk-line dark:border-line px-3 py-1.5 text-xs text-ink-soft dark:text-cream hover:border-bronze dark:hover:border-gold">
        <Columns3 size={14} /> Колонки
      </button>
      {открыт && (
        <div className="absolute right-0 top-full z-30 mt-1 w-56 rounded-xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-2 shadow-xl">
          {КОЛОНКИ.map((к) => (
            <label key={к.id} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-ink-soft dark:text-cream hover:bg-milk-deep dark:hover:bg-panel-deep">
              <input
                type="checkbox"
                checked={видны.includes(к.id)}
                onChange={(e) => setВидны(e.target.checked
                  ? КОЛОНКИ.filter((x) => x.id === к.id || видны.includes(x.id)).map((x) => x.id)
                  : видны.filter((x) => x !== к.id))}
              />
              {к.label}
            </label>
          ))}
          <p className="px-2 pt-2 text-[11px] text-muted-light dark:text-muted">
            Ширину колонки меняйте, потянув её правый край в шапке. Двойной щелчок по краю — исходная ширина.
          </p>
        </div>
      )}
    </span>
  );
}

/** Исходная ширина колонок, px. Владелец тянет край — ширина запоминается. */
const ШИРИНА: Record<string, number> = {
  days: 96, last_visit: 165, name: 230, phone: 215, group: 165, status: 140, last_call: 160,
  next: 130, tags: 150, last_call_by: 120, master: 120, visits: 80, future: 110, loyalty: 90, note: 220,
};

/** Вся база таблицей: клик по строке раскрывает полную карточку под ней. */
function ТаблицаБазы({ видны, видим, строки, варианты, сорт, setСорт, фильтры, setФильтры, открыта, раскрыть, карточка }: {
  видны: string[];
  видим: boolean;
  строки: БазаСтрока[];
  варианты: БазаСтрока[];
  сорт: Сортировка;
  setСорт: (s: Сортировка) => void;
  фильтры: Record<string, string>;
  setФильтры: (ф: Record<string, string>) => void;
  открыта: number | null;
  раскрыть: (clientId: number) => void;
  карточка: (clientId: number) => ReactNode;
}) {
  const колонки = КОЛОНКИ.filter((к) => видны.includes(к.id));
  const [ширины, setШирины] = useState<Record<string, number>>(() => {
    try { return JSON.parse(localStorage.getItem("rubl-base-widths") ?? "{}") ?? {}; } catch { return {}; }
  });
  const ширина = (id: string) => ширины[id] ?? ШИРИНА[id] ?? 120;
  const запомнить = (v: Record<string, number>) => {
    try { localStorage.setItem("rubl-base-widths", JSON.stringify(v)); } catch { /* не критично */ }
    return v;
  };
  const тянуть = (id: string) => (e: { clientX: number; preventDefault(): void; stopPropagation(): void }) => {
    e.preventDefault();
    e.stopPropagation();
    const x0 = e.clientX, w0 = ширина(id);
    let w = w0;
    const ход = (m: PointerEvent) => {
      w = Math.max(50, Math.round(w0 + m.clientX - x0));
      setШирины((s) => ({ ...s, [id]: w }));
    };
    const конец = () => {
      window.removeEventListener("pointermove", ход);
      window.removeEventListener("pointerup", конец);
      setШирины((s) => запомнить({ ...s, [id]: w }));
    };
    window.addEventListener("pointermove", ход);
    window.addEventListener("pointerup", конец);
  };
  const сброс = (id: string) => setШирины((s) => { const { [id]: _, ...rest } = s; return запомнить(rest); });

  const поСортировке = (id: string) =>
    setСорт(сорт.key !== id ? { key: id, dir: id === "days" ? -1 : 1 } : сорт.dir === -1 ? { key: id, dir: 1 } : { key: null, dir: -1 });
  const поле = "rubl-filter";
  const значенияСписка = (id: string) => {
    const к = КОЛОНКИ.find((x) => x.id === id)!;
    if (id === "tags") return [...new Set(варианты.flatMap((r) => r.tags.map((t) => t.name)))].sort();
    return [...new Set(варианты.map((r) => к.текст(r)).filter(Boolean))].sort();
  };
  const всего = колонки.reduce((s, к) => s + ширина(к.id), 0) + 36;
  // Рамка таблицы доходит ровно до низа окна — тогда горизонтальная полоса
  // прокрутки всегда на экране.
  const рамка = useRef<HTMLDivElement>(null);
  const [высота, setВысота] = useState<number>();
  useEffect(() => {
    const пересчитать = () => {
      const r = рамка.current?.getBoundingClientRect();
      if (r) setВысота(Math.max(320, window.innerHeight - (r.top + window.scrollY) - 16));
    };
    пересчитать();
    window.addEventListener("resize", пересчитать);
    return () => window.removeEventListener("resize", пересчитать);
  }, [строки.length, видим]);

  // Таблица прокручивается внутри своей рамки в обе стороны, шапка стоит на
  // месте: горизонтальная полоса видна сразу, а не после 200 строк вниз.
  return (
    <div ref={рамка} style={{ maxHeight: высота }} className="rubl-scroll rubl-solid overflow-auto rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel shadow-sm">
      <table className="rubl-table table-fixed text-sm" style={{ width: всего, minWidth: "100%" }}>
        <colgroup>
          {колонки.map((к) => <col key={к.id} style={{ width: ширина(к.id) }} />)}
          <col style={{ width: 36 }} />
        </colgroup>
        <thead className="rubl-solid sticky top-0 z-10 bg-milk-card dark:bg-panel">
          <tr className="text-left text-[11px] uppercase tracking-wider text-muted-light dark:text-muted">
            {колонки.map((к) => (
              <th key={к.id} className="relative overflow-hidden whitespace-nowrap px-3 pt-2.5 pb-1 font-medium">
                <button onClick={() => поСортировке(к.id)} className="inline-flex max-w-full items-center gap-1 truncate uppercase hover:text-ink-soft dark:hover:text-cream">
                  {к.label}
                  {сорт.key === к.id && (сорт.dir === -1 ? <ChevronDown size={12} /> : <ChevronUp size={12} />)}
                </button>
                <span onPointerDown={тянуть(к.id)} onDoubleClick={() => сброс(к.id)} title="Потяните, чтобы изменить ширину"
                      className="absolute right-0 top-1 bottom-0 w-2 cursor-col-resize border-r-2 border-transparent hover:border-bronze dark:hover:border-gold" />
              </th>
            ))}
            <th />
          </tr>
          {/* Фильтр в каждой колонке (запрос владельца 30.10.2026). */}
          <tr className="border-b border-milk-line dark:border-line">
            {колонки.map((к) => (
              <th key={к.id} className="relative px-3 pb-2 align-top">
                {к.список ? (
                  <select value={фильтры[к.id] ?? ""} onChange={(e) => setФильтры({ ...фильтры, [к.id]: e.target.value })} className={поле}>
                    <option value="">все</option>
                    {значенияСписка(к.id).map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <input value={фильтры[к.id] ?? ""} onChange={(e) => setФильтры({ ...фильтры, [к.id]: e.target.value })}
                         placeholder={к.id === "phone" ? "цифры" : к.id === "days" || к.id === "visits" ? "число" : "фильтр"}
                         className={поле} />
                )}
              </th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {строки.map((r) => {
            const открытаЛи = открыта === r.client_id;
            return (
              <Fragment key={r.client_id}>
                <tr
                  onClick={() => раскрыть(r.client_id)}
                  className={`cursor-pointer border-b border-milk-line/60 dark:border-line/60 hover:bg-milk dark:hover:bg-panel-deep/40 ${
                    r.lost_today && !r.called_today ? "shadow-[inset_3px_0_0_#e0564b]" : ""} ${
                    r.called_today && !открытаЛи ? "opacity-65" : ""} ${открытаЛи ? "rubl-tone bg-milk-deep/60 dark:bg-panel-deep" : ""}`}
                >
                  {колонки.map((к) => (
                    <td key={к.id} className={`overflow-hidden px-3 py-2 align-middle ${к.id === "note" || к.id === "tags" ? "" : "whitespace-nowrap text-ellipsis"}`}>{к.ячейка(r)}</td>
                  ))}
                  <td className="px-2 text-right text-muted-light dark:text-muted">
                    {открытаЛи ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </td>
                </tr>
                {открытаЛи && (
                  <tr className="border-b border-milk-line dark:border-line">
                    {/* Карточка не уезжает вправо вместе с широкой таблицей. */}
                    <td colSpan={колонки.length + 1} className="p-3">
                      <div className="sticky left-3 max-w-[calc(100vw-5rem)]">{карточка(r.client_id)}</div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {строки.length === 0 && (
            <tr><td colSpan={колонки.length + 1} className="px-3 py-10 text-center text-muted-light dark:text-muted">Под фильтр никто не подходит</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Через сколько дней перезвонить. Выбор из трёх сроков плюс любая дата —
 *  календарь браузера, свой писать незачем. */
const СРОКИ: { label: string; дней: number }[] = [
  { label: "завтра", дней: 1 },
  { label: "через 3 дня", дней: 3 },
  { label: "через неделю", дней: 7 },
];

function черезДней(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function TaskCard({
  task,
  busy,
  onOutcome,
  onSaveNote,
  теги,
  onTag,
  onPlan,
  onLoyalty,
  onCreateTag,
  ошибка,
}: {
  task: Task;
  busy: boolean;
  onOutcome: (outcome: string, channel: string, дата?: string | null, коммент?: string) => void;
  onSaveNote: (note: string) => Promise<boolean>;
  теги: Тег[];
  onTag: (tagId: number, value: boolean) => void;
  onPlan: (дата: string | null, заметка: string) => void;
  onLoyalty: (цвет: string) => void;
  onCreateTag: (имя: string) => void;
  ошибка?: string;
}) {
  const тёмная = useDark();
  const [noteDraft, setNoteDraft] = useState(task.admin_note ?? "");
  const [noteSaved, setNoteSaved] = useState(false);
  const [вариант, setВариант] = useState(0);
  const [новыйТег, setНовыйТег] = useState<string | null>(null);
  // Дата перезвона открывается по кнопке «Перезвонить», а не висит всегда:
  // в обычном звонке она не нужна и только шумит (замечание владельца 16.10).
  const [датаОткрыта, setДатаОткрыта] = useState(false);
  // Лампа загорается сразу, не дожидаясь ответа сервера: иначе клик кажется
  // «непрожатым». Если сервер откажет, очередь перечитается и вернёт своё.
  const [лояльность, setЛояльность] = useState<string | null>(task.loyalty);
  const скрипт = task.scripts?.[вариант] ?? task.scripts?.[0];

  const сохранитьЗаметку = async () => {
    if (noteDraft === (task.admin_note ?? "")) return;
    setNoteSaved(await onSaveNote(noteDraft));
  };

  const перезвонить = (дата: string) => {
    onOutcome("callback", "phone", дата, noteDraft);
    setДатаОткрыта(false);
  };

  const color = шкалаСегментов(тёмная)[task.group_code] || палитраГрафика(тёмная).ось;
  // Стикер статуса показываем всегда: пустое место на его месте читалось
  // как «поля статуса нет» (замечание владельца 16.10.2026).
  const статус = СТАТУСЫ.find((с) => с.code === task.call_status)
    ?? { code: "none", label: "Не звонили", chip: "bg-milk-deep dark:bg-panel-deep text-muted-light dark:text-muted" };
  // Рамка карточки — по итогу последнего звонка: записался зелёная,
  // отказался жёлтая, остальное обычная.
  const рамка = task.lost_today && !task.called_today
    ? "border-loss/70 shadow-[0_0_0_1px_rgba(224,86,75,0.35)]"
    : task.call_status === "booked"
    ? "border-profit/50"
    : task.call_status === "no_booking"
      ? "border-caution/50"
      : "border-milk-line dark:border-line";

  return (
    <div className={`bg-milk-card dark:bg-panel/80 border rounded-2xl p-5 transition-all ${рамка}`}>
      {/* Шапка: кто, в каком он состоянии и когда с ним говорили. */}
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex items-start gap-3">
          <Дни task={task} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="size-2 rounded-full shrink-0" style={{ background: color }} title={GROUP_LABELS[task.group_code] || task.group_code} />
              <span className="font-semibold text-lg">{task.client_name}</span>
              {task.lost_today && (
                <span className="rounded-full bg-loss px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-milk-card">Теряем сегодня</span>
              )}
              <span
                title="Статус последнего общения — ставится кнопками внизу карточки"
                className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${статус.chip}`}
              >
                {статус.label}
              </span>
              {task.next_contact_at && (
                <span className={`rounded-full px-2.5 py-0.5 text-[11px] ${
                  task.callback_due
                    ? "bg-bronze/15 text-bronze-ink dark:text-gold"
                    : "bg-milk-deep dark:bg-panel-deep/80 text-muted-light dark:text-muted"
                }`}>
                  перезвонить {formatDate(task.next_contact_at)}
                </span>
              )}
            </div>
            <div className="mt-0.5"><Телефон phone={task.phone} yclientsUrl={task.yclients_url} крупно /></div>
            <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-light dark:text-muted">
              <span>Последняя запись <b className="text-ink-soft dark:text-cream">{task.last_visit ? formatDate(task.last_visit) : "—"}</b></span>
              {task.future_booking && <span className="text-profit">· есть запись вперёд</span>}
              <span>· {task.visits_count} визит{plural(task.visits_count)}</span>
              {task.last_master && <span>· {task.last_master.name}</span>}
              {task.contacts.total > 0 && <span>· звонков {task.contacts.total}</span>}
              {task.last_call_at && (
                <span>· звонил {task.last_call_by || "админ"} {formatDate(task.last_call_at.slice(0, 10))}</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Светофор
            значение={лояльность}
            выбрать={(цвет) => {
              setЛояльность((текущий) => (текущий === цвет ? null : цвет));
              onLoyalty(цвет);
            }}
          />
          {/* Группа «Перезвонить» уже сказана стикером с датой у имени —
              второй раз не повторяем. */}
          {task.group_code !== "callback" && (
            <span className="text-xs text-muted-light dark:text-muted bg-milk-deep dark:bg-panel-deep/80 rounded-full px-3 py-1">
              {GROUP_LABELS[task.group_code] || task.group_code}
            </span>
          )}
        </div>
      </div>

      {/* Теги: видны только поставленные; «+ тег» открывает список. */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {task.tags.map((t) => (
          <button
            key={t.id}
            onClick={() => onTag(t.id, false)}
            title="Снять тег"
            className="rounded-full px-2.5 py-0.5 text-xs text-milk-card"
            style={{ background: t.color || "var(--color-bronze)" }}
          >
            #{t.name} ×
          </button>
        ))}
        {новыйТег === null ? (
          <button
            onClick={() => setНовыйТег("")}
            className="rounded-full border border-dashed border-milk-line dark:border-line px-2.5 py-0.5 text-xs text-muted-light dark:text-muted hover:border-bronze dark:hover:border-gold"
          >
            + тег
          </button>
        ) : (
          <span className="flex flex-wrap items-center gap-1.5">
            {теги.filter((t) => !task.tags.some((x) => x.id === t.id)).map((t) => (
              <button
                key={t.id}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => { onTag(t.id, true); setНовыйТег(null); }}
                title={t.exclude_from_calls ? "Убирает клиента из обзвона" : undefined}
                className="rounded-full border border-milk-line dark:border-line px-2.5 py-0.5 text-xs text-muted-light dark:text-muted hover:border-bronze dark:hover:border-gold"
              >
                #{t.name}
              </button>
            ))}
            <input
              autoFocus
              value={новыйТег}
              placeholder="новый тег"
              onChange={(e) => setНовыйТег(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && новыйТег.trim()) {
                  onCreateTag(новыйТег.trim());
                  setНовыйТег(null);
                }
                if (e.key === "Escape") setНовыйТег(null);
              }}
              onBlur={() => setНовыйТег(null)}
              className="w-28 rounded-full border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-2.5 py-0.5 text-xs text-ink-soft dark:text-cream focus:outline-none focus:border-bronze dark:focus:border-gold"
            />
          </span>
        )}
      </div>

      {ошибка && (
        <div className="mt-3 rounded-xl border border-loss/40 bg-loss/5 px-4 py-2 text-sm text-loss">
          {ошибка}
        </div>
      )}

      {task.called_today ? (
        <div className="mt-3 text-sm text-muted-light dark:text-muted">
          {task.call_status === "booked"
            ? "Записан сегодня."
            : task.call_status === "no_answer"
              ? "Сегодня не дозвонились, вернём завтра."
              : task.call_status === "callback"
                ? `Договорились созвониться ${task.next_contact_at ? formatDate(task.next_contact_at) : "позже"}.`
                : task.call_status === "do_not_call"
                  ? "Помечен «Не звонить» — из обзвона убран."
                  : "Звонили сегодня — без записи."}
        </div>
      ) : (
        <>
          {/* Ветки разговора из регламента: начало, причина ухода, завершение. */}
          {(task.scripts?.length ?? 0) > 1 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {task.scripts.map((в, i) => (
                <button
                  key={в.variant}
                  onClick={() => setВариант(i)}
                  className={`rounded-lg px-2.5 py-1 text-xs transition-all ${
                    i === вариант
                      ? "bg-bronze-btn text-milk-card"
                      : "border border-milk-line dark:border-line text-muted-light dark:text-muted hover:border-bronze dark:hover:border-gold"
                  }`}
                >
                  {в.title}
                </button>
              ))}
            </div>
          )}

          <div className="mt-3 rounded-xl bg-milk dark:bg-panel/60 p-4">
            <p className="text-sm text-ink-soft dark:text-cream leading-relaxed whitespace-pre-line">
              {скрипт?.phone || task.phone_script}
            </p>
            {скрипт?.hint && (
              <p className="mt-2 text-xs text-bronze-ink dark:text-gold-2">{скрипт.hint}</p>
            )}
            {(скрипт?.message || task.message_script) && (
              <details className="mt-3 group">
                <summary className="flex cursor-pointer items-center gap-1.5 text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
                  <MessageSquare size={12} /> Текст для сообщения
                </summary>
                <p className="mt-2 text-sm text-muted-light dark:text-muted leading-relaxed whitespace-pre-line">
                  {скрипт?.message || task.message_script}
                </p>
              </details>
            )}
          </div>

          {/* Один комментарий на клиента: он же причина перезвона. Сохраняется
              при потере фокуса — отдельная кнопка «Сохранить» была лишней. */}
          <input
            value={noteDraft}
            onChange={(e) => {
              setNoteDraft(e.target.value);
              setNoteSaved(false);
            }}
            onBlur={сохранитьЗаметку}
            placeholder="Комментарий: о чём договорились"
            className="mt-3 w-full rounded-xl bg-milk dark:bg-panel/60 border border-transparent focus:border-bronze dark:focus:border-gold px-4 py-2.5 text-sm text-ink-soft dark:text-cream placeholder:text-muted-light dark:placeholder:text-muted focus:outline-none"
          />
          {noteSaved && <div className="mt-1 text-xs text-profit">Комментарий сохранён</div>}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              disabled={busy}
              onClick={() => onOutcome("booked", "phone", null, noteDraft)}
              className="flex items-center gap-1.5 bg-profit text-milk-card text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
            >
              <Check size={14} /> Записан
            </button>
            <button
              disabled={busy}
              onClick={() => setДатаОткрыта((о) => !о)}
              className={`flex items-center gap-1.5 text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50 ${
                датаОткрыта
                  ? "bg-bronze-btn text-milk-card"
                  : "border border-bronze/60 text-bronze-ink dark:text-gold hover:bg-bronze/10"
              }`}
            >
              <CalendarClock size={14} /> Перезвонить
            </button>
            <button
              disabled={busy}
              onClick={() => onOutcome("no_booking", "phone", null, noteDraft)}
              className="flex items-center gap-1.5 bg-milk-line dark:bg-line text-ink-soft dark:text-cream text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
            >
              <X size={14} /> Без записи
            </button>
            <button
              disabled={busy}
              onClick={() => onOutcome("no_answer", "phone", null, noteDraft)}
              className="flex items-center gap-1.5 bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
            >
              <Phone size={14} /> Не дозвонились
            </button>
            <button
              disabled={busy}
              onClick={() => {
                if (window.confirm(`Больше никогда не звонить: ${task.client_name}? Клиент уйдёт из обзвона насовсем. Снять пометку сможет только управляющий.`))
                  onOutcome("do_not_call", "phone", null, noteDraft);
              }}
              className="ml-auto flex items-center gap-1.5 border border-loss/50 text-loss hover:bg-loss/10 text-sm font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-50"
            >
              <PhoneOff size={14} /> Не звонить
            </button>
          </div>

          {/* Дата перезвона — раскрывается по кнопке. Выбор сразу ставит
              статус «Перезвонить»: лишнего подтверждения не нужно. */}
          {датаОткрыта && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-milk dark:bg-panel/60 px-4 py-3">
              <span className="text-xs text-muted-light dark:text-muted">Когда перезвонить:</span>
              {СРОКИ.map((с) => (
                <button
                  key={с.дней}
                  onClick={() => перезвонить(черезДней(с.дней))}
                  className="rounded-lg border border-milk-line dark:border-line px-2.5 py-1.5 text-xs hover:border-bronze dark:hover:border-gold"
                >
                  {с.label}
                </button>
              ))}
              <input
                type="date"
                defaultValue={task.next_contact_at ?? ""}
                onChange={(e) => e.target.value && перезвонить(e.target.value)}
                className="rounded-lg border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-2 py-1.5 text-xs text-ink-soft dark:text-cream"
              />
              {task.next_contact_at && (
                <button
                  onClick={() => { onPlan(null, ""); setДатаОткрыта(false); }}
                  className="text-xs text-muted-light dark:text-muted underline underline-offset-2"
                >
                  снять дату
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Светофор лояльности: как клиент держался в разговоре.
 *
 *  Лампа маленькая, а кнопка вокруг неё большая (28 px): в прошлой версии
 *  нажимать приходилось точно в кружок 16 px, и владелец счёл светофор
 *  некликабельным. Повторное нажатие горящей лампы гасит светофор.
 */
function Светофор({ значение, выбрать }: { значение: string | null; выбрать: (цвет: string) => void }) {
  return (
    <span
      title="Как прошёл разговор"
      className="flex items-center rounded-full border border-milk-line dark:border-line px-0.5"
    >
      {ЛАМПЫ.map((л) => {
        const горит = значение === л.code;
        return (
          <button
            key={л.code}
            type="button"
            aria-label={л.title}
            title={л.title}
            onClick={() => выбрать(л.code)}
            className="flex size-7 cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-milk-deep dark:hover:bg-panel-deep"
          >
            <span
              className="block size-3.5 rounded-full transition-all"
              style={{
                background: горит ? л.color : "transparent",
                border: `2px solid ${л.color}`,
                opacity: значение && !горит ? 0.3 : 1,
                boxShadow: горит ? `0 0 7px ${л.color}` : undefined,
              }}
            />
          </button>
        );
      })}
    </span>
  );
}

/** Звонки сегодня — игровой счётчик: кольцо из трёх исходов, число в центре,
 *  полоса до рекорда. Решение владельца 04.10.2026. */
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


// ── Возвращённые ───────────────────────────────────────────────────────── #
// Кого вернули из потерянных с начала месяца. Статус — сверка с YCLIENTS по
// телефону: запись нашлась → галочка, нет → крестик. Данные клиентов живут
// только в этой локальной базе, на общий сервер не уходят (требование
// владельца 11.10.2026 и закона о персональных данных).

interface Возвращённый {
  attempt_id: number;
  client_id: number;
  name: string | null;
  phone: string | null;
  clicked_at: string;
  admin: string;
  status: string;
  note: string | null;
}

interface ВозвращённыеДанные {
  month: string;
  totals: { total: number; confirmed: number; not_confirmed: number; pending: number };
  days: { date: string; count: number }[];
  admins: { name: string; total: number; days: { date: string; count: number }[] }[];
  clients: Возвращённый[];
}

const ЗНАЧКИ: Record<string, { icon: typeof CheckCircle2; className: string; title: string }> = {
  confirmed: { icon: CheckCircle2, className: "text-profit", title: "Запись найдена в YCLIENTS" },
  not_confirmed: { icon: XCircle, className: "text-loss", title: "Записи в YCLIENTS нет" },
  pending: { icon: Clock, className: "text-muted-light dark:text-muted", title: "Ещё не сверено" },
};

function ВозвращённыеView() {
  const тёмная = useDark();
  const ц = палитраГрафика(тёмная);
  const [д, setД] = useState<ВозвращённыеДанные | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/client-base/returned");
        setД(r.ok ? await r.json() : null);
      } catch {
        setД(null);
      }
      setLoading(false);
    })();
  }, []);

  if (loading) return <Spinner />;
  if (!д) {
    return (
      <div className="bg-milk dark:bg-panel/60 border border-milk-line dark:border-line rounded-2xl p-10 text-center text-muted-light dark:text-muted">
        Не удалось загрузить возвращённых.
      </div>
    );
  }

  // Одна точка на день, в ней «всего» и по колонке на каждого админа.
  const точки = д.days.map((день, i) => {
    const точка: Record<string, string | number> = {
      date: день.date.slice(8) + "." + день.date.slice(5, 7),
      всего: день.count,
    };
    for (const a of д.admins) точка[a.name] = a.days[i]?.count ?? 0;
    return точка;
  });
  const цветаАдминов = [ц.золото, ц.прибыль, ц.внимание, ц.убыток];

  const плитки = [
    { label: "Вернули за месяц", value: д.totals.total, className: "" },
    { label: "Подтверждено в YCLIENTS", value: д.totals.confirmed, className: "text-profit" },
    { label: "Не подтверждено", value: д.totals.not_confirmed, className: "text-loss" },
    { label: "Ждёт сверки", value: д.totals.pending, className: "text-muted-light dark:text-muted" },
  ];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {плитки.map((п) => (
          <div key={п.label} className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-4">
            <div className="text-xs text-muted-light dark:text-muted">{п.label}</div>
            <div className={`mt-1 text-3xl font-semibold tabular-nums ${п.className}`}>{п.value}</div>
          </div>
        ))}
      </div>

      <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-5">
        <div className="mb-3 text-sm text-muted-light dark:text-muted">Возвращённые по дням</div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={точки} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid stroke={ц.сетка} vertical={false} />
            <XAxis dataKey="date" stroke={ц.ось} tick={{ fontSize: 11 }} />
            <YAxis stroke={ц.ось} tick={{ fontSize: 11 }} allowDecimals={false} />
            <Tooltip
              contentStyle={{ background: ц.подсказкаФон, border: `1px solid ${ц.подсказкаРамка}`, borderRadius: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line type="linear" dataKey="всего" stroke={ц.сейчас} strokeWidth={2} dot={false} />
            {д.admins.map((a, i) => (
              <Line
                key={a.name}
                type="linear"
                dataKey={a.name}
                stroke={цветаАдминов[i % цветаАдминов.length]}
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-widest text-muted-light dark:text-muted">
            <tr className="border-b border-milk-line dark:border-line">
              <th className="px-4 py-3 text-left font-normal">Клиент</th>
              <th className="px-4 py-3 text-left font-normal">Телефон</th>
              <th className="px-4 py-3 text-left font-normal">Записан</th>
              <th className="px-4 py-3 text-left font-normal">Админ</th>
              <th className="px-4 py-3 text-center font-normal">YCLIENTS</th>
            </tr>
          </thead>
          <tbody>
            {д.clients.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-light dark:text-muted">
                  В этом месяце потерянных ещё не возвращали.
                </td>
              </tr>
            ) : (
              д.clients.map((к) => {
                const знак = ЗНАЧКИ[к.status] ?? ЗНАЧКИ.pending;
                const Icon = знак.icon;
                return (
                  <tr key={к.attempt_id} className="border-b border-milk-line/60 dark:border-line/60 last:border-0">
                    <td className="px-4 py-3">{к.name || "—"}</td>
                    <td className="px-4 py-3 tabular-nums text-muted-light dark:text-muted">{к.phone || "—"}</td>
                    <td className="px-4 py-3 tabular-nums text-muted-light dark:text-muted">
                      {formatDate(к.clicked_at.slice(0, 10))}
                    </td>
                    <td className="px-4 py-3">{к.admin}</td>
                    <td className="px-4 py-3 text-center">
                      <span title={к.note || знак.title} className={`inline-flex ${знак.className}`}>
                        <Icon size={18} />
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-light dark:text-muted">
        Имена и телефоны хранятся только на этом компьютере — на общий сервер они не передаются.
      </p>
    </div>
  );
}
