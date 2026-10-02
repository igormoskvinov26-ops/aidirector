import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Search } from "lucide-react";

interface Админ {
  staff_id: number;
  name: string;
  creator_values: string[];
}

interface Настройки {
  targets: { extra_services_norm: number; sales_ratio_norm_pct: number };
  extra_service_ids: number[];
  admins: Админ[];
  attribution_window_days: number;
  record_created_field: string;
  record_creator_field: string;
  horizon_days: number;
}

interface Справочники {
  staff: { id: number; name: string }[];
  services: { id: number; title: string }[];
}

interface ПробаПолей {
  records_checked: number;
  keys: Record<string, { type: string; example: unknown; filled: number }>;
  date_candidates: string[];
  creator_candidates: string[];
  authors?: Record<string, { value: string; count: number; via_api: number; last_created: string | null }[]>;
}

const КАРТОЧКА =
  "rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5";
const ПОЛЕ =
  "rounded-lg border border-milk-line dark:border-line bg-milk-card dark:bg-panel px-3 py-2 text-sm text-ink-soft dark:text-cream";

export default function ReportSettings() {
  const [н, setН] = useState<Настройки | null>(null);
  const [справ, setСправ] = useState<Справочники | null>(null);
  const [проба, setПроба] = useState<ПробаПолей | null>(null);
  const [сегодня, setСегодня] = useState<{ date: string; via_api: number; authors: { value: string; count: number; times: string[] }[] } | null>(null);
  const получитьПользователей = async () => {
    setСегодня(null);
    try {
      const r = await fetch("/api/monthly-report/today-authors");
      if (r.ok) setСегодня(await r.json());
      else alert("Не удалось получить пользователей: YCLIENTS не ответил.");
    } catch {
      alert("Не удалось получить пользователей.");
    }
  };
  const [поиск, setПоиск] = useState("");
  const [сообщение, setСообщение] = useState<string | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [занят, setЗанят] = useState(false);

  useEffect(() => {
    (async () => {
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

  const проверитьПоля = async () => {
    setЗанят(true);
    setОшибка(null);
    try {
      const r = await fetch("/api/monthly-report/fields-probe");
      if (!r.ok) throw new Error();
      setПроба(await r.json());
    } catch {
      setОшибка("Не удалось прочитать записи YCLIENTS");
    }
    setЗанят(false);
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

  const переключитьАдмина = (id: number, имя: string) => {
    const есть = н.admins.some((а) => а.staff_id === id);
    setН({
      ...н,
      admins: есть
        ? н.admins.filter((а) => а.staff_id !== id)
        : [...н.admins, { staff_id: id, name: имя, creator_values: [] }],
    });
  };

  const услуги = (справ?.services ?? []).filter((с) =>
    (с.title ?? "").toLowerCase().includes(поиск.toLowerCase()),
  );

  return (
    <div className={КАРТОЧКА + " space-y-6"}>
      <div>
        <h2 className="text-lg font-semibold text-ink-soft dark:text-cream">Месячный отчёт</h2>
        <p className="mt-1 text-sm text-muted-light dark:text-muted">
          Нормативы, допуслуги, администраторы и поля записи YCLIENTS. Нормативы месяца
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
          Поля записи YCLIENTS
        </h3>
        <p className="mb-3 text-sm text-muted-light dark:text-muted">
          Дата создания и автор записи нужны для «Сделано записей» и для проверки звонков. Их
          названия не угадываются: нажмите «Проверить поля», посмотрите, что реально приходит, и
          впишите подходящие.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">
            <span className="text-muted-light dark:text-muted">Поле даты создания записи</span>
            <input
              value={н.record_created_field}
              onChange={(e) => setН({ ...н, record_created_field: e.target.value })}
              placeholder="не задано"
              className={ПОЛЕ + " mt-1 w-full"}
            />
          </label>
          <label className="text-sm">
            <span className="text-muted-light dark:text-muted">Поле автора записи</span>
            <input
              value={н.record_creator_field}
              onChange={(e) => setН({ ...н, record_creator_field: e.target.value })}
              placeholder="не задано"
              className={ПОЛЕ + " mt-1 w-full"}
            />
          </label>
        </div>
        <button
          disabled={занят}
          onClick={проверитьПоля}
          className="mt-3 inline-flex items-center gap-2 rounded-xl border border-milk-line dark:border-line px-4 py-2 text-sm disabled:opacity-50"
        >
          <Search size={14} /> Проверить поля
        </button>
        <button
          onClick={получитьПользователей}
          className="mt-3 ml-2 inline-flex items-center gap-2 rounded-xl border border-milk-line dark:border-line px-4 py-2 text-sm"
        >
          <Search size={14} /> Получить пользователей за сегодня
        </button>
        {сегодня && (
          <div className="mt-3 rounded-xl bg-milk-deep dark:bg-panel-deep/60 p-4 text-sm">
            <p>Записи, созданные сегодня вручную (не через сайт/API: {сегодня.via_api}):</p>
            {сегодня.authors.length === 0 && <p className="mt-1"><b>нет</b></p>}
            <ul className="mt-1 font-mono text-xs">
              {сегодня.authors.map((а) => (
                <li key={а.value}>
                  {а.value} · записей {а.count} · {а.times.join(", ")}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-muted-light dark:text-muted">
              Впишите этот номер в строку администратора, который сегодня работает.
            </p>
          </div>
        )}
        {проба && (
          <div className="mt-3 rounded-xl bg-milk-deep dark:bg-panel-deep/60 p-4 text-sm">
            <p>
              Проверено записей: {проба.records_checked}. Похожи на дату:{" "}
              {проба.date_candidates.length ? (
                проба.date_candidates.map((к) => (
                  <button
                    key={к}
                    className="mr-2 underline"
                    onClick={() => setН({ ...н, record_created_field: к })}
                  >
                    {к}
                  </button>
                ))
              ) : (
                <b>нет</b>
              )}
            </p>
            <p className="mt-1">
              Похожи на автора:{" "}
              {проба.creator_candidates.length ? (
                проба.creator_candidates.map((к) => (
                  <button
                    key={к}
                    className="mr-2 underline"
                    onClick={() => setН({ ...н, record_creator_field: к })}
                  >
                    {к}
                  </button>
                ))
              ) : (
                <b>нет</b>
              )}
            </p>
            {Object.entries(проба.authors ?? {}).map(([поле, список]) => (
              <div key={поле} className="mt-2">
                <p className="text-muted-light dark:text-muted">
                  Кто создавал записи ({поле}). Впишите нужное число в строку администратора:
                </p>
                <ul className="mt-1 font-mono text-xs">
                  {список.map((а) => (
                    <li key={а.value}>
                      {а.value} · записей {а.count}
                      {а.via_api ? ` (через сайт/API: ${а.via_api})` : ""}
                      {а.last_created ? ` · последняя ${а.last_created.slice(0, 16).replace("T", " ")}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <details className="mt-2">
              <summary className="cursor-pointer text-muted-light dark:text-muted">
                Все поля записи
              </summary>
              <ul className="mt-2 space-y-0.5 font-mono text-xs">
                {Object.entries(проба.keys).map(([к, i]) => (
                  <li key={к}>
                    {к} · {i.type} · заполнено {i.filled}/{проба.records_checked}
                    {i.example != null && typeof i.example !== "object" ? ` · ${String(i.example)}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink-soft dark:text-cream">
            Администраторы ({н.admins.length})
          </h3>
          {!справ && (
            <button
              disabled={занят}
              onClick={загрузитьСправочники}
              className="rounded-xl border border-milk-line dark:border-line px-3 py-1.5 text-sm disabled:opacity-50"
            >
              Выбрать из YCLIENTS
            </button>
          )}
        </div>
        {н.admins.map((а) => (
          <div key={а.staff_id} className="mb-2 grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
            <input value={а.name} readOnly className={ПОЛЕ} />
            <input
              value={а.creator_values.join(", ")}
              onChange={(e) =>
                setН({
                  ...н,
                  admins: н.admins.map((x) =>
                    x.staff_id === а.staff_id
                      ? { ...x, creator_values: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) }
                      : x,
                  ),
                })
              }
              placeholder="как автор записи выглядит в YCLIENTS (id или имя), через запятую"
              className={ПОЛЕ}
            />
            <button
              onClick={() => переключитьАдмина(а.staff_id, а.name)}
              className="rounded-lg border border-milk-line dark:border-line px-3 text-sm"
            >
              Убрать
            </button>
          </div>
        ))}
        {справ && (
          <div className="mt-2 flex flex-wrap gap-2">
            {справ.staff
              .filter((с) => !н.admins.some((а) => а.staff_id === с.id))
              .map((с) => (
                <button
                  key={с.id}
                  onClick={() => переключитьАдмина(с.id, с.name)}
                  className="rounded-full border border-milk-line dark:border-line px-3 py-1 text-sm hover:border-bronze dark:hover:border-gold"
                >
                  + {с.name}
                </button>
              ))}
          </div>
        )}
        <p className="mt-2 text-xs text-muted-light dark:text-muted">
          Этот список виден на странице обзвона: администратор выбирает своё имя перед результатом
          звонка.
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
