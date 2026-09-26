import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { LogIn, LogOut, Pencil, Send, Sunrise, Sunset, X } from "lucide-react";

/** Мастер в смене: время вводит администратор, из YCLIENTS оно не берётся. */
interface ShiftEmployee {
  staff_id: number;
  name: string;
  arrival_time: string | null;
  departure_time: string | null;
}

interface OpeningSnapshot {
  shift_date: string;
  plan: number;
  masters_working: number;
  masters: { staff_id: number; name: string }[];
  clients: { new: number | null; second: number | null; will_be_regular: number | null };
  warnings: string[];
}

interface ДеньгиСмены {
  total_earned: number | null;
  non_cash: number | null;
  cash: number | null;
  spent: number | null;
  cash_register_estimate: number | null;
  settlement_account_estimate: number | null;
  other_account_debt: number | null;
}

/** Ответ /api/shift/money/balances. Все поля null, пока владелец ни разу не
 *  внёс остатки. */
interface Остатки {
  cash_amount: number | null;
  cash_as_of: string | null;
  settlement_amount: number | null;
  settlement_as_of: string | null;
  other_account_debt: number | null;
  other_debt_note: string | null;
  updated_at: string | null;
}

interface ClosingSnapshot {
  shift_date: string;
  records_total: number;
  records_completed: number;
  services_revenue: number;
  products_revenue: number | null;
  /** Необязательно: снимок, отправленный до появления блока «Деньги» (или до
   *  появления в нём поля долга), навсегда остался без него — §32 ТЗ смены
   *  запрещает пересчитывать отправленное закрытие задним числом. */
  money?: ДеньгиСмены;
  clients: { booked_next: number; not_booked: number };
  created_today_for_future: number | null;
  completed: { new: number | null; became_regular: number | null };
  lost_today: number | null;
  warnings: string[];
  integrity_failures: string[];
}

interface ShiftState {
  exists: boolean;
  shift_date: string;
  opened_at: string | null;
  closed_at: string | null;
  opening_sent_at: string | null;
  closing_sent_at: string | null;
  opening_snapshot: OpeningSnapshot | null;
  closing_snapshot: ClosingSnapshot | null;
  employees: ShiftEmployee[];
}

/** Строка расшифровки: /api/shift/money/services и /money/products.
 *  Клиент и время — только у услуг, товары продаются без записи на визит. */
interface СтрокаДенег {
  time?: string;
  client?: string | null;
  master: string;
  title: string;
  amount: number;
}

type Вид = "opening" | "closing";
type РазделДенег = "services" | "products";

const РУБ = (n: number | null | undefined): string =>
  n === null || n === undefined ? "данные недоступны" : Math.round(n).toLocaleString("ru-RU") + " ₽";

/** Показатель, который не удалось посчитать, пишется словами.
 *  Ноль на его месте — это уже утверждение, и притом ложное (§33 ТЗ). */
const ЧИСЛО = (n: number | null): string => (n === null ? "данные недоступны" : String(n));

/** «в 09:54» из времени отправки. */
function часы(iso: string): string {
  const д = new Date(iso);
  return `${String(д.getHours()).padStart(2, "0")}:${String(д.getMinutes()).padStart(2, "0")}`;
}

/** Текущее время в Москве, ЧЧ:ММ — для кнопок «Пришёл»/«Ушёл».
 *
 *  Через formatToParts, а не через строку локали: у разных локалей и
 *  окружений разный порядок частей и разделитель, а часовой пояс салона —
 *  Europe/Moscow всегда, независимо от того, где физически стоит сервер. */
function московскоеВремя(): string {
  const части = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Moscow",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date());
  const час = части.find((ч) => ч.type === "hour")?.value ?? "00";
  const минута = части.find((ч) => ч.type === "minute")?.value ?? "00";
  return `${час}:${минута}`;
}

