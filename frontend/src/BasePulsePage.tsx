import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts";
import {
  BellRing,
  Crown,
  Heart,
  Phone,
  Repeat2,
  Sparkles,
  UserX,
  X,
  type LucideIcon,
} from "lucide-react";
import { useDark, палитраГрафика, палитраПульса } from "./тема";

/** Ответ /api/client-base/pulse. */
interface PulseColumn {
  staff_id: number;
  name: string;
  count: number;
}

interface PulseSegment {
  code: string;
  label: string;
  total: number;
  columns: PulseColumn[];
}

interface PulseData {
  segments: PulseSegment[];
  risk_zone: PulseSegment;
  base_total: number;
  lost_after_days: number;
  risk_zone_min_days: number;
}

/** Ответ /api/client-base/pulse-clients. */
interface PulseClient {
  client_id: number;
  name: string | null;
  phone: string | null;
  visits_total: number;
  master: string | null;
  last_visit: string;
  days_since: number;
  /** Дата, с которой клиент считается потерянным. null для прочих сегментов. */
  lost_since: string | null;
}

const NO_MASTER = 0;

/** Значок на каждую плитку — решение владельца 25.09.2026: опознаётся с
 *  одного взгляда, раньше, чем прочитана подпись. */
const ЗНАЧОК: Record<string, LucideIcon> = {
  new: Sparkles,
  second: Repeat2,
  loyal: Heart,
  vip: Crown,
  lost: UserX,
  risk: BellRing,
};

/** Пояснение под каждым блоком: из чего состоит сегмент. */
const ПОЯСНЕНИЯ: Record<string, string> = {
  new: "Один визит. Второй переведёт его во «второй визит».",
  second: "Ровно два визита. Здесь решается, вернётся ли клиент снова.",
  loyal: "От трёх до девяти визитов. Отсюда растут VIP — или утекают потерянные.",
  vip: "Десять визитов и больше. Опора выручки.",
  lost: "Не был в салоне дольше 60 дней и не записан вперёд.",
};

/** «12.08» — короткая дата для списка. */
function дата(iso: string): string {
  const д = new Date(iso + "T00:00:00");
  return `${String(д.getDate()).padStart(2, "0")}.${String(д.getMonth() + 1).padStart(2, "0")}`;
}

/** Подпись столбца на оси: длинное «Без своего мастера» рвёт вёрстку. */
function подписьСтолбца(c: PulseColumn): string {
  return c.staff_id === NO_MASTER ? "Без мастера" : c.name;
}

/** Одна плитка сегмента: значок, число, гистограмма по мастерам.
 *
 *  Цветной левый кант и залитый значок — общий язык «профессиональных»
 *  дашбордов: сегмент опознаётся по трём независимым каналам сразу (значок,
 *  подпись, цвет), а не только по цвету, который часть читателей не
 *  различает.
 */
