import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Download, RefreshCw, X } from "lucide-react";
import { Телефон } from "./Телефон";
import { открытьВБазе } from "./фокус";

interface Строка {
  id: number;
  at: string;
  call_date: string;
  client_id: number | null;  // null — клиента нет в базе этого компьютера
  name: string;
  phone: string | null;
  yclients_url: string | null;
  outcome: string;
  outcome_label: string;
  tags: { name: string; color: string | null }[];
  next_contact_at: string | null;
  booking: "confirmed" | "not_confirmed" | "pending" | "error" | null;
  was_lost: boolean;
  admin: string | null;
  /** Дата и время записи, которую сверка нашла в YCLIENTS. */
  booking_at: string | null;
  booking_visit: string | null;
}

interface Ответ {
  counters: { calls: number; booked: number; returned: number };
  rows: Строка[];
}

type Период = "today" | "week" | "all" | "range";

const ПЕРИОДЫ: { id: Период; label: string }[] = [
  { id: "today", label: "Сегодня" },
  { id: "week", label: "Неделя" },
  { id: "all", label: "Всё время" },
  { id: "range", label: "Интервал" },
];

const ЦВЕТ_СТАТУСА: Record<string, string> = {
  booked: "text-profit",
  callback: "text-bronze-ink dark:text-gold",
  no_booking: "text-caution",
  no_answer: "text-muted-light dark:text-muted",
  do_not_call: "text-loss",
};

/** Светофор записи: подтверждена в YCLIENTS / ждёт сверки / не нашли. */
const ЗАПИСЬ: Record<string, { label: string; color: string }> = {
  confirmed: { label: "Подтверждена", color: "#2f9e5f" },
  pending: { label: "Ждёт сверки", color: "#d0a03c" },
  error: { label: "Ждёт сверки", color: "#d0a03c" },
  not_confirmed: { label: "Не найдена", color: "#e0564b" },
};

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const дата = (s: string | null) => (s ? `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(2, 4)}` : "");
const время = (s: string) => s.slice(11, 16);
const цифры = (s: string) => s.replace(/\D/g, "");

type Колонка = "at" | "name" | "phone" | "status" | "tag" | "admin" | "call_date" | "next" | "booking";

/** Значение колонки, по которому идёт фильтр. */
function значение(r: Строка, к: Колонка): string {
  switch (к) {
    case "at": return `${дата(r.call_date)} ${время(r.at)}`;
    case "name": return r.name ?? "";
    case "phone": return r.phone ?? "";
    case "status": return r.outcome_label;
    case "tag": return r.tags.map((t) => t.name).join(" ");
    case "admin": return r.admin ?? "";
    case "call_date": return дата(r.call_date);
    case "next": return дата(r.next_contact_at);
    case "booking": return r.booking ? ЗАПИСЬ[r.booking]?.label ?? "" : "—";
  }
}