function Плитка({
  label,
  value,
  крупно,
  тон,
  onClick,
}: {
  label: string;
  value: string;
  крупно?: boolean;
  /** Смысловая окраска: positive — хорошая новость, negative — плохая. Без
   *  значения плитка нейтральна — это факт, а не оценка. */
  тон?: "positive" | "negative";
  /** Если задан — плитка кликабельна и открывает расшифровку. */
  onClick?: () => void;
}) {
  const нет = value === "данные недоступны";
  const цвет = нет
    ? "text-caution"
    : тон === "positive"
      ? "text-profit"
      : тон === "negative"
        ? "text-loss"
        : "text-ink-soft dark:text-cream";
  return (
    <div
      onClick={onClick}
      className={`rounded-xl border border-milk-line dark:border-line bg-milk dark:bg-ink/40 px-4 py-3 ${
        onClick ? "cursor-pointer transition-colors hover:border-bronze/50 dark:hover:border-gold/50" : ""
      }`}
    >
      <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
        {label}
      </div>
      <div className={`${крупно ? "text-2xl" : "text-xl"} font-bold mt-0.5 ${цвет}`}>
        {value}
      </div>
    </div>
  );
}

/** Заголовок тематического подблока внутри карточки закрытия. */
function Раздел({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-4 first:mt-0">
      <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted mb-2">
        {title}
      </div>
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-3">{children}</div>
    </div>
  );
}

/** Итог: сумма клиентов у которых оба поля не работают — сразу заметно.
 *  Строка со списком — то, что стоит за кликнутой плиткой «Услуги»/«Товары». */