function ПлиткаСегмента({
  segment,
  цвет,
  доляБазы,
  тёмная,
  onColumnClick,
}: {
  segment: PulseSegment;
  цвет: string;
  /** Доля от базы в процентах — null для зоны риска, она не часть базы. */
  доляБазы: number | null;
  тёмная: boolean;
  onColumnClick: (column: PulseColumn) => void;
}) {
  // Тема приходит пропсом, а не через свой useDark(): шесть плиток на
  // странице иначе завели бы шесть собственных MutationObserver на один и
  // тот же document.documentElement — родитель уже следит за ним один раз.
  const цвета = палитраГрафика(тёмная);
  const Значок = ЗНАЧОК[segment.code];

  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5 pl-6 transition-shadow hover:shadow-lg hover:shadow-black/5 dark:hover:shadow-black/30"
      style={{ borderLeftColor: цвет, borderLeftWidth: 3 }}
    >
      <div className="flex items-start justify-between gap-3 mb-1">
        <div className="flex items-center gap-2.5">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
            style={{ background: `${цвет}1f`, color: цвет }}
          >
            <Значок size={17} strokeWidth={2.25} />
          </div>
          <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
            {segment.label}
          </h2>
        </div>
        {доляБазы !== null && (
          <span className="mt-0.5 text-[11px] font-medium tabular-nums text-muted-light dark:text-muted">
            {доляБазы}%
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-2xl font-bold" style={{ color: цвет }}>
          {segment.total}
        </span>
      </div>
      <p className="text-xs text-muted-light dark:text-muted mb-3">
        {ПОЯСНЕНИЯ[segment.code] ?? ""}
      </p>

      <ResponsiveContainer width="100%" height={190}>
        <BarChart
          data={segment.columns}
          margin={{ top: 22, right: 8, left: 8, bottom: 0 }}
          barCategoryGap="28%"
        >
          <XAxis
            dataKey={подписьСтолбца}
            tick={{ fontSize: 12, fill: цвета.ось }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            cursor={{ fill: тёмная ? "#ffffff0d" : "#0000000a" }}
            contentStyle={{
              background: цвета.подсказкаФон,
              border: `1px solid ${цвета.подсказкаРамка}`,
              borderRadius: "12px",
              fontSize: 12,
            }}
            formatter={(value) => [`${value}`, segment.label]}
          />
          <Bar
            dataKey="count"
            radius={[4, 4, 0, 0]}
            cursor="pointer"
            onClick={(bar: unknown) => {
              const точка = bar as { payload?: PulseColumn };
              if (точка.payload) onColumnClick(точка.payload);
            }}
          >
            {segment.columns.map((column) => (
              <Cell
                key={column.staff_id}
                fill={цвет}
                // «Без своего мастера» — тот же показатель, но не мастер:
                // приглушением отделяем его от трёх настоящих столбцов.
                fillOpacity={column.staff_id === NO_MASTER ? 0.45 : 1}
              />
            ))}
            <LabelList
              dataKey="count"
              position="top"
              style={{ fontSize: 13, fontWeight: 600, fill: цвета.сейчас }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Пульс базы: пять сегментов плюс зона риска, столбец — последний мастер —
 *  решение владельца 25.09.2026.
 *
 *  Каждый клиент попадает ровно в один столбец одного из пяти сегментов,
 *  поэтому сумма их столбцов равна базе. Без этого по гистограмме нельзя
 *  было бы судить, растёт база или сжимается, — а это главный вопрос, ради
 *  которого страница. Зона риска — отдельный, шестой блок: она
 *  пересекается с любым из пяти (важна только свежесть визита), поэтому в
 *  сумму базы не входит и оформлена отдельно, как список на звонок, а не
 *  как часть разбиения.
 *
 *  Сегмент считается по общему числу визитов клиента во всём салоне, а
 *  столбец — просто тот, кто вёл его последний визит: без приписки «по
 *  частоте» и без отдельного разбора разрозненных визитов.
 */
export default function BasePulsePage() {
  const тёмная = useDark();
  const палитра = палитраПульса(тёмная);

  const [data, setData] = useState<PulseData | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState("");
  const [ячейка, setЯчейка] = useState<{ segment: PulseSegment; column: PulseColumn } | null>(null);
  const [клиенты, setКлиенты] = useState<PulseClient[] | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/client-base/pulse");
        if (!r.ok) throw new Error(`сервер ответил ${r.status}`);
        setData(await r.json());
      } catch (e) {
        setFailed(e instanceof Error ? e.message : "не удалось получить данные");
      }
      setLoading(false);
    })();
  }, []);

  const открыть = async (segment: PulseSegment, column: PulseColumn) => {
    setЯчейка({ segment, column });
    setКлиенты(null);
    try {
      const r = await fetch(
        `/api/client-base/pulse-clients?segment=${segment.code}&staff_id=${column.staff_id}`
      );
      setКлиенты(r.ok ? await r.json() : []);
    } catch {
      setКлиенты([]);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-light dark:text-muted">
        Загружаю…
      </div>
    );
  }

  if (failed || !data) {
    return (
      <div className="animate-in rounded-2xl border border-caution/30 bg-caution/5 p-6 text-sm text-caution">
        Не удалось получить данные. {failed}
      </div>
    );
  }

  const цветЯчейки = ячейка
    ? (палитра[ячейка.segment.code] ?? палитра.new)
    : палитра.new;

  return (
    <div className="animate-in">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight mb-1 text-ink-soft dark:text-cream">
          Пульс базы
        </h1>
        <p className="text-muted-light dark:text-muted text-sm">
          Вся база — {data.base_total} клиентов — разложена по пяти сегментам и мастерам.
          Столбец — тот, кто вёл последний визит клиента. Нажмите на столбец, чтобы увидеть,
          кто за ним стоит.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
        {data.segments.map((segment) => (
          <ПлиткаСегмента
            key={segment.code}
            segment={segment}
            цвет={палитра[segment.code]}
            доляБазы={
              data.base_total > 0 ? Math.round((segment.total / data.base_total) * 100) : 0
            }
            тёмная={тёмная}
            onColumnClick={(column) => открыть(segment, column)}
          />
        ))}
      </div>

      <div className="mt-6 mb-3">
        <div className="flex items-center gap-2">
          <BellRing size={16} style={{ color: палитра.risk }} />
          <h2 className="text-sm font-semibold uppercase tracking-widest text-ink-soft dark:text-cream">
            Зона риска
          </h2>
        </div>
        <p className="text-muted-light dark:text-muted text-sm mt-1">
          Не потерян, но не был от {data.risk_zone_min_days + 1} до {data.lost_after_days - 1}{" "}
          дней — самое время напомнить о записи, пока не перешёл в потерянные. Пересекается с
          сегментами выше, поэтому в базу отдельной строкой не суммируется.
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
        <ПлиткаСегмента
          segment={data.risk_zone}
          цвет={палитра.risk}
          доляБазы={null}
          тёмная={тёмная}
          onColumnClick={(column) => открыть(data.risk_zone, column)}
        />
      </div>

      {ячейка && (
        <div className="mt-4 bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl overflow-hidden">
          <div className="flex items-center gap-2 px-5 pt-4 pb-3">
            {(() => {
              const Значок = ЗНАЧОК[ячейка.segment.code];
              return Значок ? <Значок size={16} style={{ color: цветЯчейки }} /> : null;
            })()}
            <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
              {ячейка.segment.label} · {ячейка.column.name}
            </h2>
            <button
              onClick={() => setЯчейка(null)}
              className="ml-auto text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
              aria-label="Закрыть список"
            >
              <X size={16} />
            </button>
          </div>

          {клиенты === null ? (
            <p className="px-5 pb-4 text-sm text-muted-light dark:text-muted">Загружаю…</p>
          ) : клиенты.length === 0 ? (
            <p className="px-5 pb-4 text-sm text-muted-light dark:text-muted">
              В этой ячейке никого.
            </p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-muted-light dark:text-muted">
                  <th className="px-5 pb-2 text-left text-[11px] font-normal">Клиент</th>
                  <th className="px-3 pb-2 text-left text-[11px] font-normal">Телефон</th>
                  <th className="px-3 pb-2 text-right text-[11px] font-normal">визитов</th>
                  <th className="px-3 pb-2 text-right text-[11px] font-normal">
                    дней с визита
                  </th>
                  <th className="px-3 pb-2 text-right text-[11px] font-normal">последний</th>
                  {ячейка.segment.code === "lost" && (
                    <th className="px-5 pb-2 text-right text-[11px] font-normal">потерян с</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {клиенты.map((c) => (
                  <tr
                    key={c.client_id}
                    className="border-t border-milk-line/70 dark:border-line/70"
                  >
                    <td className="px-5 py-2.5 text-ink-soft dark:text-cream">
                      {c.name || "Без имени"}
                    </td>
                    <td className="px-3 py-2.5">
                      {c.phone ? (
                        <a
                          href={`tel:${c.phone}`}
                          className="inline-flex items-center gap-1.5 text-bronze dark:text-gold hover:underline"
                        >
                          <Phone size={13} />
                          {c.phone}
                        </a>
                      ) : (
                        <span className="text-muted-light dark:text-muted">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ink-soft dark:text-cream">
                      {c.visits_total}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ink-soft dark:text-cream">
                      {c.days_since}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted-light dark:text-muted">
                      {дата(c.last_visit)}
                    </td>
                    {ячейка.segment.code === "lost" && (
                      <td className="px-5 py-2.5 text-right tabular-nums text-ink-soft dark:text-cream">
                        {c.lost_since ? дата(c.lost_since) : "—"}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <p className="mt-4 text-xs text-muted-light dark:text-muted leading-relaxed">
        Сегменты не пересекаются: VIP не считается заодно лояльным, поэтому сумма всех
        столбцов равна базе целиком. Столбец — не приписка «по частоте», а просто мастер,
        который вёл последний визит клиента: у каждого клиента такой мастер ровно один, а
        значит, и ячейка тоже ровно одна. «Без мастера» — последний визит вёл не барбер
        (администратор) или мастер уже не в штате.
      </p>
    </div>
  );
}
