import { useCallback, useEffect, useState } from "react";
import { Send, Sunrise, Sunset } from "lucide-react";

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

interface ClosingSnapshot {
  shift_date: string;
  records_total: number;
  records_completed: number;
  services_revenue: number;
  products_revenue: number | null;
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

type Вид = "opening" | "closing";

const РУБ = (n: number | null): string =>
  n === null ? "данные недоступны" : Math.round(n).toLocaleString("ru-RU") + " ₽";

/** Показатель, который не удалось посчитать, пишется словами.
 *  Ноль на его месте — это уже утверждение, и притом ложное (§33 ТЗ). */
const ЧИСЛО = (n: number | null): string => (n === null ? "данные недоступны" : String(n));

/** «в 09:54» из времени отправки. */
function часы(iso: string): string {
  const д = new Date(iso);
  return `${String(д.getHours()).padStart(2, "0")}:${String(д.getMinutes()).padStart(2, "0")}`;
}

function Плитка({ label, value, крупно }: { label: string; value: string; крупно?: boolean }) {
  const нет = value === "данные недоступны";
  return (
    <div className="rounded-xl border border-milk-line dark:border-line bg-milk dark:bg-ink/40 px-4 py-3">
      <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
        {label}
      </div>
      <div
        className={
          нет
            ? "text-sm text-caution mt-1"
            : `${крупно ? "text-2xl" : "text-xl"} font-bold text-ink-soft dark:text-cream mt-0.5`
        }
      >
        {value}
      </div>
    </div>
  );
}

/** Смена: открытие утром и закрытие вечером — решение владельца 23.09.2026.
 *
 *  Страница нарочно короткая. Это рабочий инструмент администратора на два
 *  нажатия в день, а не ещё один дашборд: проверить цифры, внести время,
 *  отправить. Всё, что можно посчитать, считается само; руками вводится
 *  только время прихода и ухода.
 */
export default function ShiftPage() {
  const [state, setState] = useState<ShiftState | null>(null);
  const [занято, setЗанято] = useState<string>("");
  const [ошибка, setОшибка] = useState<string>("");
  const [превью, setПревью] = useState<{ kind: Вид; text: string } | null>(null);

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
    if (итог) setПревью({ kind, text: итог.text });
  };

  const отправить = async (kind: Вид) => {
    const итог = await запрос(`/api/shift/send?kind=${kind}`, `send-${kind}`, { method: "POST" });
    if (итог) {
      setState(итог);
      setПревью(null);
    }
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
      {state.employees.map((м) => (
        <div key={м.staff_id} className="flex items-center justify-between gap-3">
          <span className="text-sm text-ink-soft dark:text-cream">{м.name}</span>
          <input
            type="time"
            defaultValue={
              (kind === "opening" ? м.arrival_time : м.departure_time) || ""
            }
            onBlur={(e) => время(kind, м.staff_id, e.target.value)}
            className="w-28 rounded-lg border border-milk-line dark:border-line bg-milk dark:bg-ink/40 px-3 py-1.5 text-sm tabular-nums text-ink-soft dark:text-cream"
          />
        </div>
      ))}
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
        Показать сообщение
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

  return (
    <div className="animate-in max-w-3xl">
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

      <div className="grid gap-3 sm:grid-cols-2">
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
        <section className="mt-4 rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted mb-3">
            Открытие смены
          </h2>
          <div className="grid gap-3 grid-cols-2 sm:grid-cols-3">
            <Плитка label="План на день" value={РУБ(открытие.plan)} крупно />
            <Плитка label="Работает мастеров" value={String(открытие.masters_working)} />
            <Плитка label="Новые" value={ЧИСЛО(открытие.clients.new)} />
            <Плитка label="Второй визит" value={ЧИСЛО(открытие.clients.second)} />
            <Плитка label="Станут постоянными" value={ЧИСЛО(открытие.clients.will_be_regular)} />
          </div>
          <Предупреждения список={открытие.warnings} />
          <Мастера kind="opening" />
          <Отправка kind="opening" sent={state.opening_sent_at} />
        </section>
      )}

      {закрытие && (
        <section className="mt-4 rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted mb-3">
            Закрытие смены
          </h2>
          <div className="grid gap-3 grid-cols-2 sm:grid-cols-3">
            <Плитка label="Записано" value={String(закрытие.records_total)} />
            <Плитка label="Выполнено" value={String(закрытие.records_completed)} />
            <Плитка label="Услуги" value={РУБ(закрытие.services_revenue)} крупно />
            <Плитка label="Товары" value={РУБ(закрытие.products_revenue)} />
            <Плитка label="Записались дальше" value={String(закрытие.clients.booked_next)} />
            <Плитка label="Не записались" value={String(закрытие.clients.not_booked)} />
            <Плитка
              label="Создано на будущее"
              value={ЧИСЛО(закрытие.created_today_for_future)}
            />
            <Плитка label="Новых пришло" value={ЧИСЛО(закрытие.completed.new)} />
            <Плитка label="Стали постоянными" value={ЧИСЛО(закрытие.completed.became_regular)} />
            <Плитка label="Стали потерянными" value={ЧИСЛО(закрытие.lost_today)} />
          </div>
          <Предупреждения список={закрытие.warnings} />
          {закрытие.integrity_failures.length > 0 && (
            <div className="mt-3 rounded-xl border border-loss/30 bg-loss/5 px-4 py-3 text-sm text-loss">
              Проверки расчёта не прошли: {закрытие.integrity_failures.join("; ")}. Цифрам верить
              нельзя — покажите это сообщение разработчику.
            </div>
          )}
          <Мастера kind="closing" />
          <Отправка kind="closing" sent={state.closing_sent_at} />
        </section>
      )}

      {превью && (
        <section className="mt-4 rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              Сообщение в Telegram
            </h2>
            <button
              onClick={() => setПревью(null)}
              className="text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
            >
              Скрыть
            </button>
          </div>
          <pre className="whitespace-pre-wrap text-sm text-ink-soft dark:text-cream">
            {превью.text}
          </pre>
        </section>
      )}
    </div>
  );
}