function РасшифровкаДенег({ раздел, строки }: { раздел: РазделДенег; строки: СтрокаДенег[] }) {
  if (строки.length === 0) {
    return (
      <p className="text-sm text-muted-light dark:text-muted py-2">
        {раздел === "services" ? "Услуг сегодня не продано." : "Товаров сегодня не продано."}
      </p>
    );
  }
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="text-muted-light dark:text-muted">
          {раздел === "services" && (
            <>
              <th className="pb-1.5 text-left text-[11px] font-normal">Время</th>
              <th className="pb-1.5 text-left text-[11px] font-normal">Клиент</th>
            </>
          )}
          <th className="pb-1.5 text-left text-[11px] font-normal">Мастер</th>
          <th className="pb-1.5 text-left text-[11px] font-normal">
            {раздел === "services" ? "Услуга" : "Товар"}
          </th>
          <th className="pb-1.5 text-right text-[11px] font-normal">Сумма</th>
        </tr>
      </thead>
      <tbody>
        {строки.map((с, i) => (
          <tr key={i} className="border-t border-milk-line/70 dark:border-line/70">
            {раздел === "services" && (
              <>
                <td className="py-1.5 tabular-nums text-muted-light dark:text-muted">
                  {с.time ?? "—"}
                </td>
                <td className="py-1.5 text-ink-soft dark:text-cream">{с.client ?? "—"}</td>
              </>
            )}
            <td className="py-1.5 text-muted-light dark:text-muted">{с.master}</td>
            <td className="py-1.5 text-ink-soft dark:text-cream">{с.title}</td>
            <td className="py-1.5 text-right tabular-nums text-ink-soft dark:text-cream">
              {РУБ(с.amount)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Сегодняшняя дата ГГГГ-ММ-ДД для значения по умолчанию в полях даты. */
function сегодняISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Форма остатков — доступна только владельцу (§ решение 26.09.2026).
 *
 *  Регистр день-за-днём YCLIENTS вести не позволяет: касса и счёт хранятся
 *  как известное значение на дату, а не пересчитываются сами. Долг перед
 *  другим счётом YCLIENTS не видит вовсе — это исключительно ручная цифра.
 */
/* oxlint-disable react-hooks/rules-of-hooks -- имя компонента на кириллице,
   как и весь проект; JSX-компилятор классифицирует его по регистру первого
   символа (не ASCII a-z), а не по латинице, поэтому это ложное срабатывание
   линтера — компонент настоящий и вызывается как обычно, см. ПлиткаСегмента
   в BasePulsePage.tsx с тем же случаем. */
function ФормаОстатков({
  остатки,
  занято,
  onSave,
  onCancel,
}: {
  остатки: Остатки | null;
  занято: boolean;
  onSave: (значения: {
    cash_amount: string;
    cash_as_of: string;
    settlement_amount: string;
    settlement_as_of: string;
    other_account_debt: string;
    other_debt_note: string;
  }) => void;
  onCancel: () => void;
}) {
  const [cashAmount, setCashAmount] = useState(String(остатки?.cash_amount ?? ""));
  const [cashAsOf, setCashAsOf] = useState(остатки?.cash_as_of ?? сегодняISO());
  const [settlementAmount, setSettlementAmount] = useState(
    String(остатки?.settlement_amount ?? "")
  );
  const [settlementAsOf, setSettlementAsOf] = useState(остатки?.settlement_as_of ?? сегодняISO());
  const [otherDebt, setOtherDebt] = useState(String(остатки?.other_account_debt ?? "0"));
  const [otherNote, setOtherNote] = useState(остатки?.other_debt_note ?? "");

  const поле = "w-full rounded-lg border border-milk-line dark:border-line bg-milk dark:bg-ink/40 px-3 py-1.5 text-sm text-ink-soft dark:text-cream";
  const подпись = "text-[11px] uppercase tracking-widest text-muted-light dark:text-muted mb-1";

  return (
    <div className="mt-3 rounded-xl border border-milk-line dark:border-line bg-milk dark:bg-ink/40 p-3 space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <div className={подпись}>Наличными в кассе</div>
          <input
            type="number"
            value={cashAmount}
            onChange={(e) => setCashAmount(e.target.value)}
            className={поле}
          />
        </div>
        <div>
          <div className={подпись}>На какую дату</div>
          <input
            type="date"
            value={cashAsOf}
            onChange={(e) => setCashAsOf(e.target.value)}
            className={поле}
          />
        </div>
        <div>
          <div className={подпись}>На расчётном счёте</div>
          <input
            type="number"
            value={settlementAmount}
            onChange={(e) => setSettlementAmount(e.target.value)}
            className={поле}
          />
        </div>
        <div>
          <div className={подпись}>На какую дату</div>
          <input
            type="date"
            value={settlementAsOf}
            onChange={(e) => setSettlementAsOf(e.target.value)}
            className={поле}
          />
        </div>
        <div>
          <div className={подпись}>Долг по другому счёту</div>
          <input
            type="number"
            value={otherDebt}
            onChange={(e) => setOtherDebt(e.target.value)}
            placeholder="0"
            className={поле}
          />
        </div>
        <div>
          <div className={подпись}>Заметка к долгу (необязательно)</div>
          <input
            type="text"
            value={otherNote}
            onChange={(e) => setOtherNote(e.target.value)}
            placeholder="например, с какого счёта заняли"
            className={поле}
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() =>
            onSave({
              cash_amount: cashAmount,
              cash_as_of: cashAsOf,
              settlement_amount: settlementAmount,
              settlement_as_of: settlementAsOf,
              other_account_debt: otherDebt,
              other_debt_note: otherNote,
            })
          }
          disabled={занято}
          className="rounded-lg bg-bronze dark:bg-gold px-3 py-1.5 text-sm font-semibold text-milk dark:text-ink disabled:opacity-50"
        >
          Сохранить
        </button>
        <button
          onClick={onCancel}
          className="rounded-lg border border-milk-line dark:border-line px-3 py-1.5 text-sm text-ink-soft dark:text-cream"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}
/* oxlint-enable react-hooks/rules-of-hooks */

/** Смена: открытие утром и закрытие вечером — решение владельца 23.09.2026.
 *
 *  Данные и сообщение для Telegram стоят рядом, а не одно под другим
 *  (решение владельца 26.09.2026): проверил цифры — тут же увидел, что
 *  уйдёт в чат, не листая страницу.
 */
export default function ShiftPage({ role }: { role: "owner" | "operator" | "master" }) {
  const [state, setState] = useState<ShiftState | null>(null);
  const [занято, setЗанято] = useState<string>("");
  const [ошибка, setОшибка] = useState<string>("");
  const [превью, setПревью] = useState<Record<Вид, string | null>>({
    opening: null,
    closing: null,
  });
  const [деньгиОткрыто, setДеньгиОткрыто] = useState<РазделДенег | null>(null);
  const [деньгиСтроки, setДеньгиСтроки] = useState<СтрокаДенег[] | null>(null);
  const [остатки, setОстатки] = useState<Остатки | null>(null);
  const [формаОстатков, setФормаОстатков] = useState(false);

  const обновить = useCallback(async () => {
    try {
      const r = await fetch("/api/shift/today");
      if (!r.ok) throw new Error(`сервер ответил ${r.status}`);
      setState(await r.json());
    } catch (e) {
      setОшибка(e instanceof Error ? e.message : "не удалось получить состояние смены");
    }
  }, []);

  useEffect(() => {
    обновить();
  }, [обновить]);

  useEffect(() => {
    if (role !== "owner") return;
    (async () => {
      try {
        const r = await fetch("/api/shift/money/balances");
        if (r.ok) setОстатки(await r.json());
      } catch {
        // форма редактирования просто не подставит старые значения
      }
    })();
  }, [role]);

  const запрос = async (путь: string, метка: string, опции?: RequestInit) => {
    setЗанято(метка);
    setОшибка("");
    try {
      const r = await fetch(путь, опции);
      const тело = await r.json().catch(() => null);
      if (!r.ok) throw new Error(тело?.detail || `сервер ответил ${r.status}`);
      return тело;
    } catch (e) {
      setОшибка(e instanceof Error ? e.message : "не получилось");
      return null;
    } finally {
      setЗанято("");
    }
  };

  const открыть = async () => {
    const итог = await запрос("/api/shift/open", "open", { method: "POST" });
    if (итог) setState(итог);
  };

  const закрыть = async () => {
    const итог = await запрос("/api/shift/close", "close", { method: "POST" });
    if (итог) setState(итог);
  };

  const время = async (kind: Вид, staff_id: number, значение: string) => {
    if (!значение) return;
    const итог = await запрос(`/api/shift/times?kind=${kind}`, `time-${staff_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [String(staff_id)]: значение }),
    });
    if (итог) setState(итог);
  };

  const показать = async (kind: Вид) => {
    const итог = await запрос(`/api/shift/preview?kind=${kind}`, `preview-${kind}`);
    if (итог) setПревью((п) => ({ ...п, [kind]: итог.text }));
  };

  const отправить = async (kind: Вид) => {
    const итог = await запрос(`/api/shift/send?kind=${kind}`, `send-${kind}`, { method: "POST" });
    if (итог) {
      setState(итог);
      setПревью((п) => ({ ...п, [kind]: null }));
    }
  };

  const сохранитьОстатки = async (значения: {
    cash_amount: string;
    cash_as_of: string;
    settlement_amount: string;
    settlement_as_of: string;
    other_account_debt: string;
    other_debt_note: string;
  }) => {
    const итог = await запрос("/api/shift/money/balances", "balances", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cash_amount: Number(значения.cash_amount) || 0,
        cash_as_of: значения.cash_as_of,
        settlement_amount: Number(значения.settlement_amount) || 0,
        settlement_as_of: значения.settlement_as_of,
        other_account_debt: Number(значения.other_account_debt) || 0,
        other_debt_note: значения.other_debt_note || null,
      }),
    });
    if (!итог) return;
    setОстатки(итог);
    setФормаОстатков(false);
    // Смена уже закрыта, но ещё не отправлена — цифры в блоке «Деньги»
    // пересчитываются заново, как и всё закрытие (§32 ТЗ), иначе владелец
    // внёс остатки и не увидел бы их до завтрашнего закрытия.
    if (state?.closing_snapshot && !state.closing_sent_at) {
      const обновлённое = await запрос("/api/shift/close", "close", { method: "POST" });
      if (обновлённое) setState(обновлённое);
    }
  };

  const переключитьДеньги = async (раздел: РазделДенег) => {
    if (деньгиОткрыто === раздел) {
      setДеньгиОткрыто(null);
      return;
    }
    setДеньгиОткрыто(раздел);
    setДеньгиСтроки(null);
    const итог = await запрос(`/api/shift/money/${раздел}`, `money-${раздел}`);
    setДеньгиСтроки(итог ?? []);
  };

  if (!state) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-light dark:text-muted">
        {ошибка ? `Не удалось получить данные. ${ошибка}` : "Загружаю…"}
      </div>
    );
  }

  const открытие = state.opening_snapshot;
  const закрытие = state.closing_snapshot;

  const Мастера = ({ kind }: { kind: Вид }) => (
    <div className="mt-4 space-y-2">
      <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
        {kind === "opening" ? "Время прихода" : "Время ухода"}
      </div>
      {state.employees.map((м) => {
        const текущее = kind === "opening" ? м.arrival_time : м.departure_time;
        return (
          <div key={м.staff_id} className="flex items-center justify-between gap-3">
            <span className="text-sm text-ink-soft dark:text-cream truncate">{м.name}</span>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => время(kind, м.staff_id, московскоеВремя())}
                disabled={занято !== ""}
                title="Проставить текущее время"
                className="inline-flex items-center gap-1.5 rounded-lg border border-milk-line dark:border-line px-2.5 py-1.5 text-xs font-medium text-ink-soft dark:text-cream disabled:opacity-50 hover:border-bronze/50 dark:hover:border-gold/50"
              >
                {kind === "opening" ? <LogIn size={13} /> : <LogOut size={13} />}
                {kind === "opening" ? "Пришёл" : "Ушёл"}
              </button>
              <input
                type="time"
                key={текущее ?? "пусто"}
                defaultValue={текущее || ""}
                onBlur={(e) => время(kind, м.staff_id, e.target.value)}
                className="w-28 rounded-lg border border-milk-line dark:border-line bg-milk dark:bg-ink/40 px-3 py-1.5 text-sm tabular-nums text-ink-soft dark:text-cream"
              />
            </div>
          </div>
        );
      })}
      {state.employees.length === 0 && (
        <p className="text-sm text-muted-light dark:text-muted">
          Работающих мастеров на сегодня не нашлось.
        </p>
      )}
    </div>
  );

  const Отправка = ({ kind, sent }: { kind: Вид; sent: string | null }) => (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <button
        onClick={() => показать(kind)}
        disabled={занято !== ""}
        className="rounded-lg border border-milk-line dark:border-line px-3 py-1.5 text-sm text-ink-soft dark:text-cream disabled:opacity-50"
      >
        {превью[kind] ? "Обновить сообщение" : "Показать сообщение"}
      </button>
      <button
        onClick={() => отправить(kind)}
        disabled={занято !== ""}
        className="inline-flex items-center gap-2 rounded-lg bg-bronze dark:bg-gold px-3 py-1.5 text-sm font-semibold text-milk dark:text-ink disabled:opacity-50"
      >
        <Send size={14} />
        {занято === `send-${kind}` ? "Отправляю…" : "Отправить в Telegram"}
      </button>
      {sent && (
        <span className="text-xs text-muted-light dark:text-muted">
          Отправлено в Telegram в {часы(sent)}
        </span>
      )}
    </div>
  );

  const Предупреждения = ({ список }: { список: string[] }) =>
    список.length === 0 ? null : (
      <ul className="mt-3 space-y-1">
        {список.map((текст) => (
          <li key={текст} className="text-xs text-caution">
            {текст}
          </li>
        ))}
      </ul>
    );

  /** Правая колонка ряда: текст сообщения или заглушка тех же пропорций,
   *  что и карточка слева, — иначе сетка «поедет» на втором ряду. */
  const Сообщение = ({ kind }: { kind: Вид }) => (
    <section className="mt-4 lg:mt-0 rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5 h-full">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted mb-3">
        Сообщение в Telegram
      </h2>
      {превью[kind] ? (
        <pre className="whitespace-pre-wrap text-sm text-ink-soft dark:text-cream">
          {превью[kind]}
        </pre>
      ) : (
        <p className="text-sm text-muted-light dark:text-muted">
          Нажмите «Показать сообщение», чтобы увидеть текст перед отправкой.
        </p>
      )}
    </section>
  );

  return (
    <div className="animate-in">
      <div className="mb-5">
        <h1 className="text-2xl font-bold tracking-tight mb-1 text-ink-soft dark:text-cream">
          Смена
        </h1>
        <p className="text-muted-light dark:text-muted text-sm">
          Утром — план на день, вечером — факт. Руками вносится только время прихода и ухода:
          остальное считается по данным YCLIENTS.
        </p>
      </div>

      {ошибка && (
        <div className="mb-4 rounded-xl border border-caution/30 bg-caution/5 px-4 py-3 text-sm text-caution">
          {ошибка}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 max-w-2xl">
        <button
          onClick={открыть}
          disabled={занято !== ""}
          className="inline-flex items-center justify-center gap-2 rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-5 py-4 text-sm font-semibold text-ink-soft dark:text-cream disabled:opacity-50"
        >
          <Sunrise size={18} className="text-bronze dark:text-gold" />
          {занято === "open" ? "Считаю…" : "Открыть смену"}
        </button>
        <button
          onClick={закрыть}
          disabled={занято !== ""}
          className="inline-flex items-center justify-center gap-2 rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-5 py-4 text-sm font-semibold text-ink-soft dark:text-cream disabled:opacity-50"
        >
          <Sunset size={18} className="text-bronze dark:text-gold" />
          {занято === "close" ? "Считаю…" : "Закрыть смену"}
        </button>
      </div>

      {открытие && (
        <div className="grid gap-4 lg:grid-cols-2 items-start mt-4">
          <section className="rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted mb-3">
              Открытие смены
            </h2>
            <div className="grid gap-3 grid-cols-2 sm:grid-cols-3">
              <Плитка label="План на день" value={РУБ(открытие.plan)} крупно />
              <Плитка label="Работает мастеров" value={String(открытие.masters_working)} />
              <Плитка label="Новые" value={ЧИСЛО(открытие.clients.new)} />
              <Плитка label="Второй визит" value={ЧИСЛО(открытие.clients.second)} />
              <Плитка
                label="Станут постоянными"
                value={ЧИСЛО(открытие.clients.will_be_regular)}
              />
            </div>
            <Предупреждения список={открытие.warnings} />
            <Мастера kind="opening" />
            <Отправка kind="opening" sent={state.opening_sent_at} />
          </section>
          <Сообщение kind="opening" />
        </div>
      )}

      {закрытие && (
        <div className="grid gap-4 lg:grid-cols-2 items-start mt-4">
          <section className="rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted mb-1">
              Закрытие смены
            </h2>

            <Раздел title="Записи">
              <Плитка label="Записано" value={String(закрытие.records_total)} />
              <Плитка label="Выполнено" value={String(закрытие.records_completed)} />
            </Раздел>

            <div className="mt-4 first:mt-0">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
                  Деньги
                </div>
                {role === "owner" && !формаОстатков && (
                  <button
                    onClick={() => setФормаОстатков(true)}
                    className="inline-flex items-center gap-1 text-[11px] text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
                  >
                    <Pencil size={11} />
                    Остатки
                  </button>
                )}
                {формаОстатков && (
                  <button
                    onClick={() => setФормаОстатков(false)}
                    className="text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
              <div className="grid gap-3 grid-cols-2 sm:grid-cols-3">
                <Плитка
                  label="Заработано всего"
                  value={РУБ(закрытие.money?.total_earned)}
                  крупно
                />
                <Плитка label="Из них безнал" value={РУБ(закрытие.money?.non_cash)} />
                <Плитка label="Наличка" value={РУБ(закрытие.money?.cash)} />
                <Плитка
                  label="Услуги"
                  value={РУБ(закрытие.services_revenue)}
                  onClick={() => переключитьДеньги("services")}
                />
                <Плитка
                  label="Товары"
                  value={РУБ(закрытие.products_revenue)}
                  onClick={() => переключитьДеньги("products")}
                />
                <Плитка label="Потрачено" value={РУБ(закрытие.money?.spent)} тон="negative" />
                <Плитка
                  label="В кассе (расчётно)"
                  value={РУБ(закрытие.money?.cash_register_estimate)}
                />
                <Плитка
                  label="На расчётном счёте (расчётно)"
                  value={РУБ(закрытие.money?.settlement_account_estimate)}
                />
                <Плитка
                  label="Долг по другому счёту"
                  value={РУБ(закрытие.money?.other_account_debt)}
                  тон={
                    закрытие.money?.other_account_debt && закрытие.money?.other_account_debt > 0
                      ? "negative"
                      : undefined
                  }
                />
              </div>
              {формаОстатков && (
                <ФормаОстатков
                  остатки={остатки}
                  занято={занято !== ""}
                  onSave={сохранитьОстатки}
                  onCancel={() => setФормаОстатков(false)}
                />
              )}
            </div>
            {деньгиОткрыто && (
              <div className="mt-3 rounded-xl border border-milk-line dark:border-line bg-milk dark:bg-ink/40 px-3 py-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
                    Из чего сложилось: {деньгиОткрыто === "services" ? "услуги" : "товары"}
                  </span>
                  <button
                    onClick={() => setДеньгиОткрыто(null)}
                    className="text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
                  >
                    Скрыть
                  </button>
                </div>
                {деньгиСтроки === null ? (
                  <p className="text-sm text-muted-light dark:text-muted py-2">Загружаю…</p>
                ) : (
                  <РасшифровкаДенег раздел={деньгиОткрыто} строки={деньгиСтроки} />
                )}
              </div>
            )}

            <Раздел title="Клиенты">
              <Плитка
                label="Записались дальше"
                value={String(закрытие.clients.booked_next)}
                тон="positive"
              />
              <Плитка
                label="Не записались"
                value={String(закрытие.clients.not_booked)}
                тон="negative"
              />
            </Раздел>

            <Раздел title="Новые записи">
              <Плитка
                label="Создано на будущее"
                value={ЧИСЛО(закрытие.created_today_for_future)}
              />
            </Раздел>

            <Раздел title="Выполнено">
              <Плитка label="Новых пришло" value={ЧИСЛО(закрытие.completed.new)} тон="positive" />
              <Плитка
                label="Стали постоянными"
                value={ЧИСЛО(закрытие.completed.became_regular)}
                тон="positive"
                крупно
              />
            </Раздел>

            <Раздел title="Потерянные">
              <Плитка label="Сегодня" value={ЧИСЛО(закрытие.lost_today)} тон="negative" />
            </Раздел>

            <Предупреждения список={закрытие.warnings} />
            {закрытие.integrity_failures.length > 0 && (
              <div className="mt-3 rounded-xl border border-loss/30 bg-loss/5 px-4 py-3 text-sm text-loss">
                Проверки расчёта не прошли: {закрытие.integrity_failures.join("; ")}. Цифрам
                верить нельзя — покажите это сообщение разработчику.
              </div>
            )}
            <Мастера kind="closing" />
            <Отправка kind="closing" sent={state.closing_sent_at} />
          </section>
          <Сообщение kind="closing" />
        </div>
      )}
    </div>
  );
}
