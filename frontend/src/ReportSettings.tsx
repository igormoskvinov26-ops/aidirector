import { useEffect, useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";

interface Админ {
  staff_id: number;
  name: string;
  creator_values: string[];
}

interface Настройки {
  targets: { extra_services_norm: number; sales_ratio_norm_pct: number };
  extra_service_ids: number[];
  admins: Админ[];
  hidden_admins: number[];
  attribution_window_days: number;
  record_created_field: string;
  record_creator_field: string;
  horizon_days: number;
}

interface Справочники {
  staff: { id: number; name: string }[];
  services: { id: number; title: string }[];
}

const КАРТОЧКА =
  "rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5";
const ПОЛЕ =
  "rounded-lg border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-3 py-2 text-sm text-ink-soft dark:text-cream";

export default function ReportSettings() {
  const [н, setН] = useState<Настройки | null>(null);
  const [справ, setСправ] = useState<Справочники | null>(null);
  const [найденныеАдмины, setНайденныеАдмины] = useState<{ staff_id: number; name: string }[] | null>(null);
  const [новыйАдмин, setНовыйАдмин] = useState("");
  const [поиск, setПоиск] = useState("");
  const [сообщение, setСообщение] = useState<string | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [занят, setЗанят] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const a = await fetch("/api/monthly-report/admins");
        if (a.ok) setНайденныеАдмины((await a.json()).admins);
      } catch {
        /* список справочный */
      }
      try {
        const r = await fetch("/api/monthly-report/settings");
        if (r.ok) setН(await r.json());
        else setОшибка("Настройки отчёта недоступны");
      } catch {
        setОшибка("Сервер не отвечает");
      }
    })();
  }, []);

  const загрузитьСправочники = async () => {
    setЗанят(true);
    setОшибка(null);
    try {
      const r = await fetch("/api/monthly-report/staff");
      if (!r.ok) throw new Error();
      setСправ(await r.json());
    } catch {
      setОшибка("Не удалось прочитать сотрудников и услуги из YCLIENTS");
    }
    setЗанят(false);
  };

  /** Кто звонит: скрыть уволенного, вернуть, добавить нового — сохраняется сразу. */
  const сохранитьАдминов = async (admins: Админ[], hidden: number[]) => {
    if (!н) return;
    setЗанят(true);
    setОшибка(null);
    try {
      const r = await fetch("/api/monthly-report/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ admins, hidden_admins: hidden }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? "не сохранено");
      const тело: Настройки = await r.json();
      setН({ ...н, admins: тело.admins, hidden_admins: тело.hidden_admins });
      const a = await fetch("/api/monthly-report/admins");
      if (a.ok) setНайденныеАдмины((await a.json()).admins);
    } catch (e) {
      setОшибка(e instanceof Error ? e.message : "Не сохранено");
    }
    setЗанят(false);
  };
  const скрытьАдмина = (id: number, скрыть: boolean) => {
    if (!н) return;
    const h = new Set(н.hidden_admins ?? []);
    if (скрыть) h.add(id); else h.delete(id);
    сохранитьАдминов(н.admins, [...h]);
  };
  const добавитьАдмина = () => {
    const имя = новыйАдмин.trim();
    if (!н || !имя) return;
    // Номер свой, отрицательный: пока у нового нет записей в YCLIENTS. Когда
    // появятся, Пульт найдёт его по имени и склеит (имя — как в YCLIENTS).
    const id = -(Date.now() % 1_000_000_000);
    сохранитьАдминов([...н.admins, { staff_id: id, name: имя, creator_values: [] }], н.hidden_admins ?? []);
    setНовыйАдмин("");
  };

  const сохранить = async () => {
    if (!н) return;
    setЗанят(true);
    setОшибка(null);
    setСообщение(null);
    try {
      const r = await fetch("/api/monthly-report/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(н),
      });
      const тело = await r.json().catch(() => ({}));
      if (!r.ok) {
        setОшибка(тело.detail || "Не сохранено");
      } else {
        setН(тело);
        setСообщение("Сохранено. Отчёт пересчитается при следующем обновлении.");
      }
    } catch {
      setОшибка("Сервер не отвечает");
    }
    setЗанят(false);
  };

  if (!н) {
    return (
      <div className={КАРТОЧКА + " text-sm text-muted-light dark:text-muted"}>
        {ошибка ?? (
          <span className="flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Загружаю настройки отчёта…
          </span>
        )}
      </div>
    );
  }

  const услуги = (справ?.services ?? []).filter((с) =>
    (с.title ?? "").toLowerCase().includes(поиск.toLowerCase()),
  );

  return (
    <div className={КАРТОЧКА + " space-y-6"}>
      <div>
        <h2 className="text-lg font-semibold text-ink-soft dark:text-cream">Месячный отчёт</h2>
        <p className="mt-1 text-sm text-muted-light dark:text-muted">
          Нормативы и допуслуги. Нормативы месяца
          запоминаются в итоге, поэтому смена нормы не меняет прошлые месяцы.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-sm">
          <span className="text-muted-light dark:text-muted">Допуслуг в месяц (норма)</span>
          <input
            type="number"
            min={0}
            value={н.targets.extra_services_norm}
            onChange={(e) =>
              setН({ ...н, targets: { ...н.targets, extra_services_norm: Number(e.target.value) } })
            }
            className={ПОЛЕ + " mt-1 w-full"}
          />
        </label>
        <label className="text-sm">
          <span className="text-muted-light dark:text-muted">Продажи от услуг, % (норма)</span>
          <input
            type="number"
            min={0}
            step="0.5"
            value={н.targets.sales_ratio_norm_pct}
            onChange={(e) =>
              setН({
                ...н,
                targets: { ...н.targets, sales_ratio_norm_pct: Number(e.target.value) },
              })
            }
            className={ПОЛЕ + " mt-1 w-full"}
          />
        </label>
        <label className="text-sm">
          <span className="text-muted-light dark:text-muted">Окно проверки звонка, дней</span>
          <input
            type="number"
            min={0}
            max={60}
            value={н.attribution_window_days}
            onChange={(e) => setН({ ...н, attribution_window_days: Number(e.target.value) })}
            className={ПОЛЕ + " mt-1 w-full"}
          />
        </label>
        <label className="text-sm">
          <span className="text-muted-light dark:text-muted">Горизонт записей вперёд, дней</span>
          <input
            type="number"
            min={7}
            max={365}
            value={н.horizon_days}
            onChange={(e) => setН({ ...н, horizon_days: Number(e.target.value) })}
            className={ПОЛЕ + " mt-1 w-full"}
          />
        </label>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink-soft dark:text-cream">
          Администраторы — кто звонит ({найденныеАдмины?.length ?? "…"})
        </h3>
        {найденныеАдмины && найденныеАдмины.length > 0 ? (
          <ul className="divide-y divide-milk-line dark:divide-line rounded-xl border border-milk-line dark:border-line">
            {найденныеАдмины.map((а) => {
              const скрыт = (н.hidden_admins ?? []).includes(а.staff_id);
              return (
                <li key={а.staff_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                  <span className={скрыт ? "text-muted-light dark:text-muted line-through" : "text-ink-soft dark:text-cream"}>
                    {а.name}
                    {скрыт && <span className="ml-2 no-underline text-xs">не звонит</span>}
                  </span>
                  <button
                    disabled={занят}
                    onClick={() => скрытьАдмина(а.staff_id, !скрыт)}
                    className="rounded-lg border border-milk-line dark:border-line px-2.5 py-1 text-xs hover:border-bronze dark:hover:border-gold disabled:opacity-50"
                  >
                    {скрыт ? "Вернуть в список" : "Убрать из списка"}
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-light dark:text-muted">
            {найденныеАдмины ? "Пока никого не нашлось среди авторов записей за последний месяц." : "…"}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={новыйАдмин}
            onChange={(e) => setНовыйАдмин(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") добавитьАдмина(); }}
            placeholder="Имя нового администратора, как в YCLIENTS"
            className={ПОЛЕ + " min-w-[260px] flex-1"}
          />
          <button
            disabled={занят || !новыйАдмин.trim()}
            onClick={добавитьАдмина}
            className="rounded-xl border border-milk-line dark:border-line px-3 py-2 text-sm hover:border-bronze dark:hover:border-gold disabled:opacity-50"
          >
            Добавить
          </button>
        </div>
        <p className="mt-2 text-xs text-muted-light dark:text-muted">
          Список виден на странице обзвона, в выборе «Кто звонит». Тех, кто создаёт записи вручную
          в YCLIENTS, Пульт находит сам. Нового можно добавить сразу, не дожидаясь его первой записи;
          уволенного — убрать: в месячном отчёте за прошлые месяцы его работа остаётся.
          Изменения сохраняются сразу.
        </p>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink-soft dark:text-cream">
          Дополнительные услуги ({н.extra_service_ids.length})
        </h3>
        {!справ ? (
          <button
            disabled={занят}
            onClick={загрузитьСправочники}
            className="rounded-xl border border-milk-line dark:border-line px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Выбрать из услуг YCLIENTS
          </button>
        ) : (
          <>
            <input
              value={поиск}
              onChange={(e) => setПоиск(e.target.value)}
              placeholder="Найти услугу"
              className={ПОЛЕ + " mb-2 w-full sm:w-72"}
            />
            <div className="max-h-56 space-y-1 overflow-auto rounded-xl border border-milk-line dark:border-line p-3">
              {услуги.map((с) => (
                <label key={с.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={н.extra_service_ids.includes(с.id)}
                    onChange={(e) =>
                      setН({
                        ...н,
                        extra_service_ids: e.target.checked
                          ? [...н.extra_service_ids, с.id]
                          : н.extra_service_ids.filter((x) => x !== с.id),
                      })
                    }
                  />
                  {с.title}
                </label>
              ))}
            </div>
          </>
        )}
        <p className="mt-2 text-xs text-muted-light dark:text-muted">
          Пока список пуст, «Доп. услуги» в отчёте не считаются. Любую вторую услугу
          дополнительной система не объявляет.
        </p>
      </div>

      {ошибка && <p className="text-sm text-red-600 dark:text-red-400">{ошибка}</p>}
      {сообщение && (
        <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300">
          <CheckCircle2 size={16} /> {сообщение}
        </p>
      )}
      <button
        disabled={занят}
        onClick={сохранить}
        className="rounded-xl bg-bronze dark:bg-gold px-5 py-2 text-sm font-medium text-milk-card dark:text-panel-deep disabled:opacity-50"
      >
        {занят ? "Сохраняю…" : "Сохранить"}
      </button>
    </div>
  );
}
