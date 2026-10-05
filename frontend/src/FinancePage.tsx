import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertTriangle, ArrowDown, ArrowRight, ArrowUp, ChevronLeft, ChevronRight, Pencil, RefreshCw, Upload, X } from "lucide-react";
import { useDark, палитраГрафика } from "./тема";

// ── Типы ответа /api/finance-analysis ─────────────────────────────────────

type Num = number | null;

interface День {
  date: string;
  non_cash: Num;
  cash: Num;
  bank: Num;
  diff: Num;
  /** Наличка за день, пересчитанная админом при закрытии смены. */
  cash_fact?: Num;
  cash_diff?: Num;
  status: "ok" | "mismatch" | "no_bank" | "no_shift" | "no_data" | "pending";
}

interface Статья {
  title: string;
  group: string;
  total: number;
  share_pct: Num;
  count: number;
  prev_total: Num;
  delta_pct: Num;
}

interface Расходы {
  total: Num;
  prev_total: Num;
  delta_pct: Num;
  pct_of_sales: Num;
  cash: Num;
  bank: Num;
  transfers: Num;
  articles: Статья[];
  groups: {
    name: string; total: number; share_pct: Num;
    pct_of_income?: Num; prev_pct_of_income?: Num; delta_pp?: Num;
  }[];
  watch: string[];
  income?: Num;
  expenses_pct_of_income?: Num;
}

interface Данные {
  month: string;
  balances: {
    entered: boolean;
    upto: string;
    cash?: { baseline: number; as_of: string; calc: Num };
    rs?: {
      baseline: number;
      as_of: string;
      calc_yclients: Num;
      calc_bank: Num;
      bank_days: number;
    };
    missing_closure_days?: string[];
  };
  debt: { amount: Num; note: string | null; updated_at: string | null };
  totals: {
    non_cash_shift: Num;
    cash_shift: Num;
    bank_turnover: Num;
    bank_fee: Num;
    bank_net: Num;
    compared_days: number;
    mismatch_days: number;
    diff_total: Num;
    sales_total: Num;
  };
  days: День[];
  expenses: Расходы | null;
  warnings: string[];
}


// ── Форматирование ────────────────────────────────────────────────────────

const КАРТОЧКА =
  "rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-4";
const ПОЛЕ =
  "rounded-lg border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-3 py-2 text-sm text-ink-soft dark:text-cream";
const НЕТ = "—";

const руб = (v: Num | undefined) =>
  v == null ? НЕТ : `${v.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`;
