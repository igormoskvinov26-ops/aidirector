import { useEffect, useState } from "react";
import { Award, CalendarX } from "lucide-react";

/** Ответ /api/client-base/counters. */
interface Counters {
  repeat_clients: number;
  lost_clients: number;
}

interface ClientCountersProps {
  /** Клик по плитке — переключает график динамики на этот показатель.
   *  Ключ совпадает с ключом серии в /api/client-base/metric-history:
   *  "global:repeat_clients" или "global:lost_clients". Без onSelect
   *  плитки остаются просто плитками, без клика. */
  onSelect?: (key: string, label: string, тон: "profit" | "loss") => void;
  /** Ключ выбранного сейчас показателя — подсвечивает активную плитку. */
  selected?: string | null;
}

/** Два счётчика на весь салон — решение владельца 18.09.2026: «Повторные»
 *  (клиенты с двумя и более завершёнными визитами — растёт один раз, в
 *  момент закрытия второго визита, независимо от срока между ними) и
 *  «Потерянные» (последний визит или запись старше 60 дней; будущая запись
 *  снимает статус). Общие для «Записей за месяц» и «Клиентской базы» — один
 *  компонент, чтобы формулировка не разошлась между двумя страницами.
 *
 *  «Повторные» — положительный показатель, оформлен торжественно: крупнее
 *  обычной плитки, золотой акцент. «Потерянные» — предупреждение, цвет и
 *  вес соответствуют.
 *
 *  Клик по плитке переключает график динамики по дням (решение владельца
 *  18.09.2026, уточнено в том же разговоре) — если родитель передал
 *  onSelect. Активная плитка обводится цветом показателя.
 */
export function ClientCounters({ onSelect, selected }: ClientCountersProps) {
  const [data, setData] = useState<Counters | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/client-base/counters");
        if (r.ok) setData(await r.json());
      } catch {
        // молча: это дополнение к странице, не она сама
      }
    })();
  }, []);

  if (!data) return null;

  const кликабельно = "cursor-pointer transition-shadow hover:shadow-md";
  const активна = "ring-2 ring-offset-0";

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
      <div
        onClick={() => onSelect?.("global:repeat_clients", "Повторные", "profit")}
        className={`flex items-center gap-4 rounded-2xl border border-bronze/30 dark:border-gold/30 bg-bronze/[0.08] dark:bg-gold/[0.10] px-5 py-4 ${onSelect ? кликабельно : ""} ${selected === "global:repeat_clients" ? `${активна} ring-bronze dark:ring-gold` : ""}`}
      >
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-bronze/15 dark:bg-gold/15">
          <Award size={20} className="text-bronze dark:text-gold" />
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-widest text-bronze dark:text-gold">
            Повторные
          </div>
          <div className="text-3xl font-extrabold tabular-nums text-bronze dark:text-gold">
            {data.repeat_clients}
          </div>
          <div className="text-xs text-muted-light dark:text-muted">
            дошли до второго визита и дальше
          </div>
        </div>
      </div>

      <div
        onClick={() => onSelect?.("global:lost_clients", "Потерянные", "loss")}
        className={`flex items-center gap-4 rounded-2xl border border-loss/20 bg-loss/5 px-5 py-4 ${onSelect ? кликабельно : ""} ${selected === "global:lost_clients" ? `${активна} ring-loss` : ""}`}
      >
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-loss/10">
          <CalendarX size={20} className="text-loss" />
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-widest text-loss">
            Потерянные
          </div>
          <div className="text-3xl font-extrabold tabular-nums text-loss">
            {data.lost_clients}
          </div>
          <div className="text-xs text-muted-light dark:text-muted">
            не были и не записаны 60+ дней
          </div>
        </div>
      </div>
    </div>
  );
}
