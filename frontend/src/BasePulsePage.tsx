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
import { Activity, Phone, X } from "lucide-react";
import { useDark, палитраГрафика, шкалаСегментов } from "./тема";

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
  base_total: number;
  lost_after_days: number;
}

/** Ответ /api/client-base/pulse-clients. */
interface PulseClient {
  client_id: number;
  name: string | null;
  phone: string | null;
  visits_total: number;
  visits_to_master: number;
  master: string | null;
  last_visit: string;
  days_since: number;
  /** Дата, с которой клиент считается потерянным. null для прочих сегментов. */
  lost_since: string | null;
}

const NO_MASTER = 0;

/** Пояснение под каждым блоком: из чего состоит сегмент. */
const ПОЯСНЕНИЯ: Record<string, string> = {
  new: "Первый визит — и клиент ещё в игре. Второй визит переведёт его в лояльные.",
  loyal:
    "От двух до четырёх визитов к одному мастеру. Отсюда растут постоянные — "
    + "или утекают потерянные.",
  regular: "Пять визитов и больше к одному мастеру. Опора выручки.",
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

/** Пульс базы: четыре сегмента в разрезе мастеров — решение владельца 23.09.2026.
 *
 *  Каждый клиент попадает ровно в один столбец одного блока, поэтому сумма
 *  всех столбцов равна базе. Без этого по гистограмме нельзя было бы судить,
 *  растёт база или сжимается, — а это главный вопрос, ради которого страница.
 *
 *  Цвет: три растущих сегмента — один брендовый тон светлотой от светлого к
 *  тёмному (новый → лояльный → постоянный), потому что это упорядоченный ряд,
 *  а не разные категории. Потерянные — красным: здесь цвет означает прямой
 *  вердикт, как в числах убытка по всему приложению. Шаги взяты из уже
 *  проверенной шкалы сегментов в тема.ts, новых цветов не заводится.
 */
export default function BasePulsePage() {
  const тёмная = useDark();
  const цвета = палитраГрафика(тёмная);
  const шкала = шкалаСегментов(тёмная);

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

  // Три растущих сегмента — шаги одной шкалы, от светлого к тёмному.
  // Берутся через один, чтобы соседние блоки различались наверняка.
  const ЦВЕТ: Record<string, string> = {
    new: шкала.active,
    loyal: шкала.risk,
    regular: шкала.lost,
    lost: цвета.убыток,
  };

  return (
    <div className="animate-in">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight mb-1 text-ink-soft dark:text-cream">
          Пульс базы
        </h1>
        <p className="text-muted-light dark:text-muted text-sm">
          Вся база — {data.base_total} клиентов — разложена по четырём сегментам и мастерам.
          Клиент считается «своим» у того мастера, у которого был чаще. Нажмите на столбец,
          чтобы увидеть, кто за ним стоит.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {data.segments.map((segment) => (
          <div
            key={segment.code}
            className="bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl p-5"
          >
            <div className="flex items-baseline gap-3 mb-1">
              <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-light dark:text-muted">
                {segment.label}
              </h2>
              <span
                className="text-2xl font-bold"
                style={{ color: ЦВЕТ[segment.code] }}
              >
                {segment.total}
              </span>
            </div>
            <p className="text-xs text-muted-light dark:text-muted mb-3">
              {ПОЯСНЕНИЯ[segment.code]}
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
                    if (точка.payload) открыть(segment, точка.payload);
                  }}
                >
                  {segment.columns.map((column) => (
                    <Cell
                      key={column.staff_id}
                      fill={ЦВЕТ[segment.code]}
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
        ))}
      </div>

      {ячейка && (
        <div className="mt-4 bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-2xl overflow-hidden">
          <div className="flex items-center gap-2 px-5 pt-4 pb-3">
            <Activity size={16} style={{ color: ЦВЕТ[ячейка.segment.code] }} />
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
                  <th className="px-3 pb-2 text-right text-[11px] font-normal">последний</th>
                  <th className="px-5 pb-2 text-right text-[11px] font-normal">
                    {ячейка.segment.code === "lost" ? "потерян с" : "дней назад"}
                  </th>
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
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted-light dark:text-muted">
                      {дата(c.last_visit)}
                    </td>
                    <td className="px-5 py-2.5 text-right tabular-nums text-ink-soft dark:text-cream">
                      {c.lost_since ? дата(c.lost_since) : c.days_since}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <p className="mt-4 text-xs text-muted-light dark:text-muted leading-relaxed">
        Сегменты не пересекаются: постоянный не считается заодно лояльным, поэтому сумма
        всех столбцов равна базе целиком. «Без мастера» — клиент ходит в салон, но ни к
        одному барберу не набрал даже двух визитов: деньги приносит, а привязан к месту,
        а не к человеку. Такой уходит легче всех. Чем темнее столбец в первых трёх блоках,
        тем прочнее связь клиента с мастером.
      </p>
    </div>
  );
}
