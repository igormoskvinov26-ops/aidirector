import { Component, useEffect, useMemo, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
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
  AlertTriangle,
  Activity,
  Sunrise,
} from "lucide-react";
import { useDark, палитраГрафика } from "./тема";
import ClientBasePage from "./ClientBasePage";
import BarberMonthPage from "./BarberMonthPage";
import BasePulsePage from "./BasePulsePage";
import ShiftPage from "./ShiftPage";
import { ClientCounters } from "./ClientCounters";
import { MetricChart, type MetricPoint, type ТонГрафика } from "./MetricChart";
import logo from "./assets/logo.png";
import { Аватар } from "./мастера";

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
  fixed_monthly: number;
  materials_pct: number;
  acquiring_pct: number;
  master_commission_pct: number;
  product_commission_pct: number;
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


// ── Navigation ──
// Какие разделы видит каждая роль. Ограничение продублировано на сервере:
// прятать пункты меню — это удобство, а не защита. Мастер, зашедший по
// прямому адресу, всё равно получит от сервера только свою строку.
const PAGES_BY_ROLE: Record<string, string[]> = {
  owner: ["planfact", "bookings", "payroll", "pulse", "shift", "clients"],
  // Расчёт ЗП администратору не показываем — это дело управляющего.
  // Решение владельца 18.09.2026. Смену открывает и закрывает он же —
  // вкладка «Смена» ему открыта. Решение владельца 23.09.2026.
  operator: ["shift", "clients"],
  master: ["payroll"],
};

const NAV = [
  { id: "planfact", label: "План-факт", icon: CreditCard },
  { id: "bookings", label: "Записи за месяц", icon: CalendarClock },
  { id: "payroll", label: "Расчёт ЗП", icon: Wallet },
  { id: "pulse", label: "Пульс базы", icon: Activity },
  { id: "shift", label: "Смена", icon: Sunrise },
  { id: "clients", label: "Клиенты", icon: Users },
];

/** Ответ /api/sync/status — свежесть данных и текущий ход выгрузки. */
interface SyncState {
  in_progress: boolean;
  stage: string | null;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
  counts: Record<string, number> | null;
}

// Время показываем московское, а не то, в котором стоит компьютер: салон
// работает по Москве, и администратор сверяет надпись со своей сменой.
const МОСКВА = "Europe/Moscow";