export default function ЖурналОбзвона({ role }: { role: "owner" | "operator" | "master" }) {
  const сегодня = iso(new Date());
  const [период, setПериод] = useState<Период>("today");
  const [с, setС] = useState(сегодня);
  const [по, setПо] = useState(сегодня);
  const [д, setД] = useState<Ответ | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [фильтры, setФильтры] = useState<Partial<Record<Колонка, string>>>({});
  // Клик по счётчику — фильтр журнала по этой категории (запрос 30.10.2026).
  const [категория, setКатегория] = useState<"all" | "booked" | "returned">("all");

  const границы = (): [string | null, string | null] => {
    if (период === "today") return [сегодня, сегодня];
    if (период === "week") {
      const н = new Date();
      н.setDate(н.getDate() - 6);
      return [iso(н), сегодня];
    }
    if (период === "range") return [с || null, по || null];
    return [null, null];
  };

  const загрузить = async () => {
    const [от, до] = границы();
    const q = new URLSearchParams();
    if (от) q.set("from", от);
    if (до) q.set("to", до);
    try {
      const r = await fetch(`/api/client-base/call-log?${q}`);
      if (!r.ok) throw new Error(`Сервер ответил ${r.status}`);
      setД(await r.json());
      setОшибка(null);
    } catch (e) {
      setОшибка(e instanceof Error ? e.message : "Пульт не отвечает");
    }
  };

  useEffect(() => {
    загрузить();
    // Журнал за сегодня живой: пока он открыт, подтягиваем новые звонки.
    const t = window.setInterval(загрузить, 60_000);
    return () => window.clearInterval(t);
  }, [период, с, по]);

  const строки = useMemo(() => {
    const все = (д?.rows ?? []).filter((r) =>
      категория === "all" || (r.outcome === "booked" && (категория === "booked" || r.was_lost)));
    const активные = Object.entries(фильтры).filter(([, v]) => v) as [Колонка, string][];
    if (!активные.length) return все;
    return все.filter((r) => активные.every(([к, v]) => {
      if (к === "phone") return цифры(значение(r, к)).includes(цифры(v)) || значение(r, к).includes(v);
      if (к === "status" || к === "booking" || к === "admin") return значение(r, к) === v;
      if (к === "tag") return r.tags.some((t) => t.name === v);
      return значение(r, к).toLowerCase().includes(v.toLowerCase());
    }));
  }, [д, фильтры, категория]);

  const варианты = (к: Колонка) => {
    const все = д?.rows ?? [];
    if (к === "tag") return [...new Set(все.flatMap((r) => r.tags.map((t) => t.name)))].sort();
    return [...new Set(все.map((r) => значение(r, к)))].sort();
  };

  const поставить = (к: Колонка, v: string) => setФильтры((ф) => ({ ...ф, [к]: v }));
  const естьФильтры = Object.values(фильтры).some(Boolean);
  const поле = "rubl-filter";

  const текст = (к: Колонка, подсказка: string) => (
    <input value={фильтры[к] ?? ""} onChange={(e) => поставить(к, e.target.value)} placeholder={подсказка} className={поле} />
  );
  const список = (к: Колонка) => (
    <select value={фильтры[к] ?? ""} onChange={(e) => поставить(к, e.target.value)} className={поле}>
      <option value="">все</option>
      {варианты(к).map((v) => <option key={v} value={v}>{v}</option>)}
    </select>
  );

  const счёт = д?.counters;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel/80 p-1">
            {ПЕРИОДЫ.map((п) => (
              <button
                key={п.id}
                onClick={() => setПериод(п.id)}
                className={`rounded-lg px-3 py-1.5 text-sm ${период === п.id ? "bg-milk-deep dark:bg-panel-deep font-medium text-ink-soft dark:text-cream" : "text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"}`}
              >
                {п.label}
              </button>
            ))}
          </div>
          {период === "range" && (
            <div className="flex items-center gap-1.5 text-sm">
              <input type="date" value={с} max={по || undefined} onChange={(e) => setС(e.target.value)} className={`${поле} !w-auto !text-sm`} />
              <span className="text-muted-light dark:text-muted">—</span>
              <input type="date" value={по} min={с || undefined} onChange={(e) => setПо(e.target.value)} className={`${поле} !w-auto !text-sm`} />
            </div>
          )}
        </div>

        {/* Счётчик за выбранный период. */}
        <div className="flex items-stretch gap-2">
          {([
            { id: "all", label: "Звонков", n: счёт?.calls },
            { id: "booked", label: "Записей", n: счёт?.booked, cls: "text-profit" },
            { id: "returned", label: "из них возвращённых", n: счёт?.returned, cls: "text-bronze-ink dark:text-gold" },
          ] as const).map((пл) => (
            <button
              key={пл.id}
              onClick={() => setКатегория(категория === пл.id || пл.id === "all" ? "all" : пл.id)}
              title={пл.id === "all" ? "Показать все звонки" : "Показать только эти звонки"}
              className={`rounded-xl border bg-milk-card dark:bg-panel/80 px-4 py-2 min-w-[96px] text-left transition-all ${
                категория === пл.id
                  ? "border-bronze dark:border-gold shadow-[0_0_0_1px_var(--color-bronze)] dark:shadow-[0_0_0_1px_var(--color-gold)]"
                  : "border-milk-line dark:border-line hover:border-bronze/60 dark:hover:border-gold/60"
              }`}
            >
              <div className={`text-2xl font-semibold tabular-nums leading-tight ${"cls" in пл ? пл.cls : ""}`}>{пл.n ?? "—"}</div>
              <div className="text-[11px] text-muted-light dark:text-muted">{пл.label}</div>
            </button>
          ))}
        </div>
      </div>

      {ошибка && (
        <div className="rounded-xl border border-loss/40 bg-loss/5 px-4 py-2 text-sm text-loss">{ошибка}</div>
      )}

      <div className="flex items-center justify-between text-xs text-muted-light dark:text-muted">
        <span>
          {д ? `${строки.length} из ${д.rows.length}` : "Загружаю…"}
          {(естьФильтры || категория !== "all") && (
            <button onClick={() => { setФильтры({}); setКатегория("all"); }} className="ml-3 inline-flex items-center gap-1 underline underline-offset-2">
              <X size={12} /> сбросить фильтры
            </button>
          )}
        </span>
        <span className="flex items-center gap-3">
          <button onClick={загрузить} className="inline-flex items-center gap-1 hover:text-ink-soft dark:hover:text-cream">
            <RefreshCw size={12} /> обновить
          </button>
          <a href="/api/client-base/journal" className="inline-flex items-center gap-1 hover:text-ink-soft dark:hover:text-cream">
            <Download size={12} /> Excel
          </a>
        </span>
      </div>

      <div className="rubl-scroll rubl-solid overflow-x-auto rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel shadow-sm">
        <table className="rubl-table w-full min-w-[1120px] text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-muted-light dark:text-muted">
              {["Звонок", "Имя", "Телефон", "Статус", "Хэштег", "Кто звонил", "Дата звонка", "След. звонок", "Запись", ""].map((h) => (
                <th key={h} className="px-3 pt-3 pb-1 font-medium">{h}</th>
              ))}
            </tr>
            <tr className="border-b border-milk-line dark:border-line align-top">
              <th className="px-3 pb-2 w-[110px]">{текст("at", "дд.мм")}</th>
              <th className="px-3 pb-2">{текст("name", "имя")}</th>
              <th className="px-3 pb-2 w-[220px]">{текст("phone", "цифры")}</th>
              <th className="px-3 pb-2 w-[140px]">{список("status")}</th>
              <th className="px-3 pb-2 w-[140px]">{список("tag")}</th>
              <th className="px-3 pb-2 w-[130px]">{список("admin")}</th>
              <th className="px-3 pb-2 w-[100px]">{текст("call_date", "дд.мм")}</th>
              <th className="px-3 pb-2 w-[100px]">{текст("next", "дд.мм")}</th>
              <th className="px-3 pb-2 w-[170px]">{список("booking")}</th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {строки.map((r) => {
              const запись = r.booking ? ЗАПИСЬ[r.booking] : null;
              // Запись найдена в YCLIENTS и дата известна — строка слегка зеленеет.
              const нашлась = r.booking === "confirmed" && !!r.booking_at;
              return (
                <tr key={r.id} className={`border-b border-milk-line/60 dark:border-line/60 last:border-0 ${
                  нашлась ? "rubl-tone bg-profit/[0.07] hover:bg-profit/10" : "hover:bg-milk dark:hover:bg-panel-deep/40"}`}>
                  <td className="px-3 py-2.5 tabular-nums text-muted-light dark:text-muted whitespace-nowrap">
                    {дата(r.call_date)} <span className="text-ink-soft dark:text-cream">{время(r.at)}</span>
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap text-base font-semibold text-ink-soft dark:text-cream">{r.name}</td>
                  <td className="px-3 py-2.5"><Телефон phone={r.phone} yclientsUrl={r.yclients_url} крупно /></td>
                  <td className={`px-3 py-2.5 font-medium ${ЦВЕТ_СТАТУСА[r.outcome] ?? ""}`}>
                    {r.outcome_label}
                    {r.was_lost && r.outcome === "booked" && (
                      <span className="ml-1.5 text-[10px] uppercase tracking-wide text-bronze-ink dark:text-gold" title="Был в группе «Потерянные»">возврат</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {r.tags.map((t) => (
                        <span key={t.name} className="text-xs font-medium" style={{ color: t.color ?? undefined }}>#{t.name}</span>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap">{r.admin || <span className="text-muted-light dark:text-muted">—</span>}</td>
                  <td className="px-3 py-2.5 tabular-nums">{дата(r.call_date)}</td>
                  <td className="px-3 py-2.5 tabular-nums">{дата(r.next_contact_at) || <span className="text-muted-light dark:text-muted">—</span>}</td>
                  <td className="px-3 py-2.5">
                    {запись ? (
                      <span className="inline-flex items-center gap-2 whitespace-nowrap">
                        <span className="size-3 rounded-full" style={{ background: запись.color, boxShadow: `0 0 6px ${запись.color}` }} />
                        {нашлась ? (
                          <span className="text-xs font-semibold tabular-nums text-profit" title="Дата записи из YCLIENTS">
                            {дата(r.booking_at)} {время(r.booking_at!)}
                          </span>
                        ) : (
                          <span className="text-xs">{запись.label}</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-muted-light dark:text-muted">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right">
                    {r.client_id != null && <button
                      onClick={() => открытьВБазе(r.client_id!)}
                      title="Открыть клиента в клиентской базе"
                      aria-label="Открыть клиента в клиентской базе"
                      className="rounded-md p-1.5 text-muted-light dark:text-muted hover:bg-milk-deep dark:hover:bg-panel-deep hover:text-bronze dark:hover:text-gold"
                    >
                      <ArrowUpRight size={16} />
                    </button>}
                  </td>
                </tr>
              );
            })}
            {д && строки.length === 0 && (
              <tr>
                <td colSpan={10} className="px-3 py-10 text-center text-muted-light dark:text-muted">
                  {д.rows.length ? "Под фильтр никто не подходит" : "За этот период звонков нет"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {role === "owner" && (
        <p className="text-xs text-muted-light dark:text-muted">
          Имена и телефоны клиентов хранятся только на этом компьютере и на сервер не уходят.
        </p>
      )}
    </div>
  );
}
