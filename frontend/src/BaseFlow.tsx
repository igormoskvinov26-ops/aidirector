import { useEffect, useState } from "react";
import { useDark, палитраГрафика, палитраПульса } from "./тема";

interface Day {
  date: string;
  new: number;
  returned: number;
  lost: number;
  pulse: number;
  total: number;
}
interface Flow {
  start: string | null;
  today: string;
  days: Day[];
  total?: number;
  history_from?: string | null;
}

const CARD = "rounded-2xl border border-line-light dark:border-line bg-surface-light dark:bg-surface p-4";
const sign = (n: number) => (n > 0 ? `+${n}` : String(n));
const short = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

// Шкала симметричная: ±span; округляем вверх до «красивого» числа, чтобы стрелка не прилипала к краю.
const шкала = (abs: number[]) => {
  const m = Math.max(10, ...abs) * 1.15;
  const p = 10 ** Math.floor(Math.log10(m));
  return [1, 2, 5, 10].map((x) => x * p).find((v) => v >= m)!;
};

/** Спидометр: стрелка от −span (потеряно больше) до +span (база растёт). */
function Gauge({ value, span, minus, plus, tick }: { value: number; span: number; minus: string; plus: string; tick: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => { const t = setTimeout(() => setShown(value), 50); return () => clearTimeout(t); }, [value]);
  const k = Math.max(-1, Math.min(1, shown / span));
  const R = 120, C = 150;
  const pt = (f: number, r = R) => {
    const a = Math.PI * (1 - (f + 1) / 2);
    return [C + r * Math.cos(a), C - r * Math.sin(a)];
  };
  const arc = (f1: number, f2: number) => {
    const [x1, y1] = pt(f1), [x2, y2] = pt(f2);
    return `M${x1} ${y1} A${R} ${R} 0 0 1 ${x2} ${y2}`;
  };
  const seg = 20;
  const ticks = [-1, -0.5, 0, 0.5, 1];
  return (
    <svg viewBox="0 0 300 190" className="w-full" role="img" aria-label={`Баланс базы ${sign(value)}`}>
      {Array.from({ length: seg }, (_, i) => {
        const f1 = -1 + (2 * i) / seg, f2 = -1 + (2 * (i + 1)) / seg;
        const mid = (f1 + f2) / 2;
        return (
          <path key={i} d={arc(f1 + 0.01, f2 - 0.01)} fill="none" strokeWidth={16}
            stroke={mid < 0 ? minus : plus} strokeOpacity={0.25 + 0.75 * Math.abs(mid)} />
        );
      })}
      {ticks.map((f) => {
        const [x1, y1] = pt(f, R + 12), [x2, y2] = pt(f, R + 20), [tx, ty] = pt(f, R + 32);
        return (
          <g key={f}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={tick} strokeWidth={1.5} />
            <text x={tx} y={ty + 4} textAnchor="middle" fontSize={10} fill={tick}>
              {f === 0 ? "0" : sign(Math.round(f * span))}
            </text>
          </g>
        );
      })}
      <g style={{ transform: `rotate(${k * 90}deg)`, transformOrigin: `${C}px ${C}px`, transition: "transform 1.2s cubic-bezier(.2,1.4,.4,1)" }}>
        <polygon points={`${C - 4},${C} ${C + 4},${C} ${C},${C - R + 6}`} fill={value >= 0 ? plus : minus} />
      </g>
      <circle cx={C} cy={C} r={9} fill={value >= 0 ? plus : minus} />
      <circle cx={C} cy={C} r={3.5} fill="#fff" fillOpacity={0.8} />
      <text x={C} y={C + 38} textAnchor="middle" fontSize={34} fontWeight={700} fill={value >= 0 ? plus : minus}>
        {sign(value)}
      </text>
      <text x={C} y={C + 56} textAnchor="middle" fontSize={10} fill={tick} letterSpacing={2}>
        БАЛАНС БАЗЫ
      </text>
    </svg>
  );
}

/** Баланс базы: новые минус потерянные по дням и накопленный итог с точки отсчёта. */
export default function BaseFlow() {
  const dark = useDark();
  const colors = палитраГрафика(dark);
  const pal = палитраПульса(dark);
  const [flow, setFlow] = useState<Flow | null>(null);
  const [start, setStart] = useState("");
  const [msg, setMsg] = useState("");

  const apply = (f: Flow) => {
    setFlow(f);
    setStart(f.start ?? "");
  };

  useEffect(() => {
    fetch("/api/client-base/flow")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(apply)
      .catch(() => setMsg("Не удалось получить баланс базы."));
  }, []);

  const save = async () => {
    setMsg("");
    const r = await fetch("/api/client-base/flow/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start }),
    });
    if (r.ok) apply(await r.json());
    else setMsg((await r.json().catch(() => ({}))).detail ?? "Не удалось сохранить дату.");
  };

  const today = flow?.days.at(-1);
  const early = !!flow?.start && !!flow.history_from && flow.start < flow.history_from;

  return (
    <section className="mb-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-widest text-ink-soft dark:text-cream">
            Баланс базы: новые и потерянные
          </h2>
          <p className="mt-1 text-xs text-muted-light dark:text-muted">
            Новый — первый визит или возвращение после потери. Потерянный — 61-й день без визита.
            Стрелка — накопленный итог (новые − потерянные) с точки отсчёта.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <label className="text-muted-light dark:text-muted" htmlFor="flow-start">
            Точка отсчёта
          </label>
          <input
            id="flow-start"
            type="date"
            value={start}
            max={flow?.today}
            onChange={(e) => setStart(e.target.value)}
            className="rounded-lg border border-line-light dark:border-line bg-transparent px-2 py-1"
          />
          <button
            type="button"
            onClick={save}
            disabled={!start || start === flow?.start}
            className="rounded-lg border border-line-light dark:border-line px-3 py-1 disabled:opacity-40"
          >
            Сохранить
          </button>
        </div>
      </div>

      {msg && <p className="mb-3 text-sm text-caution">{msg}</p>}
      {flow && !flow.start && (
        <div className={CARD + " text-sm text-muted-light dark:text-muted"}>
          Выберите дату, с которой считать пульс, например 1 января или начало месяца. История
          посчитается задним числом, дату можно менять.
        </div>
      )}
      {early && (
        <p className="mb-3 text-xs text-caution">
          В базе визиты только с {flow?.history_from}: до этой даты цифры неполные.
        </p>
      )}

      {flow && today && (
        <div className={CARD + " mx-auto max-w-sm py-3"}>
          <Gauge
            value={today.total}
            span={шкала(flow.days.map((d) => Math.abs(d.total)))}
            minus={pal.lost}
            plus={pal.new}
            tick={colors.ось}
          />
          <p className="mt-2 text-center text-xs text-muted-light dark:text-muted">
            с {short(flow.start!)}: новых {flow.days.reduce((s, d) => s + d.new, 0)} (из них вернулись{" "}
            {flow.days.reduce((s, d) => s + d.returned, 0)}), потеряно {flow.days.reduce((s, d) => s + d.lost, 0)}
            {" · "}сегодня {sign(today.pulse)}
          </p>
        </div>
      )}
    </section>
  );
}