/** «17.09 в 13:42» по Москве. */
function времяПоМоскве(iso: string): string {
  const д = new Date(iso);
  const дата = д.toLocaleDateString("ru-RU", {
    timeZone: МОСКВА,
    day: "2-digit",
    month: "2-digit",
  });
  const часы = д.toLocaleTimeString("ru-RU", {
    timeZone: МОСКВА,
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${дата} в ${часы}`;
}

/** Сколько минут прошло. Нужно, чтобы отметить устаревшие данные. */
function минутНазад(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
}

// Выгрузка идёт раз в час. Полтора часа без удачной — значит что-то не так,
// и числа на экране уже не сегодняшние.
const УСТАРЕЛО_МИНУТ = 90;

/** Свежесть данных: когда обновлялись и не идёт ли загрузка прямо сейчас.
 *
 *  Стоит в боковой панели, то есть на каждой странице. Без этой надписи
 *  вчерашние числа выглядят как сегодняшние: выгрузка работает в фоне раз в
 *  час, и по экрану её не видно вовсе.
 */
function SyncBadge() {
  const [состояние, setСостояние] = useState<SyncState | null>(null);

  useEffect(() => {
    let живой = true;
    let таймер: number | undefined;

    const спросить = async () => {
      try {
        const r = await fetch("/api/sync/status");
        if (r.ok && живой) {
          const тело: SyncState = await r.json();
          setСостояние(тело);
          // Пока выгрузка идёт, спрашиваем чаще: человек смотрит на надпись
          // и ждёт, когда она сменится. В покое реже — раз в час всё равно.
          таймер = window.setTimeout(спросить, тело.in_progress ? 3000 : 30000);
          return;
        }
      } catch {
        // Молча: Директор мог перезапускаться. Надпись останется прежней,
        // следующая попытка будет через полминуты.
      }
      if (живой) таймер = window.setTimeout(спросить, 30000);
    };

    спросить();
    return () => {
      живой = false;
      if (таймер) window.clearTimeout(таймер);
    };
  }, []);

  if (!состояние) return null;

  if (состояние.in_progress) {
    return (
      <div className="flex items-start gap-2 text-xs text-bronze dark:text-gold">
        <RefreshCw size={13} className="animate-spin mt-0.5 shrink-0" />
        <span>
          Загрузка данных
          {состояние.stage ? `: ${состояние.stage}` : ""}
          <span className="block text-muted-light dark:text-muted">
            это несколько минут
          </span>
        </span>
      </div>
    );
  }

  if (!состояние.last_success_at) {
    return (
      <div className="flex items-start gap-2 text-xs text-muted-light dark:text-muted">
        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
        <span>Данные ещё не загружались</span>
      </div>
    );
  }

  const возраст = минутНазад(состояние.last_success_at);
  const устарело = возраст > УСТАРЕЛО_МИНУТ;
  // Упавшая попытка после удачной — единственный случай, когда числа на
  // экране верные, но уже не свежие. Об этом надо сказать прямо.
  const сорвалось = Boolean(состояние.last_error);

  return (
    <div
      className={`flex items-start gap-2 text-xs ${
        устарело || сорвалось
          ? "text-caution"
          : "text-muted-light dark:text-muted"
      }`}
      title={
        сорвалось
          ? `Последняя попытка обновления не удалась: ${состояние.last_error}`
          : undefined
      }
    >
      {устарело || сорвалось ? (
        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
      ) : (
        <RefreshCw size={13} className="mt-0.5 shrink-0" />
      )}
      <span>
        Обновлено {времяПоМоскве(состояние.last_success_at)}
        {сорвалось && (
          <span className="block">Последняя попытка не удалась</span>
        )}
      </span>
    </div>
  );
}

/** Ограждение раздела: ошибка внутри страницы не гасит весь интерфейс.
 *
 *  Без него любая неожиданная выдача сервера — поле не того типа, пустой
 *  ответ вместо списка — обрывала отрисовку всего приложения. Человек видел
 *  белый экран: ни меню, ни надписи о свежести данных, ни намёка на причину.
 *  Найдено при проверке интерфейса на подставных ответах 17.09.2026.
 *
 *  Ограждается только область страницы. Боковая панель снаружи и остаётся
 *  на месте: по ней можно уйти в другой раздел, а не перезагружать окно.
 */
class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Раздел не отрисовался:", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="rounded-2xl border border-caution/30 bg-caution/5 p-6">
        <div className="flex items-center gap-2 text-caution font-medium">
          <AlertTriangle size={18} />
          Раздел не открылся
        </div>
        <p className="text-sm text-muted-light dark:text-muted mt-2">
          Скорее всего данные ещё не загружены до конца. Слева видно, идёт ли
          загрузка. Если она закончилась, а раздел всё равно не открывается —
          перезапустите Директора и покажите вывод.
        </p>
      </div>
    );
  }
}

// ── Components ──
function Spinner() {
  return (
    <div className="min-h-screen bg-milk dark:bg-ink flex items-center justify-center">
      <div className="relative">
        <div className="w-8 h-8 border-2 border-bronze/20 dark:border-gold/20 rounded-full" />
        <div className="w-8 h-8 border-2 border-transparent border-t-bronze dark:border-t-gold rounded-full animate-spin absolute inset-0" />
      </div>
    </div>
  );
}

// Постоянные расходы — одним числом: разбор по статьям ведётся в отчётности
// салона, а Директору нужна итоговая сумма, чтобы поделить её на дни.
// Оплата мастеров и расходники в неё не входят — они ниже, процентами.
const COST_FIELDS = [
  { key: "fixed_monthly", label: "Постоянные расходы", unit: "₽ / мес" },
  { key: "materials_pct", label: "Расходники", unit: "% выручки" },
  { key: "acquiring_pct", label: "Эквайринг", unit: "% выручки" },
  { key: "master_commission_pct", label: "Мастеру с услуг", unit: "% выручки" },
  { key: "product_commission_pct", label: "Мастеру с косметики", unit: "% продаж" },
] as const;

type КлючЦвета = "убыток" | "внимание" | "прибыль";

const ZONE_TEXT: Record<string, { label: string; ключ: КлючЦвета }> = {
  // Цвета зон берутся из палитры графика по текущей теме: подписи легенды
  // стоят на панели, и тёмно-красный на чёрном фоне слепнет.
  red: { label: "убыток при любом раскладе", ключ: "убыток" as const },
  amber: { label: "исход зависит от загрузки мастеров", ключ: "внимание" as const },
  green: { label: "прибыль при любом раскладе", ключ: "прибыль" as const },
};

/**
 * Подсказка дня. Раньше сумма дня висела подписью над каждым столбцом, и к
 * концу месяца тридцать подписей налезали друг на друга. Теперь по наведению —
 * и вместе с суммой помещается то, что подписью было не показать: пороги дня
 * и во что этот день обошёлся.
 */
function DayTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  const цвета = палитраГрафика(useDark());
  if (!active || !payload?.length) return null;
  const day = payload[0].payload;
  const rub = (n: number) => Math.round(n).toLocaleString("ru-RU") + " ₽";
  const zone = day.zone ? ZONE_TEXT[day.zone] : null;
  const planned = day.scheduled_day ?? 0;

  return (
    <div className="bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-xl px-4 py-3 text-xs shadow-xl">
      <div className="font-semibold text-sm mb-2 text-ink-soft dark:text-cream">
        {day.date}
        {day.masters_count > 0 && (
          <span className="ml-2 font-normal text-muted-light dark:text-muted">
            мастеров на смене: {day.masters_count}
          </span>
        )}
      </div>

      {day.delta > 0 ? (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-muted-light dark:text-muted">За день:</span>
            <span
              className="text-base font-bold"
              style={{ color: zone ? цвета[zone.ключ] : undefined }}
            >
              {rub(day.delta)}
            </span>
          </div>
          {zone && (
            <div className="mb-2" style={{ color: цвета[zone.ключ] }}>
              {zone.label}
            </div>
          )}
          <div className="text-muted-light dark:text-muted mb-2">
            пороги дня: {rub(day.zone_low)}
            {day.zone_high > day.zone_low && ` … ${rub(day.zone_high)}`}
          </div>
        </>
      ) : (
        <div className="text-muted-light dark:text-muted mb-2">
          {planned > 0 ? `Записей на ${rub(planned)}` : "Выручки нет"}
        </div>
      )}

      <div className="border-t border-milk-line dark:border-line pt-2 space-y-0.5 text-muted-light dark:text-muted">
        <div className="text-[10px] uppercase tracking-wider text-muted-light dark:text-muted">
          накопленным итогом
        </div>
        <div>Услуги: {rub(day.services)}</div>
        <div>Товары: {rub(day.products)}</div>
        <div>Запланировано: {rub(day.scheduled)}</div>
        <div>Мин. маржинальность: {rub(day.break_even)}</div>
        {day.daily_plan_cum > 0 && <div>Выручка под план: {rub(day.daily_plan_cum)}</div>}
      </div>
    </div>
  );
}

function PlanFactPage() {
  // Цвета графиков — литералами, по текущей теме. Подробнее у палитраГрафика.
  const цвета = палитраГрафика(useDark());
  const [hourly, setHourly] = useState<any[]>([]);
  const [daily, setDaily] = useState<DailyFinancePoint[]>([]);
  const [plan, setPlan] = useState<PlanData>({ period: "", profit_target: 0, margin_target_pct: 30 });
  const [summary, setSummary] = useState<PlanFactSummary | null>(null);
  const [costs, setCosts] = useState<CostSettings | null>(null);
  const [costsOpen, setCostsOpen] = useState(false);
  const [costsDraft, setCostsDraft] = useState<Record<string, string>>({});
  const [costsError, setCostsError] = useState("");
  const [planInput, setPlanInput] = useState("");
  // «Фикс» — то же fixed_monthly, что и в «Структуре расходов» ниже, просто
  // вынесено сюда для удобства: это единственный рычаг, которым управляющий
  // двигает порог безубыточности по ходу месяца, и тянуться для этого вниз
  // не нужно. Значение одно и то же в обоих местах — сохранение отсюда
  // обновляет его целиком, и нижняя форма при следующем открытии подхватит
  // новое значение.
  const [fixedInput, setFixedInput] = useState("");
  const [headerError, setHeaderError] = useState("");
  const [headerSaved, setHeaderSaved] = useState(false);
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
      setFixedInput(String(Math.round(c.fixed_monthly)));
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

  // Сохраняет план и «Фикс» одной кнопкой — обе цифры относятся к одному и
  // тому же месяцу, и вводить их по отдельности незачем.
  //
  // fetch() не бросает исключение на 4xx/5xx — раньше здесь Promise.all
  // просто дожидался обоих ответов и шёл дальше, не глядя, что в них. Если
  // сервер отклонял значение (или сеть подводила), человек не видел вообще
  // ничего: ни ошибки, ни того, что «Сохранить» вообще сработало. Теперь
  // оба ответа проверяются по .ok, а из отказа читается detail — тот же
  // приём, что уже в saveCosts ниже.
  const saveHeader = async () => {
    setHeaderError("");
    setHeaderSaved(false);
    const planVal = parseFloat(planInput);
    const fixedVal = parseFloat(fixedInput);
    if (isNaN(planVal) || planVal <= 0) {
      setHeaderError("План должен быть положительным числом.");
      return;
    }
    if (!costs || isNaN(fixedVal) || fixedVal < 0) {
      setHeaderError("Фикс должен быть числом не меньше нуля.");
      return;
    }
    try {
      const [planRes, costsRes] = await Promise.all([
        fetch("/api/finance/plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            period: currentPeriod,
            profit_target: planVal,
            margin_target_pct: plan.margin_target_pct,
          }),
        }),
        // Остальные поля расходов берём как есть — эндпоинт принимает их все
        // разом, меняем в нём только fixed_monthly.
        fetch("/api/finance/costs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...costs, fixed_monthly: fixedVal }),
        }),
      ]);
      if (!planRes.ok || !costsRes.ok) {
        const failed = !planRes.ok ? planRes : costsRes;
        const detail = await failed.json().catch(() => null);
        setHeaderError(
          typeof detail?.detail === "string"
            ? detail.detail
            : `Сервер отклонил значение (код ${failed.status}). Ничего не сохранено.`,
        );
        return;
      }
      setPlan({ ...plan, profit_target: planVal });
      await fetchData();
      setHeaderSaved(true);
    } catch (e) {
      console.error("Header save error", e);
      setHeaderError("Сервер не ответил. Проверьте, что Директор запущен.");
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
        // Накопленные ряды затирают дневные значения, поэтому запись на этот
        // день сохраняется отдельно — она нужна подсказке.
        scheduled_day: d.scheduled,
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
      <div className="mb-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-1">План-факт</h1>
          <p className="text-muted-light dark:text-muted text-sm">Маржинальность, точка безубыточности, план/факт</p>
        </div>
        <div className="flex items-end gap-3">
          <div>
            {/* Единицы подписаны не случайно: раньше поле принимало голое
                число, и «500» вместо 500 000 молча превращалось в план
                в пятьсот рублей. */}
            <label className="block text-[11px] uppercase tracking-wider text-muted-light dark:text-muted mb-1">
              План прибыли на месяц, ₽
            </label>
            <input
              type="number"
              value={planInput}
              onChange={(e) => { setPlanInput(e.target.value); setHeaderSaved(false); }}
              placeholder="например, 500000"
              className="w-40 bg-milk-deep dark:bg-panel border border-milk-line dark:border-line rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:border-bronze dark:focus:border-gold"
            />
          </div>
          <div>
            {/* Тот же fixed_monthly, что и в «Структуре расходов» ниже — см.
                комментарий у useState(fixedInput). Меняется здесь по ходу
                месяца, когда прогноз требует поправить порог безубыточности. */}
            <label className="block text-[11px] uppercase tracking-wider text-muted-light dark:text-muted mb-1">
              Фикс, ₽ / мес
            </label>
            <input
              type="number"
              value={fixedInput}
              onChange={(e) => { setFixedInput(e.target.value); setHeaderSaved(false); }}
              placeholder="например, 389117"
              className="w-40 bg-milk-deep dark:bg-panel border border-milk-line dark:border-line rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:border-bronze dark:focus:border-gold"
            />
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5 border border-milk-line dark:border-line hover:border-bronze dark:hover:border-gold px-4 py-2 rounded-lg text-sm transition-all disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Обновить данные
          </button>
          <button
            onClick={saveHeader}
            className="flex items-center gap-1.5 bg-bronze dark:bg-gold hover:bg-bronze/90 dark:hover:bg-gold/90 text-ink-soft font-semibold px-4 py-2 rounded-lg text-sm transition-all"
          >
            <Save size={14} />
            Сохранить
          </button>
        </div>
      </div>
      {/* Обратная связь по сохранению. fetch не бросает исключение на 4xx —
          без этой строки отказ сервера был не видно вообще никак: кнопка
          молчала, а «Обновить данные» просто честно показывал то, что
          реально осталось лежать в базе. */}
      {headerError && (
        <p className="mt-2 text-right text-sm text-loss">{headerError}</p>
      )}
      {headerSaved && !headerError && (
        <p className="mt-2 text-right text-sm text-profit">Сохранено.</p>
      )}
      </div>

      {/* Сегодня — по фактической выработке каждого мастера. Никаких
          допущений: кто сколько сделал, уже известно. */}
      {summary?.today_detail && (
        <div
          className={`bg-milk-card dark:bg-panel/80 border rounded-2xl p-6 mb-6 ${
            summary.today_detail.margin >= 0
              ? "border-profit/50"
              : "border-loss/40"
          }`}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-3 mb-5">
            <h3 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              Сегодня — {summary.today}
            </h3>
            <span
              className={`text-sm font-semibold ${
                summary.today_detail.margin >= 0 ? "text-profit" : "text-loss"
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
            <p className="text-sm text-muted-light dark:text-muted">
              Выполненных записей сегодня пока нет.
            </p>
          ) : (
            <div className="overflow-x-auto mb-5">
              <table className="w-full text-sm min-w-[520px]">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-muted-light dark:text-muted">
                    <th className="pb-2 pr-4 font-semibold">Мастер</th>
                    <th className="pb-2 px-4 font-semibold text-right">Услуги</th>
                    <th className="pb-2 px-4 font-semibold text-right">Косметика</th>
                    <th className="pb-2 pl-4 font-semibold text-right">К выплате</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.today_detail.masters.map((m) => (
                    <tr key={m.name} className="border-t border-milk-line dark:border-line/60">
                      <td className="py-2.5 pr-4">
                        {m.name}
                        {m.on_guarantee && (
                          <span className="ml-2 text-[10px] uppercase tracking-wider text-caution border border-caution/40 rounded px-1.5 py-0.5">
                            гарант
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-4 text-right">{RUB(m.services)}</td>
                      <td className="py-2.5 px-4 text-right text-muted-light dark:text-muted">
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
              <div className="text-xs text-muted-light dark:text-muted">Заработано</div>
              <div className="font-semibold mt-1">{RUB(summary.today_detail.revenue)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-light dark:text-muted">Мастерам</div>
              <div className="font-semibold mt-1">− {RUB(summary.today_detail.payout)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-light dark:text-muted">Постоянные</div>
              <div className="font-semibold mt-1">− {RUB(summary.today_detail.fixed)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-light dark:text-muted">Расходники</div>
              <div className="font-semibold mt-1">− {RUB(summary.today_detail.variable)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-light dark:text-muted">Итог дня</div>
              <div
                className={`font-semibold mt-1 ${
                  summary.today_detail.margin >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {summary.today_detail.margin >= 0 ? "+" : "−"}
                {RUB(Math.abs(summary.today_detail.margin))}
              </div>
            </div>
          </div>

          <p className="text-xs text-muted-light dark:text-muted mt-4 max-w-[80ch]">
            Считается по фактической выработке каждого: гарант платится
            персонально, поэтому две одинаковые общие суммы обходятся салону
            по-разному. Порог сегодня при сложившемся распределении —{" "}
            {RUB(summary.today_detail.break_even)} по услугам.
          </p>
        </div>
      )}

      {/* Сводка месяца и таблица по составу смены */}
      {summary && (
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6 mb-6">
          <div className="flex flex-wrap items-baseline justify-between gap-3 mb-5">
            <h3 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              С начала месяца — {summary.period}
            </h3>
            <span className="text-xs text-muted-light dark:text-muted">
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
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-light dark:text-muted">
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
                        ? "bg-bronze/10 dark:bg-gold/10 border-l-2 border-bronze dark:border-gold"
                        : "border-l-2 border-transparent"
                    }
                  >
                    <td className="py-3 pr-4">
                      <span className="font-semibold">{row.masters}</span>
                      {row.is_today && (
                        <span className="ml-2 text-[11px] text-bronze dark:text-gold uppercase tracking-wider">
                          сегодня
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      <div className="font-semibold">
                        {RUB(row.break_even_daily)}
                        {row.break_even_worst > row.break_even_daily && (
                          <span className="text-muted-light dark:text-muted font-normal">
                            {" … "}{RUB(row.break_even_worst)}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-muted-light dark:text-muted">
                        {row.break_even_worst > row.break_even_daily
                          ? "при равной загрузке … если работает один"
                          : "день в ноль"}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      {row.plan_daily_required > 0 ? (
                        <>
                          <div className="font-semibold">{RUB(row.plan_daily_required)}</div>
                          <div className="text-xs text-muted-light dark:text-muted">
                            по {RUB(row.plan_per_master)} на мастера
                          </div>
                        </>
                      ) : (
                        <span className="text-muted-light dark:text-muted">—</span>
                      )}
                    </td>
                    <td className="py-3 pl-4">
                      {row.fact_daily_avg !== null ? (
                        <>
                          <div
                            className={`font-semibold ${
                              row.fact_daily_avg >= row.break_even_daily
                                ? "text-profit"
                                : "text-loss"
                            }`}
                          >
                            {RUB(row.fact_daily_avg)}
                          </div>
                          <div className="text-xs text-muted-light dark:text-muted">
                            среднее за {row.fact_days} дн.
                          </div>
                        </>
                      ) : (
                        <span className="text-muted-light dark:text-muted">
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
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6 mb-6">
          <button
            onClick={() => setCostsOpen(!costsOpen)}
            className="w-full flex flex-wrap items-baseline justify-between gap-3 text-left"
          >
            <h3 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              Расходы {costsOpen ? "▴" : "▾"}
            </h3>
            <span className="text-xs text-muted-light dark:text-muted">
              {RUB(costs.fixed_monthly)} в месяц ·{" "}
              <span className="text-ink-soft dark:text-cream">
                {RUB(costs.fixed_daily)} в день
              </span>
              {" · мастеру "}{costs.master_commission_pct}% с услуг и{" "}
              {costs.product_commission_pct}% с косметики
            </span>
          </button>

          {costsOpen && (
            <>
              <p className="text-xs text-muted-light dark:text-muted mt-4 max-w-[70ch]">
                Из этих чисел считается всё остальное: порог безубыточности,
                выручка под план и прибыль за месяц. Постоянные расходы —
                аренда, оклады, уборка, налоги — задаются одной суммой за месяц
                и делятся на {costs.days_in_month} дней текущего месяца.
                Оплата мастеров и расходники сюда не входят: они считаются
                процентом от выручки и учлись бы дважды.
              </p>
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mt-4">
                {COST_FIELDS.map((f) => (
                  <label key={f.key} className="block">
                    <span className="block text-[11px] uppercase tracking-wider text-muted-light dark:text-muted mb-1">
                      {f.label}
                    </span>
                    <input
                      type="number"
                      step="0.01"
                      value={costsDraft[f.key] ?? ""}
                      onChange={(e) =>
                        setCostsDraft({ ...costsDraft, [f.key]: e.target.value })
                      }
                      className="w-full bg-milk-deep dark:bg-ink border border-milk-line dark:border-line rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:border-bronze dark:focus:border-gold"
                    />
                    <span className="block text-[11px] text-muted-light dark:text-muted mt-1">
                      {f.unit}
                    </span>
                  </label>
                ))}
              </div>
              {costsError && (
                <p className="text-sm text-loss mt-4">{costsError}</p>
              )}
              <div className="flex items-center gap-3 mt-5">
                <button
                  onClick={saveCosts}
                  className="flex items-center gap-1.5 bg-bronze dark:bg-gold hover:bg-bronze/90 dark:hover:bg-gold/90 text-ink-soft font-semibold px-4 py-2 rounded-lg text-sm transition-all"
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
                  className="text-sm text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
                >
                  Вернуть как было
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Chart 1: Hourly (Today) */}
      <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
            Сегодня — {todayStr}
          </h3>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-light dark:text-muted">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-bronze dark:bg-gold" /> Услуги выполн.</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-profit" /> Товары</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm border border-bronze/30 dark:border-gold/30 bg-bronze/25 dark:bg-gold/25" /> Запланировано</span>
            <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-loss rounded-full" /> Безубыточность {FMT_RUB(breakEvenDaily)}</span>
            {dailyPlan > 0 && <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-profit rounded-full" /> План дня {FMT_RUB(dailyPlan)}</span>}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={hourlyCumulative} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke={цвета.сетка} />
            <XAxis dataKey="hour" tick={{ fill: цвета.ось, fontSize: 11 }} />
            <YAxis tick={{ fill: цвета.ось, fontSize: 11 }} tickFormatter={(v) => FMT(v)} />
            <Tooltip
              contentStyle={{ background: цвета.подсказкаФон, border: `1px solid ${цвета.подсказкаРамка}`, borderRadius: "12px", fontSize: 12 }}
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
                  <text x={x + width / 2} y={y - 8} fill={цвета.подпись} fontSize={12} fontWeight={700} textAnchor="middle">{FMT_RUB(value)}</text>
                </g>
              );
            }}>
              {hourlyCumulative.map((entry, i) => (
                <Cell key={i} fill={цвета.золото} stroke={entry.hour === nowHour ? цвета.сейчас : "transparent"} strokeWidth={entry.hour === nowHour ? 2 : 0} />
              ))}
            </Bar>
            <Bar dataKey="products" stackId="rev" fill={цвета.прибыль} name="products" radius={[0, 0, 0, 0]} />
            <Bar dataKey="scheduled" stackId="rev" name="scheduled" radius={[4, 4, 0, 0]} label={({ x, y, width, index }: any) => {
              const entry = hourlyCumulative[index];
              if (!entry || entry.hour !== nowHour) return null;
              const total = entry.services + entry.products + entry.scheduled;
              return <text x={x + width / 2} y={y - 8} fill={цвета.подпись} fontSize={11} fontWeight={700} textAnchor="middle">{FMT_RUB(total)}</text>;
            }}>
              {hourlyCumulative.map((entry, i) => (
                <Cell key={i} fill={цвета.золото} fillOpacity={0.25} stroke={entry.hour === nowHour ? цвета.сейчас : цвета.золото} strokeWidth={entry.hour === nowHour ? 2 : 1} />
              ))}
            </Bar>
            <Line dataKey="break_even" stroke={цвета.убыток} strokeWidth={2.5} dot={false} name="break_even" />
            {dailyPlan > 0 && (
              <Line dataKey={() => dailyPlan} stroke={цвета.прибыль} strokeWidth={2.5} dot={false} name="daily_plan" />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Chart 2: Daily (current month) */}
      <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-6 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
            По дням — {currentPeriod}
          </h3>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-light dark:text-muted">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-bronze dark:bg-gold" /> Услуги выполн.</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-profit" /> Товары</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm border border-bronze/30 dark:border-gold/30 bg-bronze/25 dark:bg-gold/25" /> Запланировано</span>
            <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-loss rounded-full" /> Мин. марж. (накоп.)</span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-loss" />
              <span className="w-2 h-2 rounded-full bg-caution" />
              <span className="w-2 h-2 rounded-full bg-profit" />
              день: убыток · спорно · прибыль
            </span>
            {plan.profit_target > 0 && <span className="flex items-center gap-1.5"><span className="w-0.5 h-4 bg-profit rounded-full" /> Выручка под план (накоп.)</span>}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={dailyCumulative} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke={цвета.сетка} />
            <XAxis dataKey="date" tick={{ fill: цвета.ось, fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
            <YAxis tick={{ fill: цвета.ось, fontSize: 11 }} tickFormatter={(v) => FMT(v)} />
            <Tooltip cursor={{ fill: "rgba(212,168,83,0.08)" }} content={<DayTooltip />} />
            {/* Столбец красится по зоне дня: подписей над каждым больше нет,
                сумма и пояснение — в подсказке при наведении. */}
            <Bar dataKey="services" stackId="rev" name="services" radius={[6, 6, 0, 0]}>
              {dailyCumulative.map((entry, i) => (
                <Cell
                  key={i}
                  fill={цвета.золото}
                  stroke={
                    entry.date === todayStr
                      ? цвета.сейчас
                      : entry.zone === "green"
                        ? цвета.прибыль
                        : entry.zone === "amber"
                          ? цвета.внимание
                          : entry.zone === "red"
                            ? цвета.убыток
                            : "transparent"
                  }
                  strokeWidth={entry.date === todayStr ? 2 : entry.zone ? 1.5 : 0}
                />
              ))}
            </Bar>
            <Bar dataKey="products" stackId="rev" fill={цвета.прибыль} name="products" radius={[0, 0, 0, 0]} />
            <Bar dataKey="scheduled" stackId="rev" name="scheduled" radius={[6, 6, 0, 0]} label={({ x, y, width, index }: any) => {
              const entry = dailyCumulative[index];
              if (!entry || entry.date !== todayStr) return null;
              const actual = entry.services + entry.products;
              if (actual <= 0) return null;
              return <text x={x + width / 2} y={y - 8} fill={цвета.сейчас} fontSize={11} fontWeight={700} textAnchor="middle">{FMT_RUB(actual)}</text>;
            }}>
              {dailyCumulative.map((entry, i) => (
                <Cell key={i} fill={цвета.золото} fillOpacity={0.25} stroke={entry.date === todayStr ? цвета.сейчас : цвета.золото} strokeWidth={entry.date === todayStr ? 2 : 1} />
              ))}
            </Bar>
            <Line dataKey="break_even" stroke={цвета.убыток} strokeWidth={2.5} dot={false} name="break_even" />
            {plan.profit_target > 0 && (
              <Line dataKey="daily_plan_cum" stroke={цвета.прибыль} strokeWidth={2.5} dot={false} name="daily_plan_cum" />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* KPI mini-cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-4">
          <div className="text-xs text-muted-light dark:text-muted">Выручка сегодня</div>
          <div className="text-lg font-bold mt-1">{FMT_RUB(todayRevenue)}</div>
        </div>
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-4">
          <div className="text-xs text-muted-light dark:text-muted">Мастеров на смене</div>
          <div className="text-lg font-bold mt-1">{mastersToday}</div>
        </div>
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-4">
          <div className="text-xs text-muted-light dark:text-muted">Точка безубыточности</div>
          <div className="text-lg font-bold mt-1">{FMT_RUB(breakEvenDaily)}</div>
        </div>
        <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-xl p-4">
          <div className="text-xs text-muted-light dark:text-muted">План на день</div>
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
    <div className="bg-milk dark:bg-ink/60 border border-milk-line dark:border-line rounded-xl p-4">
      <div className="text-xs text-muted-light dark:text-muted">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${accent ? "text-bronze dark:text-gold" : ""}`}>{value}</div>
      <div className="text-xs text-muted-light dark:text-muted mt-1">{note}</div>
    </div>
  );
}

/** Ответ /api/bookings/upcoming. */
/** Строка мастера в дашборде месяца. Зарплаты здесь нет: это загрузка, а не доход. */
interface MonthRow {
  staff_id: number;
  name: string;
  /** Выполнено с первого числа месяца по текущий момент. */
  completed_count: number;
  completed_revenue: number;
  /** Проданная косметика. null — YCLIENTS не отдал продажи. */
  product_sales: number | null;
  /** Впереди до конца этого же месяца. */
  future_count: number;
  future_revenue: number;
  /** Выполненное плюс будущее. */
  expected_count: number;
  /** Только услуги — считается всегда. */
  expected_services: number;
  /** Услуги вместе с косметикой. null, если продажи косметики не получены.
   *  По нему же таблица отсортирована: это ключевой параметр. */
  expected_revenue: number | null;
  /** Начислено мастеру на сегодня. null — зарплата не посчитана. */
  payroll: number | null;
  /** Выручка мастера минус его зарплата. Не чистая прибыль салона: постоянные
   *  расходы, расходники и эквайринг сюда не входят. */
  contribution: number | null;
}

/** Строка «Продажи администраторов» — деньги не через трёх зарегистрированных
 *  барберов. Без расписания, гаранта и прогноза: только то, что уже прошло. */
interface AdminSaleRow {
  staff_id: number;
  name: string;
  completed_count: number;
  completed_revenue: number;
  /** null — YCLIENTS не отдал продажи, а не «ничего не продано». */
  product_sales: number | null;
}

interface AdminSalesBlock {
  masters: AdminSaleRow[];
  totals: {
    completed_count: number;
    completed_revenue: number;
    product_sales: number | null;
  };
}

interface MonthTotals extends MonthRow {
  /** Выручка всего салона: прогноз по барберам плюс продажи администраторов.
   *  null, если хоть одна из двух частей неизвестна — сложить с неизвестным
   *  нельзя, не подставляя молча ноль вместо него. */
  company_revenue: number | null;
}

/** Возвращаемость — доля клиентов, пришедших к мастеру повторно, и сколько
 *  из них уже потерянные. Считается по всей истории визитов в базе, не по
 *  календарному месяцу — решение владельца 18.09.2026, уточнено там же. */
interface ReturnRateRow {
  staff_id: number;
  name: string;
  clients_total: number;
  clients_returned: number;
  /** Последний визит или запись к этому мастеру старше 60 дней. */
  clients_lost: number;
  /** Первый завершённый визит к этому мастеру был в пределах 60 дней. */
  clients_new: number;
  /** null — у мастера пока нет ни одного клиента в базе. */
  return_rate_pct: number | null;
}

interface MonthReport {
  month_start: string;
  month_end: string;
  as_of: string;
  updated_at: string;
  masters: MonthRow[];
  totals: MonthTotals;
  /** Только владельцу и управляющему — мастеру чужая выручка не нужна. */
  admin_sales?: AdminSalesBlock;
  warnings: string[];
  scope: "all" | "own";
}

const МЕСЯЦЫ = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

/** «1 — 30 сентября»: период, за который посчитан весь дашборд. */
function периодМесяца(начало: string, конец: string): string {
  const с = new Date(начало + "T00:00:00");
  const по = new Date(конец + "T00:00:00");
  return `${с.getDate()} — ${по.getDate()} ${МЕСЯЦЫ[по.getMonth()]}`;
}

const РУБ = (n: number | null): string =>
  n === null ? "—" : Math.round(n).toLocaleString("ru-RU") + " ₽";

const ШТ = (n: number | null): string => (n === null ? "—" : String(n));

/** Дашборд месяца: мастера в строках, три блока столбцов.
 *
 *  Блоки разделены не только подписью, но и фоном — сплошной полосой на всю
 *  высоту таблицы. Сделано через colgroup: фон на <col> красит столбец
 *  целиком, и полоса не рвётся между строками, как это вышло бы при заливке
 *  каждой клетки по отдельности.
 *
 *  Акцент двухуровневый, по просьбе владельца:
 *    первый  — заработанные деньги и прогноз: крупнее, полужирным, золотом;
 *    второй  — количество и сумма будущих записей: приглушённое золото.
 *  Остальные числа набраны обычным текстом. Если выделить всё, не выделено
 *  ничего.
 */
function BookingsPage() {
  const [data, setData] = useState<MonthReport | null>(null);
  // Фикс — тот же fixed_monthly, что редактируется на «План-факте»: нужен
  // здесь только для блока «Прибыль» ниже таблицы.
  const [fixedMonthly, setFixedMonthly] = useState<number | null>(null);
  const [returnRate, setReturnRate] = useState<ReturnRateRow[] | null>(null);
  // Динамика по дням для клика на плитку/колонку — решение владельца
  // 18.09.2026. Общий источник с «Клиентской базой»: тот же формат ключей.
  const [metricHistory, setMetricHistory] = useState<Record<string, MetricPoint[]>>({});
  const [selectedMetric, setSelectedMetric] = useState<
    { key: string; label: string; тон: ТонГрафика } | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [bRes, cRes] = await Promise.all([
          fetch("/api/barbers/future"),
          fetch("/api/finance/costs"),
        ]);
        if (!bRes.ok) throw new Error(`сервер ответил ${bRes.status}`);
        setData(await bRes.json());
        if (cRes.ok) {
          const c = await cRes.json();
          setFixedMonthly(c.fixed_monthly ?? null);
        }
      } catch (e) {
        setFailed(e instanceof Error ? e.message : "не удалось получить данные");
      }
      setLoading(false);
    })();

    // Возвращаемость — отдельным запросом: считается по году истории в
    // базе, а не по месяцу живьём из YCLIENTS, и не должна ронять всю
    // страницу, если сама база ещё не досинхронизирована на такую глубину.
    (async () => {
      try {
        const r = await fetch("/api/barbers/return-rate");
        if (r.ok) setReturnRate((await r.json()).masters);
      } catch {
        // молча: страница и без этого блока работает
      }
    })();

    (async () => {
      try {
        const r = await fetch("/api/client-base/metric-history");
        if (r.ok) setMetricHistory((await r.json()).series ?? {});
      } catch {
        // молча: это дополнение к графику, не он сам
      }
    })();
  }, []);

  if (loading) return <Spinner />;

  if (failed || !data) {
    return (
      <div className="animate-in rounded-2xl border border-caution/30 bg-caution/5 p-6">
        <div className="flex items-center gap-2 text-caution font-medium">
          <AlertTriangle size={18} />
          Не удалось получить данные
        </div>
        <p className="text-sm text-muted-light dark:text-muted mt-2">
          {failed || "Ответ пустой."} Слева видно, идёт ли загрузка из YCLIENTS.
        </p>
      </div>
    );
  }

  const итог = data.totals;

  // Классы собраны в одном месте: разделители и отступы блоков должны
  // совпадать в шапке и в каждой строке, иначе полосы разъезжаются.
  const клетка = "px-3 py-3.5 text-right whitespace-nowrap align-middle";
  const межблок = "border-l border-milk-line dark:border-line";
  // Четыре ступени выделения, сверху вниз по важности.
  //
  //   принесено  — сколько осталось салону. Самое важное число, и цвет у него
  //                свой: зелёный значит деньги, которые остались, а не прошли
  //                мимо. Отрицательный вклад показывается красным — мастер на
  //                гаранте при пустом месяце обходится дороже, чем приносит;
  //   ключевой   — прогноз с косметикой. По нему отсортирована таблица, и
  //                сравнивать мастеров владелец будет по нему;
  //   первый     — прочие заработанные деньги;
  //   второй     — будущие записи: тише денег, громче служебных чисел.
  const принесено = "text-[17px] font-bold";
  const ключевой = "text-[17px] font-bold text-bronze dark:text-gold";
  const первый = "text-[15px] font-semibold text-bronze dark:text-gold";
  const второй = "text-sm font-medium text-bronze-ink dark:text-gold-2";
  const обычный = "text-sm text-ink-soft dark:text-cream";

  const Строка = ({ row, итоговая }: { row: MonthRow; итоговая?: boolean }) => {
    // Строка итогов набрана крупнее и золотом целиком: это сводка по салону,
    // и глаз должен находить её, не пересчитывая строки сверху.
    const итог = итоговая ? "text-[15px] text-bronze dark:text-gold" : "";
    const вклад =
      row.contribution !== null && row.contribution < 0 ? "text-loss" : "text-profit";

    return (
      <tr
        className={
          итоговая
            ? "border-t-2 border-bronze/50 dark:border-gold/50"
            : "border-t border-milk-line/70 dark:border-line/70"
        }
      >
        <td className="px-4 py-3 align-middle">
          {итоговая ? (
            <span className="text-[15px] font-bold text-bronze dark:text-gold">
              Всего по салону
            </span>
          ) : (
            <span className="flex items-center gap-3">
              <Аватар staffId={row.staff_id} name={row.name} />
              <span className="font-semibold text-ink-soft dark:text-cream">{row.name}</span>
            </span>
          )}
        </td>

        <td className={`${клетка} ${межблок} ${итог || обычный}`}>{ШТ(row.completed_count)}</td>
        <td className={`${клетка} ${первый} ${итог}`}>{РУБ(row.completed_revenue)}</td>
        <td className={`${клетка} ${итог || обычный}`}>{РУБ(row.product_sales)}</td>

        <td className={`${клетка} ${межблок} ${второй} ${итог}`}>{ШТ(row.future_count)}</td>
        <td className={`${клетка} ${второй} ${итог}`}>{РУБ(row.future_revenue)}</td>

        <td className={`${клетка} ${межблок} ${итог || обычный}`}>{ШТ(row.expected_count)}</td>
        <td className={`${клетка} ${первый} ${итог}`}>{РУБ(row.expected_services)}</td>
        <td className={`${клетка} ${ключевой}`}>{РУБ(row.expected_revenue)}</td>

        <td className={`${клетка} ${межблок} ${итог || обычный}`}>{РУБ(row.payroll)}</td>
        {/* Цвет вклада не зависит от того, итоговая строка или нет: знак суммы
            важнее единообразия, минус обязан быть виден сразу. */}
        <td className={`${клетка} ${принесено} ${вклад}`}>{РУБ(row.contribution)}</td>
      </tr>
    );
  };

  const подписьБлока =
    "px-3 pt-4 pb-1 text-center text-[10px] font-semibold uppercase tracking-[0.14em]";
  const подписьСтолбца = "px-3 pb-3 text-right text-[11px] font-normal";

  return (
    <div className="animate-in">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight mb-1 text-ink-soft dark:text-cream">
          Записи за месяц
        </h1>
        <p className="text-muted-light dark:text-muted text-sm">
          {периодМесяца(data.month_start, data.month_end)}. Выполненное — с первого
          числа по сейчас, будущее — до конца месяца. Отменённые и неявки не
          учитываются.
        </p>
      </div>

      {data.warnings.map((w) => (
        <div
          key={w}
          className="mb-4 flex items-start gap-2 rounded-xl border border-caution/30 bg-caution/5 px-4 py-3 text-sm text-caution"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          {w}
        </div>
      ))}

      <ClientCounters
        selected={selectedMetric?.key ?? null}
        onSelect={(key, label, тон) => setSelectedMetric({ key, label, тон })}
      />

      {/* График динамики по дням — появляется по клику на плитку выше или
          на колонку в «Возвращаемости» ниже. Решение владельца 18.09.2026:
          на этой странице такого блока раньше не было вовсе. */}
      {selectedMetric && (
        <div className="mb-6 bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <Activity
              size={16}
              className={
                selectedMetric.тон === "profit"
                  ? "text-profit"
                  : selectedMetric.тон === "loss"
                  ? "text-loss"
                  : "text-bronze dark:text-gold"
              }
            />
            <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              {selectedMetric.label}
            </h2>
            <button
              onClick={() => setSelectedMetric(null)}
              className="ml-auto text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
            >
              Скрыть график
            </button>
          </div>
          <MetricChart
            points={metricHistory[selectedMetric.key] ?? []}
            label={selectedMetric.label}
            тон={selectedMetric.тон}
            suffix={selectedMetric.key.endsWith(":return_rate_pct") ? "%" : ""}
          />
        </div>
      )}

      <div className="bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl overflow-x-auto">
        <table className="w-full min-w-[1150px] border-collapse">
          {/* Фон блоков — на столбцах. Полоса идёт на всю высоту таблицы и не
              рвётся между строками. Клетки фона не имеют, иначе они закрасят
              полосу собой. */}
          <colgroup>
            {/* Ширина первого столбца задана: иначе имя с фотографией
                растягивает его на четверть таблицы, а числа сжимаются. */}
            <col className="w-[210px]" />
            <col span={3} />
            <col span={2} className="bg-milk-deep dark:bg-panel-deep" />
            <col span={3} className="bg-bronze/[0.07] dark:bg-gold/[0.08]" />
            {/* Последний блок подсвечен сильнее остальных: в нём то, ради чего
                вся таблица, — сколько осталось салону. */}
            <col span={2} className="bg-bronze/[0.14] dark:bg-gold/[0.15]" />
          </colgroup>

          <thead>
            <tr>
              <th />
              <th className={`${подписьБлока} ${межблок} text-muted-light dark:text-muted`} colSpan={3}>
                Выполнено
              </th>
              <th className={`${подписьБлока} ${межблок} text-muted-light dark:text-muted`} colSpan={2}>
                Впереди
              </th>
              <th className={`${подписьБлока} ${межблок} text-bronze dark:text-gold`} colSpan={3}>
                Прогноз на месяц
              </th>
              <th
                className={`${подписьБлока} pt-4 ${межблок} text-bronze dark:text-gold`}
                colSpan={2}
              >
                Вклад в салон
              </th>
            </tr>
            <tr className="text-muted-light dark:text-muted">
              <th className="px-4 pb-3 text-left text-[11px] font-normal">Мастер</th>

              <th className={`${подписьСтолбца} ${межблок}`}>записей</th>
              <th className={подписьСтолбца}>услуги</th>
              <th className={подписьСтолбца}>косметика</th>

              <th className={`${подписьСтолбца} ${межблок}`}>записей</th>
              <th className={подписьСтолбца}>сумма</th>

              <th className={`${подписьСтолбца} ${межблок}`}>записей</th>
              <th className={подписьСтолбца}>услуги</th>
              <th className={подписьСтолбца}>с косметикой</th>

              <th className={`${подписьСтолбца} ${межблок}`}>зарплата</th>
              <th className={подписьСтолбца}>принесено</th>
            </tr>
          </thead>

          <tbody>
            {data.masters.map((row) => (
              <Строка key={row.staff_id} row={row} />
            ))}
            {/* Итог показываем и когда строка одна: он обязан с ней совпасть,
                и по этому видно, что ничего не потерялось. */}
            <Строка row={итог} итоговая />
          </tbody>
        </table>
      </div>

      {/* Возвращаемость: доля клиентов, пришедших к мастеру повторно —
          решение владельца 18.09.2026, «самый важный показатель для
          мастеров», уточнено в том же разговоре. Считается по всей истории
          визитов в базе — не по календарному месяцу: месячный расчёт (был
          здесь раньше) давал заниженный и мало о чём говорящий процент.
          Отдельный, более медленный запрос: может прийти позже или не
          прийти вовсе, если база ещё не досинхронизирована на нужную
          глубину — тогда блок просто не появится. */}
      {returnRate && (
        <div className="mt-4 bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl overflow-hidden">
          <div className="px-5 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-bronze dark:text-gold">
            Возвращаемость
          </div>
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-muted-light dark:text-muted">
                <th className="px-5 pb-2 pt-1 text-left text-[11px] font-normal">Мастер</th>
                <th className="px-3 pb-2 pt-1 text-right text-[11px] font-normal">потерянные</th>
                <th className="px-3 pb-2 pt-1 text-right text-[11px] font-normal">новые</th>
                <th className="px-3 pb-2 pt-1 text-right text-[11px] font-normal">
                  уникальные клиенты
                </th>
                <th className="px-5 pb-2 pt-1 text-right text-[11px] font-normal">
                  возвращаемость
                </th>
              </tr>
            </thead>
            <tbody>
              {returnRate.map((row) => {
                // Клик по числу переключает график ниже на динамику именно
                // этого показателя у этого мастера — решение владельца
                // 18.09.2026. Ключ — как в metric-history.
                const ячейка = (
                  metric: string, label: string, тон: ТонГрафика, содержимое: ReactNode, cls: string,
                ) => {
                  const key = `master:${row.staff_id}:${metric}`;
                  const активна = selectedMetric?.key === key;
                  return (
                    <td
                      onClick={() => setSelectedMetric({ key, label: `${label} — ${row.name}`, тон })}
                      className={`px-3 py-2.5 text-right cursor-pointer hover:underline ${cls} ${активна ? "underline" : ""}`}
                    >
                      {содержимое}
                    </td>
                  );
                };
                return (
                  <tr key={row.staff_id} className="border-t border-milk-line/70 dark:border-line/70">
                    <td className="px-5 py-2.5 text-ink-soft dark:text-cream">{row.name}</td>
                    {ячейка("clients_lost", "Потерянные", "loss", row.clients_lost, "text-loss font-medium")}
                    {ячейка("clients_new", "Новые", "profit", row.clients_new, "text-profit font-medium")}
                    {ячейка("clients_total", "Уникальные клиенты", "accent", row.clients_total, "text-ink-soft dark:text-cream")}
                    <td
                      onClick={() => setSelectedMetric({
                        key: `master:${row.staff_id}:return_rate_pct`,
                        label: `Возвращаемость — ${row.name}`, тон: "accent",
                      })}
                      className="px-5 py-2.5 text-right text-[15px] font-bold text-bronze dark:text-gold cursor-pointer hover:underline"
                    >
                      {row.return_rate_pct === null ? "—" : `${row.return_rate_pct}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="px-5 pb-4 pt-2 text-xs text-muted-light dark:text-muted">
            Уникальные клиенты — все, у кого хотя бы один завершённый визит к
            этому мастеру. Возвращаемость = клиенты с двумя и более визитами
            ÷ уникальные клиенты × 100%. Новые — те, чей первый визит к этому
            мастеру был в пределах последних 60 дней. Потерянные — те, чей
            последний визит или запись к этому мастеру старше 60 дней;
            будущая запись снимает статус, даже если предыдущий визит был
            давно. Клик по числу — график динамики по дням выше.
          </p>
        </div>
      )}

      {/* Продажи администраторов — отдельно от мастеров: у этих денег нет ни
          расписания, ни гаранта, ни прогноза, это просто то, что прошло не
          через трёх зарегистрированных барберов. Найдено владельцем в
          настоящем отчёте YCLIENTS 18.09.2026 — продажа товара администратором,
          которой не было ни в одной строке этой страницы. */}
      {data.admin_sales && (
        <div className="mt-4 bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl overflow-hidden">
          <div className="px-5 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-light dark:text-muted">
            Продажи администраторов
          </div>
          {data.admin_sales.masters.length === 0 ? (
            <p className="px-5 pb-4 text-sm text-muted-light dark:text-muted">
              В этом периоде — не было.
            </p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-muted-light dark:text-muted">
                  <th className="px-5 pb-2 pt-1 text-left text-[11px] font-normal">Сотрудник</th>
                  <th className="px-3 pb-2 pt-1 text-right text-[11px] font-normal">записей</th>
                  <th className="px-3 pb-2 pt-1 text-right text-[11px] font-normal">услуги</th>
                  <th className="px-5 pb-2 pt-1 text-right text-[11px] font-normal">товары</th>
                </tr>
              </thead>
              <tbody>
                {data.admin_sales.masters.map((row) => (
                  <tr key={row.staff_id} className="border-t border-milk-line/70 dark:border-line/70">
                    <td className="px-5 py-2.5 text-ink-soft dark:text-cream">{row.name}</td>
                    <td className="px-3 py-2.5 text-right text-ink-soft dark:text-cream">
                      {ШТ(row.completed_count)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-ink-soft dark:text-cream">
                      {РУБ(row.completed_revenue)}
                    </td>
                    <td className="px-5 py-2.5 text-right text-ink-soft dark:text-cream">
                      {РУБ(row.product_sales)}
                    </td>
                  </tr>
                ))}
                <tr className="border-t-2 border-milk-line dark:border-line font-semibold">
                  <td className="px-5 py-2.5 text-ink-soft dark:text-cream">Итого</td>
                  <td className="px-3 py-2.5 text-right text-ink-soft dark:text-cream">
                    {ШТ(data.admin_sales.totals.completed_count)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-ink-soft dark:text-cream">
                    {РУБ(data.admin_sales.totals.completed_revenue)}
                  </td>
                  <td className="px-5 py-2.5 text-right text-ink-soft dark:text-cream">
                    {РУБ(data.admin_sales.totals.product_sales)}
                  </td>
                </tr>
              </tbody>
            </table>
          )}
          <p className="px-5 pb-4 pt-1 text-xs text-muted-light dark:text-muted">
            Не мастера — не входят ни в «Записи», ни в расчёт ЗП. Здесь — только
            чтобы эти деньги не пропали из выручки салона ниже.
          </p>
        </div>
      )}

      {/* Прибыль по итогам месяца: выручка всего салона (мастера плюс
          администраторы) минус Фикс. Фикс редактируется на «План-факте» —
          тот же параметр, что двигает порог безубыточности везде на этой
          странице; значение одно на оба места. */}
      {(() => {
        const выручка = итог.company_revenue;
        const прибыль =
          выручка !== null && fixedMonthly !== null ? выручка - fixedMonthly : null;
        const цветПрибыли =
          прибыль === null
            ? "text-ink-soft dark:text-cream"
            : прибыль < 0
              ? "text-loss"
              : "text-profit";
        return (
          <div className="mt-4 bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl overflow-hidden">
            <div className="px-5 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-bronze dark:text-gold">
              Прибыль
            </div>
            <div className="grid grid-cols-3 divide-x divide-milk-line dark:divide-line">
              <div className="px-5 py-4 text-center">
                <div className="text-[11px] text-muted-light dark:text-muted mb-1">
                  Расчётная выручка на конец месяца, весь салон
                </div>
                <div className="text-xl font-bold text-ink-soft dark:text-cream">
                  {РУБ(выручка)}
                </div>
              </div>
              <div className="px-5 py-4 text-center">
                <div className="text-[11px] text-muted-light dark:text-muted mb-1">Фикс</div>
                <div className="text-xl font-bold text-ink-soft dark:text-cream">
                  {РУБ(fixedMonthly)}
                </div>
              </div>
              <div className="px-5 py-4 text-center">
                <div className="text-[11px] text-muted-light dark:text-muted mb-1">Прибыль</div>
                <div className={`text-xl font-bold ${цветПрибыли}`}>{РУБ(прибыль)}</div>
              </div>
            </div>
          </div>
        );
      })()}

      <div className="mt-3 space-y-1.5 text-xs text-muted-light dark:text-muted">
        <p>
          Строки отсортированы по прогнозу с косметикой — по тому числу, по
          которому мастеров и сравнивают. Прогноз — выполненное плюс будущее до
          конца месяца.
        </p>
        <p>
          <span className="text-ink-soft dark:text-cream">Принесено</span> —
          выручка мастера за вычетом его зарплаты: услуги выполненных записей
          плюс косметика минус начисленное. Будущие записи сюда не входят, их
          ещё не оплатили.
        </p>
        <p>
          «Принесено» у каждого мастера —{" "}
          <span className="text-ink-soft dark:text-cream">
            не чистая прибыль салона
          </span>
          : постоянные расходы, расходники и эквайринг по мастерам не делятся и
          здесь не вычтены.
        </p>
        <p>
          Блок <span className="text-ink-soft dark:text-cream">«Прибыль»</span>{" "}
          — выручка всего салона: прогноз по мастерам плюс продажи
          администраторов из блока выше. Из неё вычтен только Фикс —
          постоянные расходы. Расходники, эквайринг и то, что ещё не начислено
          мастерам за будущие записи, в это число не входят; полный расчёт —
          на вкладке «План-факт».
        </p>
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
    <div className="min-h-screen bg-milk dark:bg-ink text-ink-soft dark:text-cream flex">
      {/* Sidebar */}
      <aside className="w-60 border-r border-milk-line dark:border-line/50 flex flex-col fixed h-full bg-milk-card/90 dark:bg-ink/80 backdrop-blur-xl z-10">
        <div className="p-6">
          <div className="flex items-center gap-2.5 mb-8">
            <img src={logo} alt="РублЪ" className="h-12 w-auto object-contain" />
            <div>
              <div className="text-sm font-bold tracking-tight leading-none">
                Рубл<span className="text-bronze dark:text-gold">Ъ</span>
              </div>
              <div className="text-[10px] text-muted-light dark:text-muted mt-0.5">AI Director</div>
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
                      ? "bg-milk-deep dark:bg-panel-deep/80 text-ink-soft dark:text-cream font-medium"
                      : "text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream hover:bg-milk-deep dark:hover:bg-panel"
                  }`}
                >
                  <Icon size={18} className={active ? "text-bronze dark:text-gold" : ""} />
                  {item.label}
                  {active && (
                    <span className="ml-auto w-1.5 h-1.5 rounded-full bg-bronze dark:bg-gold" />
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="mt-auto p-6 border-t border-milk-line dark:border-line/50">
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-muted-light dark:text-muted hover:bg-milk-deep dark:hover:bg-panel transition-colors"
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          </button>
          {/* Свежесть данных. Здесь, а не на каждой странице по отдельности:
              боковая панель видна везде, и надпись не придётся повторять. */}
          <div className="mt-3">
            <SyncBadge />
          </div>

          {/* Кто вошёл. Мастеру это важнее всего: он должен видеть, что перед
              ним его собственный расчёт, а не чужой. */}
          <div className="text-xs text-muted-light dark:text-muted mt-3">
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
            /* key по разделу: при переходе React создаёт ограждение заново,
               и сломанная страница не держит его поднятым до перезагрузки
               окна. Сбрасывать состояние вручную для этого не нужно. */
            <PageBoundary key={page}>
              {page === "planfact" && <PlanFactPage />}
              {page === "bookings" && <BookingsPage />}
              {page === "payroll" && <BarberMonthPage payroll />}
              {page === "pulse" && <BasePulsePage />}
              {page === "shift" && <ShiftPage />}
              {page === "clients" && <ClientBasePage role={role} />}
            </PageBoundary>
          )}
        </div>
      </main>
    </div>
  );
}
