import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from "recharts";
import { RefreshCw, Scale } from "lucide-react";
import { useDark, палитраГрафика } from "./тема";
import { СверкаПоДням } from "./FinancePage";

// ── Ответ /api/finance-analysis/overview ──────────────────────────────────

type Num = number | null;

interface Обзор {
  today: string;
  month: string;
  day: number;
  days_in_month: number;
  elapsed_pct: number;
  income: { value: Num; plan: Num; pct_of_plan: Num; ok: boolean | null };
  expenses: {
    value: Num; budget: Num; pct_of_budget: Num; ok: boolean | null;
    groups: { name: string; total: Num; share_pct: Num }[];
  };
  profit: { value: Num; plan: Num; pace: Num; margin_pct: Num; ok: boolean | null };
  history: { month: string; income: Num; expenses: Num; profit: Num; partial: boolean }[];
  recon: { diff_total: Num; compared_days: number; mismatch_days: number; days_without_bank: number };
}

type Режим = "income" | "expenses" | "profit" | "recon";

const МЕСЯЦЫ = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const МЕСЯЦЫ_ИМ = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const руб = (v: Num | undefined) =>
  v == null ? "—" : `${Math.round(v).toLocaleString("ru-RU")} ₽`;
const кратко = (v: number) =>
  Math.abs(v) >= 1_000_000 ? `${(v / 1_000_000).toFixed(1).replace(".", ",")} млн` : `${Math.round(v / 1000)}к`;

// ── Спидометр денег ───────────────────────────────────────────────────────

/** Полукруг от min до max. Заливка — от «нуля» до значения; точка — план,
 *  тонкая засечка — где значение должно быть сегодня по темпу месяца.
 *  zone — участок шкалы после плана (перевыполнение или перерасход). */
function Спидометр({
  min, max, value, plan, pace, zoneColor, fill, track, tick, text, textColor, caption,
}: {
  min: number; max: number; value: number; plan: number | null; pace: number | null;
  zoneColor: string; fill: string; track: string; tick: string;
  text: string; textColor: string; caption: string;
}) {
  const [shown, setShown] = useState(min < 0 ? 0 : min);
  useEffect(() => { const t = setTimeout(() => setShown(value), 60); return () => clearTimeout(t); }, [value]);
  const R = 118, C = 150, W = 14;
  const f = (v: number) => (Math.max(min, Math.min(max, v)) - min) / (max - min || 1); // 0..1
  const pt = (k: number, r = R) => {
    const a = Math.PI * (1 - k);
    return [C + r * Math.cos(a), C - r * Math.sin(a)];
  };
  const arc = (k1: number, k2: number, r = R) => {
    const [x1, y1] = pt(k1, r), [x2, y2] = pt(k2, r);
    return `M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}`;
  };
  const ноль = f(Math.max(0, min));
  const к = f(shown);
  const [a, b] = к >= ноль ? [ноль, к] : [к, ноль];
  return (
    <svg viewBox="0 0 300 200" className="w-full max-h-[190px]" role="img" aria-label={`${caption}: ${text}`}>
      <path d={arc(0, 1)} fill="none" stroke={track} strokeWidth={W} strokeLinecap="round" />
      {plan != null && plan < max && (
        <path d={arc(f(plan), 1)} fill="none" stroke={zoneColor} strokeOpacity={0.28} strokeWidth={W} />
      )}
      {b - a > 0.002 && (
        <path d={arc(a, b)} fill="none" stroke={fill} strokeWidth={W} strokeLinecap="round"
          style={{ transition: "d 1s cubic-bezier(.2,.9,.3,1)" }} />
      )}
      {min < 0 && (() => {
        const [x1, y1] = pt(ноль, R - W), [x2, y2] = pt(ноль, R + W);
        return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={tick} strokeWidth={1.5} />;
      })()}
      {pace != null && (() => {
        const [x1, y1] = pt(f(pace), R - W / 2 - 5), [x2, y2] = pt(f(pace), R + W / 2 + 5);
        return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={tick} strokeWidth={1.2} strokeDasharray="2 2" />;
      })()}
      {plan != null && (() => {
        const [x, y] = pt(f(plan));
        const [tx, ty] = pt(f(plan), R + 24);
        return (
          <g>
            <circle cx={x} cy={y} r={6.5} fill={track} stroke={tick} strokeWidth={2} />
            <text x={tx} y={ty + 3} textAnchor="middle" fontSize={9.5} fill={tick}>план</text>
          </g>
        );
      })()}
      <text x={C} y={C - 6} textAnchor="middle" fontSize={27} fontWeight={600} fill={textColor}
        style={{ fontVariantNumeric: "tabular-nums" }}>{text}</text>
      <text x={C} y={C + 14} textAnchor="middle" fontSize={10.5} fill={tick}>{caption}</text>
      <text x={pt(0)[0]} y={C + 22} textAnchor="middle" fontSize={9.5} fill={tick}>{min < 0 ? `−${кратко(-min)}` : "0"}</text>
      <text x={pt(1)[0]} y={C + 22} textAnchor="middle" fontSize={9.5} fill={tick}>{кратко(max)}</text>
    </svg>
  );
}

