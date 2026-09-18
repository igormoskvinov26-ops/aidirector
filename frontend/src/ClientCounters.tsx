import { useEffect, useState } from "react";
import { Award, CalendarX } from "lucide-react";

/** Ответ /api/client-base/counters. */
interface Counters {
  repeat_clients: number;
  lost_clients: number;
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
 */
export function ClientCounters() {
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

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
      <div className="flex items-center gap-4 rounded-2xl border border-bronze/30 dark:border-gold/30 bg-bronze/[0.08] dark:bg-gold/[0.10] px-5 py-4">
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

      <div className="flex items-center gap-4 rounded-2xl border border-loss/20 bg-loss/5 px-5 py-4">
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