const проц = (v: Num | undefined) =>
  v == null ? НЕТ : `${v.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
const датаКратко = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

function текущийМесяц(): string {
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Moscow" }));
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function Tile({
  название,
  значение,
  пояснение,
  тон,
}: {
  название: string;
  значение: string;
  пояснение?: string;
  тон?: "минус" | "плюс";
}) {
  return (
    <div className={КАРТОЧКА}>
      <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">
        {название}
      </div>
      <div
        className={`mt-1 text-xl font-semibold ${
          тон === "минус" ? "text-loss" : тон === "плюс" ? "text-profit" : "text-ink-soft dark:text-cream"
        }`}
      >
        {значение}
      </div>
      {пояснение && (
        <div className="mt-1 text-xs text-muted-light dark:text-muted">{пояснение}</div>
      )}
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
      {children}
    </h2>
  );
}

// ── Форма остатков и долга ────────────────────────────────────────────────

function BalancesForm({
  начало,
  onDone,
  onCancel,
}: {
  начало: {
    cash: number | null;
    cashDate: string | null;
    rs: number | null;
    rsDate: string | null;
    debt: number | null;
    note: string | null;
  };
  onDone: () => void;
  onCancel: () => void;
}) {
  const вчера = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
  const [касса, setКасса] = useState(String(начало.cash ?? ""));
  const [датаКассы, setДатаКассы] = useState(начало.cashDate ?? вчера);
  const [рс, setРс] = useState(String(начало.rs ?? ""));
  const [датаРс, setДатаРс] = useState(начало.rsDate ?? вчера);
  const [долг, setДолг] = useState(String(начало.debt ?? "0"));
  const [заметка, setЗаметка] = useState(начало.note ?? "");
  const [занято, setЗанято] = useState(false);
  const [ошибка, setОшибка] = useState<string | null>(null);

  const сохранить = async () => {
    setЗанято(true);
    setОшибка(null);
    try {
      const r = await fetch("/api/finance-analysis/balances", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cash_amount: касса || "0",
          cash_as_of: датаКассы,
          settlement_amount: рс || "0",
          settlement_as_of: датаРс,
          other_account_debt: долг || "0",
          other_debt_note: заметка,
        }),
      });
      if (!r.ok) {
        const тело = await r.json().catch(() => ({}));
        setОшибка(тело.detail || "Не удалось сохранить");
        return;
      }
      onDone();
    } catch {
      setОшибка("Сервер не отвечает");
    } finally {
      setЗанято(false);
    }
  };

  const подпись = "text-xs text-muted-light dark:text-muted mb-1";
  return (
    <div className={КАРТОЧКА + " space-y-3"}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-soft dark:text-cream">Остатки и долг</h3>
        <button onClick={onCancel} aria-label="Закрыть">
          <X size={16} />
        </button>
      </div>
      <p className="text-xs text-muted-light dark:text-muted">
        Внесите сумму на конец указанного дня. Дальше остатки считаются сами: плюс поступления по
        закрытиям смены, минус расходы YCLIENTS.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label>
          <div className={подпись}>Наличные в кассе, ₽</div>
          <input className={ПОЛЕ + " w-full"} inputMode="decimal" value={касса} onChange={(e) => setКасса(e.target.value)} />
        </label>
        <label>
          <div className={подпись}>…на конец дня</div>
          <input type="date" className={ПОЛЕ + " w-full"} value={датаКассы} onChange={(e) => setДатаКассы(e.target.value)} />
        </label>
        <label>
          <div className={подпись}>На расчётном счёте, ₽</div>
          <input className={ПОЛЕ + " w-full"} inputMode="decimal" value={рс} onChange={(e) => setРс(e.target.value)} />
        </label>
        <label>
          <div className={подпись}>…на конец дня</div>
          <input type="date" className={ПОЛЕ + " w-full"} value={датаРс} onChange={(e) => setДатаРс(e.target.value)} />
        </label>
        <label>
          <div className={подпись}>Долг по другому счёту, ₽</div>
          <input className={ПОЛЕ + " w-full"} inputMode="decimal" value={долг} onChange={(e) => setДолг(e.target.value)} />
        </label>
        <label>
          <div className={подпись}>Заметка к долгу</div>
          <input className={ПОЛЕ + " w-full"} value={заметка} onChange={(e) => setЗаметка(e.target.value)} />
        </label>
      </div>
      {ошибка && (
        <p role="alert" className="text-sm text-loss">
          {ошибка}
        </p>
      )}
      <button
        disabled={занято}
        onClick={() => void сохранить()}
        className="rounded-xl bg-gold px-5 py-2 text-sm font-semibold text-black disabled:opacity-50"
      >
        {занято ? "Сохранение…" : "Сохранить"}
      </button>
    </div>
  );
}

// ── Общая загрузка и шапка ────────────────────────────────────────────────

function useФинансы(месяц: string) {
  const [данные, setДанные] = useState<Данные | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [грузим, setГрузим] = useState(false);

  const загрузить = useCallback(async () => {
    setГрузим(true);
    setОшибка(null);
    try {
      const r = await fetch(`/api/finance-analysis?month=${месяц}`);
      if (!r.ok) {
        const тело = await r.json().catch(() => ({}));
        setОшибка(тело.detail || "Страница не построена");
        return;
      }
      setДанные(await r.json());
    } catch {
      setОшибка("Сервер не отвечает");
    } finally {
      setГрузим(false);
    }
  }, [месяц]);

  useEffect(() => {
    setДанные(null);
    void загрузить();
  }, [загрузить]);

  return { данные, ошибка, грузим, загрузить };
}

function Шапка({
  заголовок, подзаголовок, месяц, setМесяц, грузим, загрузить, ошибка, данные,
}: {
  заголовок: string;
  подзаголовок: string;
  месяц: string;
  setМесяц: (m: string) => void;
  грузим: boolean;
  загрузить: () => void;
  ошибка: string | null;
  данные: Данные | null;
}) {
  return (
    <>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1>{заголовок}</h1>
          <p className="mt-1 text-sm text-muted-light dark:text-muted">{подзаголовок}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-muted-light dark:text-muted">
            Месяц{" "}
            <input
              type="month"
              value={месяц}
              max={текущийМесяц()}
              onChange={(e) => e.target.value && setМесяц(e.target.value)}
              className={ПОЛЕ + " ml-1"}
            />
          </label>
          <button
            disabled={грузим}
            onClick={() => void загрузить()}
            className="inline-flex items-center gap-2 rounded-xl border border-milk-line dark:border-line px-4 py-2 text-sm disabled:opacity-50"
          >
            <RefreshCw size={14} className={грузим ? "animate-spin" : ""} />
            {грузим ? "Обновление…" : "Обновить"}
          </button>
        </div>
      </header>
      {ошибка && (
        <p role="alert" className="rounded-xl bg-loss/10 p-4 text-loss">
          {ошибка}
        </p>
      )}
      {данные?.warnings.map((w) => (
        <p key={w} role="status" className="flex items-start gap-2 rounded-xl bg-caution/10 p-4 text-sm text-caution">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          {w}
        </p>
      ))}
    </>
  );
}

// ── Расходы: пончик по статьям и стрелка динамики ─────────────────────────

/** Оттенки одной латуни — от насыщенной к бледной: статьи упорядочены по сумме. */
const ЛАТУНЬ = {
  тёмная: ["#c9a15a", "#a8843f", "#d9bd85", "#8a6a2f", "#e6d3a8", "#6f5626", "#b5a07a", "#56452a"],
  светлая: ["#9a6a36", "#7c5228", "#b98c55", "#5f3f1f", "#cfae7c", "#8f7650", "#ddc59f", "#4a3218"],
};

function Пончик({ статьи, тёмная, цвета }: { статьи: Статья[]; тёмная: boolean; цвета: ReturnType<typeof палитраГрафика> }) {
  const МАКС = 7;
  const данные = статьи.slice(0, МАКС).map((a) => ({ name: a.title, value: a.total, share: a.share_pct }));
  const хвост = статьи.slice(МАКС);
  if (хвост.length) {
    const сумма = хвост.reduce((s, a) => s + a.total, 0);
    данные.push({ name: `Остальное (${хвост.length})`, value: сумма, share: хвост.reduce((s, a) => s + (a.share_pct ?? 0), 0) });
  }
  const тона = тёмная ? ЛАТУНЬ.тёмная : ЛАТУНЬ.светлая;
  return (
    <div className="mt-3 flex items-center gap-4">
      <div className="h-44 w-44 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={данные} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="100%" paddingAngle={1.5} stroke="none">
              {данные.map((_, i) => <Cell key={i} fill={тона[i % тона.length]} />)}
            </Pie>
            <Tooltip
              contentStyle={{ background: цвета.подсказкаФон, border: `1px solid ${цвета.подсказкаРамка}`, borderRadius: 12, fontSize: 12 }}
              formatter={(v, n) => [руб(Number(v)), String(n)]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="min-w-0 flex-1 space-y-1 text-xs">
        {данные.map((d, i) => (
          <li key={d.name} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: тона[i % тона.length] }} />
            <span className="truncate text-ink-soft dark:text-cream">{d.name}</span>
            <span className="ml-auto tabular-nums text-muted-light dark:text-muted">{проц(d.share ?? null)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Динамика({ пп, было }: { пп: Num; было: Num }) {
  if (пп == null) return <span className="text-muted-light dark:text-muted">{НЕТ}</span>;
  const подсказка = `было ${проц(было)}, изменение ${пп > 0 ? "+" : ""}${пп.toLocaleString("ru-RU")} п.п.`;
  if (Math.abs(пп) <= 0.5)
    return <span title={подсказка} className="inline-flex items-center gap-1 text-caution"><ArrowRight size={14} /> {пп > 0 ? "+" : ""}{пп.toLocaleString("ru-RU")} п.п.</span>;
  return пп > 0 ? (
    <span title={подсказка} className="inline-flex items-center gap-1 text-loss"><ArrowUp size={14} /> +{пп.toLocaleString("ru-RU")} п.п.</span>
  ) : (
    <span title={подсказка} className="inline-flex items-center gap-1 text-profit"><ArrowDown size={14} /> {пп.toLocaleString("ru-RU")} п.п.</span>
  );
}

// ── Финансы: деньги сейчас и куда уходят ──────────────────────────────────

export default function FinancePage() {
  const тёмная = useDark();
  const цвета = палитраГрафика(тёмная);
  const [месяц, setМесяц] = useState(текущийМесяц());
  const { данные, ошибка, грузим, загрузить } = useФинансы(месяц);
  const [форма, setФорма] = useState(false);

  const б = данные?.balances;
  const расходы = данные?.expenses ?? null;

  return (
    <section className="space-y-6">
      <Шапка заголовок="Финансы" подзаголовок="Деньги сейчас и куда они уходят · Москва"
        {...{ месяц, setМесяц, грузим, загрузить, ошибка, данные }} />

      {данные && (
        <>
          {/* ── Деньги сейчас ── */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Heading>Деньги сейчас</Heading>
              {!форма && (
                <button
                  onClick={() => setФорма(true)}
                  className="inline-flex items-center gap-1 text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
                >
                  <Pencil size={12} /> Остатки и долг
                </button>
              )}
            </div>
            {форма && (
              <BalancesForm
                начало={{
                  cash: б?.cash?.baseline ?? null,
                  cashDate: б?.cash?.as_of ?? null,
                  rs: б?.rs?.baseline ?? null,
                  rsDate: б?.rs?.as_of ?? null,
                  debt: данные.debt.amount,
                  note: данные.debt.note,
                }}
                onCancel={() => setФорма(false)}
                onDone={() => {
                  setФорма(false);
                  void загрузить();
                }}
              />
            )}
            {!б?.entered ? (
              <p className={КАРТОЧКА + " text-sm text-muted-light dark:text-muted"}>
                Остатки ещё не внесены. Нажмите «Остатки и долг» и укажите, сколько денег в кассе и на
                счёте на конец какого-нибудь дня: дальше Пульт считает остатки сам.
              </p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Tile
                  название="В кассе (расчётно)"
                  значение={руб(б.cash?.calc)}
                  пояснение={`от ${датаКратко(б.cash!.as_of)}: ${руб(б.cash!.baseline)}, учтено до ${датаКратко(б.upto)}`}
                />
                <Tile
                  название="На РС (по YCLIENTS)"
                  значение={руб(б.rs?.calc_yclients)}
                  пояснение={`от ${датаКратко(б.rs!.as_of)}: ${руб(б.rs!.baseline)}`}
                />
                <Tile
                  название="На РС (с поправкой на банк)"
                  значение={руб(б.rs?.calc_bank)}
                  пояснение={
                    б.rs?.calc_bank != null && б.rs.calc_yclients != null
                      ? `разница с YCLIENTS ${руб(б.rs.calc_bank - б.rs.calc_yclients)}, дней с отчётом банка: ${б.rs.bank_days}`
                      : "нужен отчёт банка за дни после внесённых остатков"
                  }
                />
                <Tile
                  название="Долг по другому счёту"
                  значение={руб(данные.debt.amount)}
                  пояснение={данные.debt.note ?? undefined}
                  тон={данные.debt.amount ? "минус" : undefined}
                />
              </div>
            )}
            {б?.missing_closure_days && б.missing_closure_days.length > 0 && (
              <p className="text-xs text-caution">
                Нет закрытой смены: {б.missing_closure_days.map(датаКратко).join(", ")}. Эти дни в
                расчёте остатков не учтены.
              </p>
            )}
          </div>

          {/* ── Расходы ── */}
          {расходы && (
            <div className="space-y-3">
              <Heading>Куда уходят деньги</Heading>
              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
                <div className={КАРТОЧКА + " flex flex-col"}>
                  <div className="text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">Расходы за месяц</div>
                  <div className="mt-1 text-xl font-semibold text-ink-soft dark:text-cream">{руб(расходы.total)}</div>
                  {расходы.expenses_pct_of_income != null && (
                    <div className="mt-1 text-xs text-muted-light dark:text-muted">
                      {проц(расходы.expenses_pct_of_income)} от дохода ({руб(расходы.income ?? null)})
                    </div>
                  )}
                  {расходы.articles.length === 0 ? (
                    <p className="mt-4 text-sm text-muted-light dark:text-muted">За этот месяц расходов нет.</p>
                  ) : (
                    <Пончик статьи={расходы.articles} тёмная={тёмная} цвета={цвета} />
                  )}
                </div>

                <div className={КАРТОЧКА}>
                  <div className="mb-2 text-sm font-semibold text-ink-soft dark:text-cream">По группам</div>
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-muted-light dark:text-muted">
                      <tr>
                        <th className="py-1 font-normal">Группа</th>
                        <th className="py-1 text-right font-normal">Сумма</th>
                        <th className="py-1 pl-3 text-right font-normal">Доля дохода</th>
                        <th className="py-1 pl-3 text-right font-normal">К прошлому месяцу</th>
                      </tr>
                    </thead>
                    <tbody>
                      {расходы.groups.map((g) => (
                        <tr key={g.name} className="border-t border-milk-line dark:border-line">
                          <td className="py-1.5">{g.name}</td>
                          <td className="py-1.5 text-right tabular-nums">{руб(g.total)}</td>
                          <td className="py-1.5 pl-3 text-right tabular-nums">{проц(g.pct_of_income ?? null)}</td>
                          <td className="py-1.5 pl-3 text-right"><Динамика пп={g.delta_pp ?? null} было={g.prev_pct_of_income ?? null} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-3 text-xs text-muted-light dark:text-muted">
                    Сравниваем не рубли, а долю от дохода: аренда та же, а доход упал — доля выросла.
                    Стрелка: ↑ красная — доля выросла, ↓ зелёная — сократилась, → жёлтая — в пределах ±0,5 п.п.
                  </p>
                </div>
              </div>

              {расходы.watch.length > 0 && (
                <div className="rounded-2xl border border-caution/40 bg-caution/10 p-4">
                  <div className="mb-1 text-sm font-semibold text-caution">Где стоит посмотреть, что сократить</div>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-ink-soft dark:text-cream">
                    {расходы.watch.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

// ── Контроль финансов: поступления и сверка с банком (только Владельцу) ────

const ДНИ = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

/** Дни месяца, разбитые на недели с понедельника. */
function недели(дни: День[]): День[][] {
  const out: День[][] = [];
  for (const д of дни) {
    const пн = new Date(д.date + "T12:00:00").getDay() === 1;
    if (!out.length || пн) out.push([]);
    out[out.length - 1].push(д);
  }
  return out;
}

function сдвигМесяца(ym: string, на: number): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + на, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Два близких тона на столбец: тёмный низ (эквайринг) и светлее верх
 *  (наличка). Золото — YCLIENTS, зелень — факт. Без резких скачков цвета. */
const СВЕРКА = {
  тёмная: { айкЭкв: "#a8843f", айкНал: "#dcc08a", банк: "#4f8f63", касса: "#a3cf8c" },
  светлая: { айкЭкв: "#8c6a2e", айкНал: "#cfae6c", банк: "#3f7a50", касса: "#8fbf78" },
};

function причины(д: День): string[] {
  const out: string[] = [];
  if (д.status === "no_bank") out.push("нет отчёта банка за этот день");
  if (д.status === "no_shift") out.push("смена не закрыта, есть только отчёт банка");
  if (д.diff != null && Math.abs(д.diff) > 1)
    out.push(`банк получил ${д.diff < 0 ? "меньше" : "больше"} на ${руб(Math.abs(д.diff))}`);
  if (д.cash_diff != null && Math.abs(д.cash_diff) > 1)
    out.push(`наличка в кассе ${д.cash_diff < 0 ? "меньше" : "больше"} на ${руб(Math.abs(д.cash_diff))}`);
  return out;
}

function ПодсказкаСверки({
  active, payload, label, фон, рамка,
}: {
  active?: boolean;
  payload?: { payload: { айкЭкв: Num; айкНал: Num; банк: Num; кассаНал: Num } }[];
  label?: string;
  фон: string;
  рамка: string;
}) {
  if (!active || !payload?.length) return null;
  const р = payload[0].payload;
  const сумма = (a: Num, b: Num) => (a == null && b == null ? null : (a ?? 0) + (b ?? 0));
  const айк = сумма(р.айкЭкв, р.айкНал);
  const факт = сумма(р.банк, р.кассаНал);
  const разница = айк != null && факт != null ? факт - айк : null;
  const строка = (подпись: string, v: Num, жирно = false) => (
    <div className={`flex justify-between gap-6 ${жирно ? "font-semibold" : ""}`}>
      <span>{подпись}</span>
      <span className="tabular-nums">{руб(v)}</span>
    </div>
  );
  return (
    <div className="rounded-xl px-3 py-2 text-xs text-ink-soft dark:text-cream shadow-lg" style={{ background: фон, border: `1px solid ${рамка}` }}>
      <div className="mb-1 font-semibold">{label}</div>
      <div className="text-muted-light dark:text-muted">YCLIENTS</div>
      {строка("эквайринг", р.айкЭкв)}
      {строка("наличка", р.айкНал)}
      {строка("итого", айк, true)}
      <div className="mt-1 text-muted-light dark:text-muted">Факт</div>
      {строка("банк", р.банк)}
      {строка("наличка в кассе", р.кассаНал)}
      {строка("итого", факт, true)}
      {разница != null && (
        <div className={`mt-1 flex justify-between gap-6 font-semibold ${Math.abs(разница) <= 1 ? "text-profit" : "text-loss"}`}>
          <span>разница</span>
          <span className="tabular-nums">{Math.abs(разница) <= 1 ? "сходится" : руб(разница)}</span>
        </div>
      )}
    </div>
  );
}

/** Недельная сверка: YCLIENTS против факта (банк + наличка в кассе).
 *  Клик по дню — загрузить отчёт банка именно за этот день. */
export function СверкаПоДням({ компактно = false }: { компактно?: boolean }) {
  const тёмная = useDark();
  const цвета = палитраГрафика(тёмная);
  const сверка = тёмная ? СВЕРКА.тёмная : СВЕРКА.светлая;
  const [месяц, setМесяц] = useState(текущийМесяц());
  const { данные, ошибка, загрузить } = useФинансы(месяц);
  // Номер недели в месяце; -1 — последняя (после перехода на прошлый месяц).
  const [неделя, setНеделя] = useState(-1);
  const [деньЗагрузки, setДеньЗагрузки] = useState<string | null>(null);
  const [шлём, setШлём] = useState(false);
  const [итог, setИтог] = useState<{ ok: boolean; текст: string } | null>(null);
  const файлРеф = useRef<HTMLInputElement>(null);

  const отправить = async (файл: File, день: string | null) => {
    setШлём(true);
    setИтог(null);
    try {
      const r = await fetch(`/api/finance-analysis/acquiring${день ? `?day=${день}` : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(файл.name) },
        body: файл,
      });
      const тело = await r.json().catch(() => ({}));
      if (!r.ok) {
        setИтог({ ok: false, текст: тело.detail || "Файл не принят" });
        return;
      }
      setИтог({
        ok: true,
        текст: `Загружено: ${тело.days} дн. (${датаКратко(тело.date_from)}–${датаКратко(тело.date_to)}), оборот ${руб(тело.amount)}.`,
      });
      await загрузить();
    } catch {
      setИтог({ ok: false, текст: "Сервер не отвечает" });
    } finally {
      setШлём(false);
      setДеньЗагрузки(null);
    }
  };
  const выбратьФайл = (день: string | null) => {
    setДеньЗагрузки(день);
    файлРеф.current?.click();
  };

  const списокНедель = недели(данные?.days ?? []);
  const номер = неделя < 0 || неделя >= списокНедель.length ? списокНедель.length - 1 : неделя;
  const дниНедели = списокНедель[номер] ?? [];
  // Всегда семь мест, Пн–Вс: у неполной недели столбцы не раздуваются.
  const поДате = new Map(дниНедели.map((д) => [д.date, д]));
  const пн = дниНедели.length ? new Date(дниНедели[0].date + "T12:00:00") : null;
  if (пн) пн.setDate(пн.getDate() - ((пн.getDay() + 6) % 7));
  const график = пн
    ? Array.from({ length: 7 }, (_, i) => {
        const d = new Date(пн);
        d.setDate(пн.getDate() + i);
        const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        const д = поДате.get(iso);
        return {
          iso,
          день: `${ДНИ[d.getDay()]} ${датаКратко(iso)}`,
          айкЭкв: д?.non_cash ?? null,
          айкНал: д?.cash ?? null,
          банк: д?.bank ?? null,
          кассаНал: д?.cash_fact ?? null,
        };
      })
    : [];
  const можноВперёд = номер < списокНедель.length - 1 || месяц < текущийМесяц();
  const назад = () => {
    if (номер > 0) setНеделя(номер - 1);
    else { setНеделя(-1); setМесяц(сдвигМесяца(месяц, -1)); }
  };
  const вперёд = () => {
    if (номер < списокНедель.length - 1) setНеделя(номер + 1);
    else if (месяц < текущийМесяц()) { setНеделя(0); setМесяц(сдвигМесяца(месяц, 1)); }
  };
  const расходятся = (данные?.days ?? []).filter((д) => причины(д).length > 0);

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <input
        ref={файлРеф}
        type="file"
        accept=".xlsx,.xlsm,.csv,.txt"
        className="hidden"
        onChange={(e) => {
          const ф = e.target.files?.[0];
          e.target.value = "";
          if (ф) void отправить(ф, деньЗагрузки);
        }}
      />
      <div className="flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-light dark:text-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm" style={{ background: сверка.айкЭкв }} />
            <span className="-ml-1 h-3 w-3 rounded-sm" style={{ background: сверка.айкНал }} />
            YCLIENTS: эквайринг + наличка
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm" style={{ background: сверка.банк }} />
            <span className="-ml-1 h-3 w-3 rounded-sm" style={{ background: сверка.касса }} />
            Факт: банк + наличка в кассе
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => выбратьФайл(null)}
            disabled={шлём}
            className="inline-flex items-center gap-1.5 rounded-lg border border-milk-line dark:border-line px-3 py-1 text-xs hover:border-bronze dark:hover:border-gold disabled:opacity-50"
          >
            <Upload size={12} /> {шлём ? "Загрузка…" : "Отчёт банка"}
          </button>
          <button onClick={назад} aria-label="Предыдущая неделя"
            className="rounded-lg border border-milk-line dark:border-line p-1 hover:border-bronze dark:hover:border-gold">
            <ChevronLeft size={16} />
          </button>
          <span className="min-w-[8.5rem] text-center text-xs text-muted-light dark:text-muted">
            {дниНедели.length
              ? `${датаКратко(дниНедели[0].date)} – ${датаКратко(дниНедели[дниНедели.length - 1].date)}`
              : "нет дней"}
          </span>
          <button onClick={вперёд} disabled={!можноВперёд} aria-label="Следующая неделя"
            className="rounded-lg border border-milk-line dark:border-line p-1 hover:border-bronze dark:hover:border-gold disabled:opacity-30">
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
      {ошибка && <p role="alert" className="text-sm text-loss">{ошибка}</p>}
      {итог && <p role={итог.ok ? "status" : "alert"} className={`text-xs ${итог.ok ? "text-profit" : "text-loss"}`}>{итог.текст}</p>}
      <div className={`min-h-[180px] flex-1 ${компактно ? "" : "h-[260px]"}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={график}
            margin={{ top: 10, right: 8, left: 8, bottom: 0 }}
            barGap={0}
            barCategoryGap="22%"
            onClick={(s: { activeLabel?: string | number } | null) => {
              const стр = график.find((g) => g.день === s?.activeLabel);
              if (стр) выбратьФайл(стр.iso);
            }}
            style={{ cursor: "pointer" }}
          >
            <CartesianGrid stroke={цвета.сетка} vertical={false} />
            <XAxis dataKey="день" tick={{ fontSize: 11, fill: цвета.ось }} tickLine={false} axisLine={false} />
            <YAxis
              tick={{ fontSize: 11, fill: цвета.ось }}
              tickLine={false}
              axisLine={false}
              width={48}
              tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}к` : String(v))}
            />
            <Tooltip cursor={{ fill: тёмная ? "#ffffff0d" : "#0000000a" }} content={<ПодсказкаСверки фон={цвета.подсказкаФон} рамка={цвета.подсказкаРамка} />} />
            <Bar dataKey="айкЭкв" stackId="айк" fill={сверка.айкЭкв} />
            <Bar dataKey="айкНал" stackId="айк" fill={сверка.айкНал} radius={[3, 3, 0, 0]} />
            <Bar dataKey="банк" stackId="факт" fill={сверка.банк} />
            <Bar dataKey="кассаНал" stackId="факт" fill={сверка.касса} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="shrink-0 text-[11px] text-muted-light dark:text-muted">
        Наведите на день — покажу числа. Щёлкните по дню — загрузите отчёт банка за этот день.
        {расходятся.length > 0 && ` Не сошлось за месяц: ${расходятся.map((д) => датаКратко(д.date)).join(", ")}.`}
      </p>
    </div>
  );
}