function Блок({
  заголовок, активен, onClick, children, подпись,
}: { заголовок: string; активен: boolean; onClick: () => void; children: React.ReactNode; подпись: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`text-left bg-milk-card dark:bg-panel/80 border rounded-2xl px-5 pt-4 pb-3 flex flex-col min-w-0 transition-all ${
        активен
          ? "border-bronze dark:border-gold shadow-[0_0_0_1px_var(--color-bronze)] dark:shadow-[0_0_0_1px_var(--color-gold)]"
          : "border-milk-line dark:border-line hover:border-bronze/60 dark:hover:border-gold/60"
      }`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">{заголовок}</h3>
        {активен && <span className="text-[10px] uppercase tracking-wider text-bronze dark:text-gold">на графике</span>}
      </div>
      <div className="flex-1 flex items-center">{children}</div>
      <div className="text-xs text-muted-light dark:text-muted min-h-[2.5em]">{подпись}</div>
    </button>
  );
}

// ── Страница ──────────────────────────────────────────────────────────────

export default function OwnerPage() {
  const тёмная = useDark();
  const цвета = палитраГрафика(тёмная);
  const [д, setД] = useState<Обзор | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [грузим, setГрузим] = useState(false);
  const [режим, setРежим] = useState<Режим>("income");

  const загрузить = useCallback(async () => {
    setГрузим(true);
    setОшибка(null);
    try {
      const r = await fetch("/api/finance-analysis/overview");
      const тело = await r.json().catch(() => ({}));
      if (!r.ok) {
        setОшибка(тело.detail || "Страница не построена");
        return;
      }
      setД(тело);
    } catch {
      setОшибка("Сервер не отвечает");
    } finally {
      setГрузим(false);
    }
  }, []);
  useEffect(() => { void загрузить(); }, [загрузить]);

  const цвет = (ok: boolean | null) => (ok == null ? цвета.сейчас : ok ? цвета.прибыль : цвета.убыток);
  const текущий = д ? Number(д.month.slice(5)) - 1 : 0;

  // Шкалы: план не в конце — после него 20% на перевыполнение/перерасход.
  const шкалаДохода = д ? Math.max((д.income.plan ?? 0) * 1.2, (д.income.value ?? 0) * 1.1, 1) : 1;
  const шкалаРасхода = д ? Math.max((д.expenses.budget ?? 0) * 1.2, (д.expenses.value ?? 0) * 1.1, 1) : 1;
  const размахПрибыли = д
    ? Math.max(Math.abs(д.profit.value ?? 0) * 1.15, (д.profit.plan ?? 0) * 1.2, 1)
    : 1;

  const история = (д?.history ?? []).map((h) => ({
    месяц: МЕСЯЦЫ[Number(h.month.slice(5)) - 1] + (h.partial ? " ·" : ""),
    значение: режим === "income" ? h.income : режим === "expenses" ? h.expenses : h.profit,
    partial: h.partial,
  }));
  const цветСерии = режим === "income" ? цвета.золото : режим === "expenses" ? цвета.внимание : цвета.прибыль;

  const r = д?.recon;
  const сверкаЕсть = r && r.compared_days > 0;
  const сошлось = сверкаЕсть && Math.abs(r!.diff_total ?? 0) <= 1;

  return (
    <div className="animate-in lg:h-[calc(100vh-4rem)] flex flex-col gap-3 min-h-0">
      <header className="flex flex-wrap items-start justify-between gap-4 shrink-0">
        <div>
          <h1 className="mb-1">Контроль финансов</h1>
          <p className="text-sm text-muted-light dark:text-muted">
            {д
              ? `${МЕСЯЦЫ_ИМ[текущий]}: прошло ${д.day} из ${д.days_in_month} дн. — ${Math.round(д.elapsed_pct)}% месяца · видно только Владельцу`
              : "Как идут дела у салона · видно только Владельцу"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setРежим("recon")}
            className={`flex items-center gap-3 rounded-2xl border px-4 py-2 text-left transition-all bg-milk-card dark:bg-panel/80 ${
              режим === "recon" ? "border-bronze dark:border-gold" : "border-milk-line dark:border-line hover:border-bronze/60 dark:hover:border-gold/60"
            }`}
          >
            <Scale size={18} className="text-muted-light dark:text-muted" />
            <span>
              <span className="block text-[11px] uppercase tracking-widest text-muted-light dark:text-muted">Сверка с банком</span>
              <span className={`block text-base font-semibold ${!сверкаЕсть ? "" : сошлось ? "text-profit" : "text-loss"}`}>
                {!сверкаЕсть ? "нет данных" : сошлось ? "сходится" : руб(r!.diff_total)}
              </span>
            </span>
          </button>
          <button
            disabled={грузим}
            onClick={() => void загрузить()}
            className="inline-flex items-center gap-2 rounded-xl border border-milk-line dark:border-line px-3 py-2 text-sm disabled:opacity-50"
            aria-label="Обновить"
          >
            <RefreshCw size={14} className={грузим ? "animate-spin" : ""} />
          </button>
        </div>
      </header>

      {ошибка && <p role="alert" className="rounded-xl bg-loss/10 p-3 text-sm text-loss shrink-0">{ошибка}</p>}

      {д && (
        <>
          <div className="grid gap-3 lg:grid-cols-3 shrink-0">
            <Блок
              заголовок="Доход"
              активен={режим === "income"}
              onClick={() => setРежим("income")}
              подпись={
                д.income.plan != null
                  ? <>План {руб(д.income.plan)} · выполнено <b className="text-ink-soft dark:text-cream">{д.income.pct_of_plan}%</b> при {Math.round(д.elapsed_pct)}% месяца</>
                  : "План не задан: задайте план прибыли в «План-факте»"
              }
            >
              <Спидометр
                min={0} max={шкалаДохода} value={д.income.value ?? 0} plan={д.income.plan}
                pace={д.income.plan != null ? (д.income.plan * д.elapsed_pct) / 100 : null}
                zoneColor={цвета.прибыль} fill={цвет(д.income.ok)} track={цвета.сетка} tick={цвета.ось}
                text={руб(д.income.value)} textColor={цвет(д.income.ok)} caption="заработано с 1-го числа"
              />
            </Блок>
            <Блок
              заголовок="Расходы"
              активен={режим === "expenses"}
              onClick={() => setРежим("expenses")}
              подпись={
                д.expenses.budget != null
                  ? <>Бюджет {руб(д.expenses.budget)} (среднее за 3 мес.) · потрачено <b className="text-ink-soft dark:text-cream">{д.expenses.pct_of_budget}%</b></>
                  : "Бюджета нет: мало истории расходов"
              }
            >
              <Спидометр
                min={0} max={шкалаРасхода} value={д.expenses.value ?? 0} plan={д.expenses.budget}
                pace={д.expenses.budget != null ? (д.expenses.budget * д.elapsed_pct) / 100 : null}
                zoneColor={цвета.убыток} fill={цвет(д.expenses.ok)} track={цвета.сетка} tick={цвета.ось}
                text={руб(д.expenses.value)} textColor={цвет(д.expenses.ok)} caption="потрачено с 1-го числа"
              />
            </Блок>
            <Блок
              заголовок="Прибыль"
              активен={режим === "profit"}
              onClick={() => setРежим("profit")}
              подпись={
                д.profit.plan != null
                  ? <>План {руб(д.profit.plan)} · сегодня по темпу нужно {руб(д.profit.pace)}{д.profit.margin_pct != null && <> · рентабельность {д.profit.margin_pct}%</>}</>
                  : "План прибыли не задан"
              }
            >
              <Спидометр
                min={-размахПрибыли} max={размахПрибыли} value={д.profit.value ?? 0} plan={д.profit.plan}
                pace={д.profit.pace}
                zoneColor={цвета.прибыль} fill={цвет(д.profit.ok)} track={цвета.сетка} tick={цвета.ось}
                text={руб(д.profit.value)} textColor={цвет(д.profit.ok)} caption="доход минус расходы"
              />
            </Блок>
          </div>

          <div className="bg-milk-card dark:bg-panel/80 border border-milk-line dark:border-line rounded-2xl p-4 flex flex-col flex-1 min-h-[240px]">
            <h3 className="mb-2 shrink-0 text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              {режим === "income" && "Доход за полгода"}
              {режим === "expenses" && "Расходы за полгода"}
              {режим === "profit" && "Прибыль за полгода"}
              {режим === "recon" && "Сверка с банком по дням"}
            </h3>
            {режим === "recon" ? (
              <div className="flex-1 min-h-0"><СверкаПоДням компактно /></div>
            ) : (
              <div className="flex flex-1 min-h-0 gap-6">
                <div className="flex-1 min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={история} margin={{ top: 18, right: 8, left: 8, bottom: 0 }} barCategoryGap="28%">
                      <CartesianGrid stroke={цвета.сетка} vertical={false} />
                      <XAxis dataKey="месяц" tick={{ fontSize: 11, fill: цвета.ось }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: цвета.ось }} tickLine={false} axisLine={false} width={52}
                        tickFormatter={(v: number) => кратко(v)} />
                      <ReferenceLine y={0} stroke={цвета.ось} />
                      <Tooltip
                        cursor={{ fill: тёмная ? "#ffffff0d" : "#0000000a" }}
                        contentStyle={{ background: цвета.подсказкаФон, border: `1px solid ${цвета.подсказкаРамка}`, borderRadius: 12, fontSize: 12 }}
                        formatter={(v) => [руб(Number(v)), режим === "income" ? "Доход" : режим === "expenses" ? "Расходы" : "Прибыль"]}
                        labelFormatter={(l) => (String(l).endsWith("·") ? `${String(l).slice(0, -2)} — месяц ещё идёт` : String(l))}
                      />
                      <Bar dataKey="значение" radius={[4, 4, 4, 4]} maxBarSize={56}
                        label={{ position: "top", fontSize: 10, fill: цвета.ось, formatter: (v: unknown) => (v == null ? "" : кратко(Number(v))) }}>
                        {история.map((h, i) => (
                          <Cell key={i}
                            fill={режим === "profit" ? ((h.значение ?? 0) >= 0 ? цвета.прибыль : цвета.убыток) : цветСерии}
                            fillOpacity={h.partial ? 0.55 : 1} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                {режим === "expenses" && (
                  <div className="w-72 shrink-0 overflow-y-auto">
                    <div className="mb-2 text-xs text-muted-light dark:text-muted">По группам за этот месяц</div>
                    {д.expenses.groups.length === 0 && <p className="text-sm text-muted-light dark:text-muted">Расходов пока нет.</p>}
                    <ul className="space-y-2.5">
                      {д.expenses.groups.map((g) => (
                        <li key={g.name} className="text-sm">
                          <div className="flex justify-between gap-3">
                            <span className="truncate">{g.name}</span>
                            <span className="tabular-nums">{руб(g.total)}</span>
                          </div>
                          <div className="mt-1 h-1.5 rounded-full bg-milk-deep dark:bg-ink/60">
                            <div className="h-1.5 rounded-full" style={{ width: `${g.share_pct ?? 0}%`, background: цвета.внимание }} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {режим !== "recon" && (
              <p className="mt-1 shrink-0 text-[11px] text-muted-light dark:text-muted">
                Текущий месяц — бледнее: он ещё идёт. Доход и расходы — реальные деньги по кассе YCLIENTS; прибыль = доход − расходы.
              </p>
            )}
          </div>
        </>
      )}
      {!д && !ошибка && <p className="text-sm text-muted-light dark:text-muted">Считаю…</p>}
    </div>
  );
}
