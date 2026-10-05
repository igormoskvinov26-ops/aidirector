import { useCallback, useEffect, useRef, useState } from "react";
import ReportSettings from "./ReportSettings";
import SalonSettings from "./SalonSettings";
import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  FileUp,
  KeyRound,
  Loader2,
  Plug,
  RotateCcw,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";

/** Одно поле настройки. Секрет наружу не уходит: приходит только маска. */
interface Поле {
  key: string;
  title: string;
  hint: string;
  kind: "text" | "number" | "password";
  secret: boolean;
  required: boolean;
  configured: boolean;
  /** Маска для секрета, значение как есть — для остального. */
  display: string;
  source: "process_env" | "managed" | "env_file" | "none";
  /** Задано переменной окружения — здесь не меняется. */
  locked: boolean;
}

interface Интеграция {
  id: string;
  name: string;
  description: string;
  critical: boolean;
  applies_immediately: boolean;
  status: string;
  error: string | null;
  fields: Поле[];
}

interface Обзор {
  integrations: Интеграция[];
  ready: boolean;
  missing: string[];
}

interface ПолеПредпросмотра {
  key: string;
  title: string;
  found: boolean;
  required: boolean;
  display: string;
  /** Значение уже есть, и файл его не трогает. */
  kept: boolean;
  locked: boolean;
}

interface Предпросмотр {
  integrations: {
    id: string;
    name: string;
    status_now: string;
    status_after: string;
    fields: ПолеПредпросмотра[];
  }[];
  unknown: string[];
  applicable: string[];
}

interface Проверка {
  ok: boolean;
  message: string;
  status: string;
}

const НАСТРОЕНО = "настроено";
const ЧАСТИЧНО = "настроено частично";
const ОШИБКА_СВЯЗИ = "ошибка подключения";

interface СтатусСервера {
  configured: boolean;
  ok: boolean | null;
  at: string | null;
  error: string | null;
  pushed?: number;
  pulled?: number;
}

/** «16:24» для сегодняшнего обмена, иначе «04.10 16:24». */
function когдаКратко(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const t = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const сегодня = new Date().toDateString() === d.toDateString();
  return сегодня ? `в ${t}` : `${d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })} ${t}`;
}

/** Цвет и значок статуса. Один взгляд должен отвечать на вопрос «всё ли в порядке». */
function видСтатуса(статус: string) {
  if (статус === НАСТРОЕНО) {
    return { цвет: "text-emerald-600 dark:text-emerald-400", Значок: CheckCircle2 };
  }
  if (статус === ОШИБКА_СВЯЗИ) {
    return { цвет: "text-red-600 dark:text-red-400", Значок: AlertTriangle };
  }
  if (статус === ЧАСТИЧНО) {
    return { цвет: "text-amber-600 dark:text-amber-400", Значок: AlertTriangle };
  }
  return { цвет: "text-muted-light dark:text-muted", Значок: CircleSlash };
}

const ПОДПИСЬ_ИСТОЧНИКА: Record<Поле["source"], string> = {
  process_env: "задано на сервере",
  managed: "задано здесь",
  env_file: "из файла .env",
  none: "",
};

const КАРТОЧКА =
  "rounded-2xl border border-milk-line dark:border-line/50 bg-milk-card dark:bg-panel/60 p-6";

const КНОПКА =
  "inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm transition-colors " +
  "disabled:opacity-40 disabled:cursor-not-allowed";

const КНОПКА_ГЛАВНАЯ =
  КНОПКА +
  " bg-bronze dark:bg-gold text-milk dark:text-ink font-medium hover:opacity-90";

const КНОПКА_ОБЫЧНАЯ =
  КНОПКА +
  " border border-milk-line dark:border-line/50 text-ink-soft dark:text-cream " +
  "hover:bg-milk-deep dark:hover:bg-panel";

const ПОЛЕ_ВВОДА =
  "w-full px-3 py-2 rounded-lg bg-milk dark:bg-ink border border-milk-line " +
  "dark:border-line/50 text-sm text-ink-soft dark:text-cream " +
  "placeholder:text-muted-light/60 dark:placeholder:text-muted/60 " +
  "focus:outline-none focus:border-bronze dark:focus:border-gold";

async function разобратьОшибку(ответ: Response): Promise<string> {
  try {
    const тело = await ответ.json();
    return тело.detail || `Ошибка ${ответ.status}`;
  } catch {
    return `Ошибка ${ответ.status}`;
  }
}

export default function SettingsPage() {
  const [обзор, setОбзор] = useState<Обзор | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [сообщение, setСообщение] = useState<string | null>(null);

  const загрузить = useCallback(async () => {
    try {
      const ответ = await fetch("/api/settings/integrations");
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        return;
      }
      setОбзор(await ответ.json());
      setОшибка(null);
    } catch {
      setОшибка("Сервер не отвечает");
    }
  }, []);

  useEffect(() => {
    void загрузить();
  }, [загрузить]);

  if (ошибка && !обзор) {
    return (
      <div className={КАРТОЧКА + " text-sm text-red-600 dark:text-red-400"}>{ошибка}</div>
    );
  }
  if (!обзор) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-light dark:text-muted">
        <Loader2 size={16} className="animate-spin" /> Загружаю настройки…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-ink-soft dark:text-cream">
          Настройки · Интеграции
        </h1>
        <p className="text-sm text-muted-light dark:text-muted mt-1">
          Ключи, по которым Пульт ходит за данными. Их можно вписать руками
          или загрузить готовым файлом <code>.env</code>.
        </p>
      </header>

      {сообщение && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300 flex items-start gap-2">
          <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
          <span className="flex-1">{сообщение}</span>
          <button onClick={() => setСообщение(null)} aria-label="Скрыть">
            <X size={14} />
          </button>
        </div>
      )}

      <ЗагрузкаФайла
        приУспехе={async (текст) => {
          await загрузить();
          setСообщение(текст);
        }}
      />

      {обзор.integrations.map((интеграция) => (
        <КарточкаИнтеграции
          key={интеграция.id}
          интеграция={интеграция}
          приИзменении={загрузить}
          приСообщении={setСообщение}
        />
      ))}

      <SalonSettings />

      <ReportSettings />

      <УчёткаВладельца />

      <Журнал />
    </div>
  );
}

// ── Загрузка .env ─────────────────────────────────────────────────────────

/** Кнопка «Загрузить .env» с обязательным предпросмотром.
 *
 *  Файл сначала показывается и только потом применяется: в нём ключи от
 *  чужого филиала — ошибка, которую по одному имени файла не видно, а по
 *  последствиям видно сразу и надолго.
 */
function ЗагрузкаФайла({ приУспехе }: { приУспехе: (текст: string) => void }) {
  const выбор = useRef<HTMLInputElement>(null);
  const [файл, setФайл] = useState<File | null>(null);
  const [предпросмотр, setПредпросмотр] = useState<Предпросмотр | null>(null);
  const [занято, setЗанято] = useState(false);
  const [ошибка, setОшибка] = useState<string | null>(null);

  async function отправить(куда: string, файлДляОтправки: File) {
    const тело = new FormData();
    тело.append("file", файлДляОтправки);
    return fetch(куда, { method: "POST", body: тело });
  }

  async function выбрать(выбранный: File) {
    setЗанято(true);
    setОшибка(null);
    try {
      const ответ = await отправить("/api/settings/import/preview", выбранный);
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        setПредпросмотр(null);
        setФайл(null);
        return;
      }
      setПредпросмотр(await ответ.json());
      setФайл(выбранный);
    } finally {
      setЗанято(false);
    }
  }

  async function применить() {
    if (!файл) return;
    setЗанято(true);
    try {
      const ответ = await отправить("/api/settings/import/apply", файл);
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        return;
      }
      const тело = await ответ.json();
      const сколько = (тело.changed ?? []).length;
      отменить();
      приУспехе(
        сколько
          ? `Из файла применено настроек: ${сколько}.`
          : "В файле не было ничего нового — настройки не изменились.",
      );
    } finally {
      setЗанято(false);
    }
  }

  function отменить() {
    setФайл(null);
    setПредпросмотр(null);
    setОшибка(null);
    if (выбор.current) выбор.current.value = "";
  }

  return (
    <div className={КАРТОЧКА}>
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 text-ink-soft dark:text-cream font-medium">
            <FileUp size={18} className="text-bronze dark:text-gold" />
            Загрузить готовый .env
          </div>
          <p className="text-sm text-muted-light dark:text-muted mt-1">
            Возьмутся только те строки, которые Пульт умеет использовать.
            Остальные будут показаны и пропущены.
          </p>
        </div>
        <input
          ref={выбор}
          type="file"
          className="hidden"
          onChange={(e) => {
            const выбранный = e.target.files?.[0];
            if (выбранный) void выбрать(выбранный);
          }}
        />
        <button
          className={КНОПКА_ОБЫЧНАЯ}
          disabled={занято}
          onClick={() => выбор.current?.click()}
        >
          {занято ? <Loader2 size={16} className="animate-spin" /> : <FileUp size={16} />}
          Выбрать файл
        </button>
      </div>

      {ошибка && (
        <div className="mt-4 text-sm text-red-600 dark:text-red-400">{ошибка}</div>
      )}

      {предпросмотр && (
        <div className="mt-6 space-y-4 border-t border-milk-line dark:border-line/50 pt-5">
          <div className="text-sm text-muted-light dark:text-muted">
            Что даст этот файл. Пока ничего не изменено.
          </div>

          {предпросмотр.integrations.map((и) => (
            <div key={и.id}>
              <div className="flex items-center gap-2 text-sm font-medium text-ink-soft dark:text-cream">
                {и.name}
                <span className="text-muted-light dark:text-muted font-normal">
                  {и.status_now} → {и.status_after}
                </span>
              </div>
              <ul className="mt-2 space-y-1">
                {и.fields.map((п) => (
                  <li key={п.key} className="text-sm flex items-center gap-2">
                    {п.found ? (
                      <CheckCircle2 size={14} className="text-emerald-500 shrink-0" />
                    ) : п.kept ? (
                      <ShieldCheck size={14} className="text-muted-light dark:text-muted shrink-0" />
                    ) : (
                      <X size={14} className="text-muted-light dark:text-muted shrink-0" />
                    )}
                    <span className="text-ink-soft dark:text-cream">{п.title}</span>
                    <span className="text-muted-light dark:text-muted">
                      {п.found
                        ? `найден${п.display ? ` · ${п.display}` : ""}`
                        : п.kept
                          ? "в файле нет — останется прежним"
                          : п.required
                            ? "не найден"
                            : "не найден (необязательный)"}
                    </span>
                    {п.locked && (
                      <span className="text-xs text-amber-600 dark:text-amber-400">
                        задано на сервере — не изменится
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {предпросмотр.unknown.length > 0 && (
            <div className="text-sm">
              <div className="text-muted-light dark:text-muted">
                Не используется Пультом — будет пропущено:
              </div>
              <div className="mt-1 font-mono text-xs text-muted-light dark:text-muted">
                {предпросмотр.unknown.join(", ")}
              </div>
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button
              className={КНОПКА_ГЛАВНАЯ}
              disabled={занято || предпросмотр.applicable.length === 0}
              onClick={() => void применить()}
            >
              Применить настройки
            </button>
            <button className={КНОПКА_ОБЫЧНАЯ} onClick={отменить} disabled={занято}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Карточка одной интеграции ─────────────────────────────────────────────

function КарточкаИнтеграции({
  интеграция,
  приИзменении,
  приСообщении,
}: {
  интеграция: Интеграция;
  приИзменении: () => Promise<void>;
  приСообщении: (текст: string) => void;
}) {
  const [правка, setПравка] = useState(false);
  const [значения, setЗначения] = useState<Record<string, string>>({});
  const [занято, setЗанято] = useState(false);
  const [проверка, setПроверка] = useState<Проверка | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [синхр, setСинхр] = useState<СтатусСервера | null>(null);

  useEffect(() => {
    if (интеграция.id !== "hub") return;
    let жив = true;
    const опрос = async () => {
      try {
        const r = await fetch("/api/settings/hub/status");
        if (жив && r.ok) setСинхр(await r.json());
      } catch {
        /* сеть моргнула — покажем при следующем опросе */
      }
    };
    void опрос();
    const t = setInterval(() => void опрос(), 15000);
    return () => {
      жив = false;
      clearInterval(t);
    };
  }, [интеграция.id]);

  const { цвет, Значок } = видСтатуса(проверка ? проверка.status : интеграция.status);
  const ничегоНеЗаполнено = интеграция.fields.every((п) => !п.configured);

  async function сохранить() {
    setЗанято(true);
    setОшибка(null);
    try {
      const ответ = await fetch("/api/settings/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: значения }),
      });
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        return;
      }
      const тело = await ответ.json();
      setЗначения({});
      setПравка(false);
      setПроверка(null);
      await приИзменении();
      приСообщении(
        (тело.changed ?? []).length
          ? интеграция.applies_immediately
            ? "Настройки сохранены и уже действуют — перезапуск не нужен."
            : "Настройки сохранены. Для применения требуется перезапуск Пульта."
          : "Ничего не изменилось.",
      );
    } finally {
      setЗанято(false);
    }
  }

  async function проверитьСвязь() {
    setЗанято(true);
    setОшибка(null);
    try {
      const ответ = await fetch(`/api/settings/test/${интеграция.id}`, { method: "POST" });
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        return;
      }
      setПроверка(await ответ.json());
    } finally {
      setЗанято(false);
    }
  }

  async function сбросить(ключ: string, подпись: string) {
    if (!confirm(`Убрать «${подпись}»? Интеграция перестанет работать, пока поле пустое.`)) {
      return;
    }
    setЗанято(true);
    try {
      const ответ = await fetch("/api/settings/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: ключ }),
      });
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        return;
      }
      setПроверка(null);
      await приИзменении();
      приСообщении(`«${подпись}» убрано.`);
    } finally {
      setЗанято(false);
    }
  }

  async function тестовоеСообщение() {
    setЗанято(true);
    setОшибка(null);
    try {
      const ответ = await fetch("/api/settings/telegram/test-message", { method: "POST" });
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        return;
      }
      приСообщении("Тестовое сообщение отправлено — проверьте чат.");
    } finally {
      setЗанято(false);
    }
  }

  return (
    <div className={КАРТОЧКА}>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <Plug size={18} className="text-bronze dark:text-gold" />
            <span className="font-medium text-ink-soft dark:text-cream">
              {интеграция.name}
            </span>
            <span className={`inline-flex items-center gap-1.5 text-sm ${цвет}`}>
              <Значок size={14} />
              {проверка ? проверка.status : интеграция.status}
            </span>
          </div>
          <p className="text-sm text-muted-light dark:text-muted mt-1 max-w-xl">
            {интеграция.description}
          </p>
        </div>

        {/* ml-auto, чтобы при переносе на вторую строку кнопки оставались
            справа: иначе у карточки с тремя кнопками они уезжают под текст,
            и две карточки подряд выглядят по-разному. */}
        <div className="flex gap-2 flex-wrap ml-auto justify-end">
          <button
            className={КНОПКА_ОБЫЧНАЯ}
            disabled={занято || ничегоНеЗаполнено}
            onClick={() => void проверитьСвязь()}
          >
            {занято ? <Loader2 size={16} className="animate-spin" /> : <Plug size={16} />}
            Проверить подключение
          </button>
          {интеграция.id === "telegram" && (
            <button
              className={КНОПКА_ОБЫЧНАЯ}
              disabled={занято || интеграция.status !== НАСТРОЕНО}
              onClick={() => void тестовоеСообщение()}
            >
              <Send size={16} />
              Тестовое сообщение
            </button>
          )}
          <button className={КНОПКА_ОБЫЧНАЯ} onClick={() => setПравка(!правка)}>
            <KeyRound size={16} />
            {правка ? "Свернуть" : ничегоНеЗаполнено ? "Настроить" : "Изменить"}
          </button>
        </div>
      </div>

      {(проверка || интеграция.error) && (
        <div
          className={`mt-4 text-sm ${
            проверка?.ok
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-red-600 dark:text-red-400"
          }`}
        >
          {проверка ? проверка.message : интеграция.error}
        </div>
      )}
      {ошибка && <div className="mt-4 text-sm text-red-600 dark:text-red-400">{ошибка}</div>}

      {интеграция.id === "hub" && синхр?.configured && (
        <div className="mt-4 text-sm">
          {синхр.ok === null && <span className="text-muted-light dark:text-muted">Обмена ещё не было — подождите до минуты.</span>}
          {синхр.ok === true && (
            <span className="text-emerald-600 dark:text-emerald-400">
              Синхронизация работает. Последний обмен {когдаКратко(синхр.at)}: отправлено {синхр.pushed ?? 0}, получено{" "}
              {синхр.pulled ?? 0}.
            </span>
          )}
          {синхр.ok === false && (
            <span className="text-red-600 dark:text-red-400">
              Последний обмен {когдаКратко(синхр.at)} не прошёл: {синхр.error}. Пульт повторит сам.
            </span>
          )}
        </div>
      )}

      {/* Что настроено сейчас. Секретов здесь нет — только маски. */}
      <dl className="mt-5 grid gap-x-8 gap-y-2 sm:grid-cols-2">
        {интеграция.fields.map((поле) => (
          <div key={поле.key} className="flex items-baseline justify-between gap-3">
            <dt className="text-sm text-muted-light dark:text-muted">{поле.title}</dt>
            <dd className="text-sm font-mono text-ink-soft dark:text-cream text-right">
              {поле.configured ? (
                <>
                  {поле.display}
                  {ПОДПИСЬ_ИСТОЧНИКА[поле.source] && (
                    <span className="ml-2 font-sans text-xs text-muted-light dark:text-muted">
                      {ПОДПИСЬ_ИСТОЧНИКА[поле.source]}
                    </span>
                  )}
                </>
              ) : (
                <span className="font-sans text-muted-light dark:text-muted">
                  {поле.required ? "не заполнено" : "не заполнено (необязательно)"}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>

      {интеграция.id === "yclients" && (
        <ТокенПоЛогину приИзменении={приИзменении} приСообщении={приСообщении} />
      )}

      {правка && (
        <div className="mt-6 space-y-4 border-t border-milk-line dark:border-line/50 pt-5">
          {интеграция.fields.map((поле) => (
            <div key={поле.key}>
              <label className="block text-sm text-ink-soft dark:text-cream mb-1.5">
                {поле.title}
                {!поле.required && (
                  <span className="text-muted-light dark:text-muted"> · необязательно</span>
                )}
              </label>
              <div className="flex gap-2">
                <input
                  className={ПОЛЕ_ВВОДА}
                  type={поле.kind === "password" ? "password" : поле.kind}
                  inputMode={поле.kind === "number" ? "numeric" : undefined}
                  autoComplete="off"
                  disabled={поле.locked}
                  placeholder={
                    поле.locked
                      ? "задано на сервере — здесь не меняется"
                      : поле.configured
                        ? "оставьте пустым, чтобы не менять"
                        : "впишите значение"
                  }
                  value={значения[поле.key] ?? ""}
                  onChange={(e) =>
                    setЗначения({ ...значения, [поле.key]: e.target.value })
                  }
                />
                {поле.configured && !поле.locked && (
                  <button
                    className={КНОПКА_ОБЫЧНАЯ + " shrink-0"}
                    disabled={занято}
                    onClick={() => void сбросить(поле.key, поле.title)}
                    title="Убрать значение"
                    aria-label={`Убрать «${поле.title}»`}
                  >
                    <RotateCcw size={16} />
                  </button>
                )}
              </div>
              {поле.hint && (
                <p className="text-xs text-muted-light dark:text-muted mt-1">{поле.hint}</p>
              )}
            </div>
          ))}

          <div className="flex gap-3 pt-1">
            <button
              className={КНОПКА_ГЛАВНАЯ}
              disabled={занято || Object.values(значения).every((з) => !з.trim())}
              onClick={() => void сохранить()}
            >
              {занято && <Loader2 size={16} className="animate-spin" />}
              Сохранить
            </button>
            <button
              className={КНОПКА_ОБЫЧНАЯ}
              onClick={() => {
                setЗначения({});
                setПравка(false);
              }}
            >
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Пользовательский токен YCLIENTS по логину ─────────────────────────────

/** Пользовательский токен YCLIENTS в кабинете не показывается — его выдают
 *  только в обмен на логин и пароль сотрудника. Раньше для этого был скрипт
 *  в терминале; здесь то же самое одной формой. Логин и пароль уходят на
 *  сервер одним запросом и нигде не сохраняются. */
function ТокенПоЛогину({
  приИзменении,
  приСообщении,
}: {
  приИзменении: () => Promise<void>;
  приСообщении: (текст: string) => void;
}) {
  const [открыта, setОткрыта] = useState(false);
  const [логин, setЛогин] = useState("");
  const [пароль, setПароль] = useState("");
  const [занято, setЗанято] = useState(false);
  const [ошибка, setОшибка] = useState<string | null>(null);

  async function получить() {
    setЗанято(true);
    setОшибка(null);
    try {
      const ответ = await fetch("/api/settings/yclients/user-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ login: логин, password: пароль }),
      });
      if (!ответ.ok) {
        setОшибка(await разобратьОшибку(ответ));
        return;
      }
      const тело = await ответ.json();
      setПароль("");
      setОткрыта(false);
      await приИзменении();
      приСообщении(тело.message ?? "Токен получен и сохранён.");
    } catch {
      setОшибка("Сервер не отвечает");
    } finally {
      setЗанято(false);
    }
  }

  if (!открыта) {
    return (
      <button
        className="mt-4 text-sm text-bronze dark:text-gold hover:underline"
        onClick={() => setОткрыта(true)}
      >
        Получить новый токен по логину и паролю YCLIENTS
      </button>
    );
  }

  return (
    <div className="mt-5 space-y-3 border-t border-milk-line dark:border-line/50 pt-5">
      <p className="text-sm text-muted-light dark:text-muted">
        Логин и пароль от кабинета YCLIENTS — не от Пульта. Телефон без плюса,
        например 79991234567, или почта. Они нужны на один запрос и нигде не
        сохраняются. Партнёрский токен должен быть уже вписан.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <input
          className={ПОЛЕ_ВВОДА}
          placeholder="Логин YCLIENTS"
          autoComplete="off"
          value={логин}
          onChange={(e) => setЛогин(e.target.value)}
        />
        <input
          className={ПОЛЕ_ВВОДА}
          type="password"
          placeholder="Пароль YCLIENTS"
          autoComplete="off"
          value={пароль}
          onChange={(e) => setПароль(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void получить()}
        />
      </div>
      {ошибка && <div className="text-sm text-red-600 dark:text-red-400">{ошибка}</div>}
      <div className="flex gap-3">
        <button
          className={КНОПКА_ГЛАВНАЯ}
          disabled={занято || !логин.trim() || !пароль}
          onClick={() => void получить()}
        >
          {занято && <Loader2 size={16} className="animate-spin" />}
          Получить токен
        </button>
        <button
          className={КНОПКА_ОБЫЧНАЯ}
          onClick={() => {
            setПароль("");
            setОткрыта(false);
          }}
        >
          Отмена
        </button>
      </div>
    </div>
  );
}

// ── Учётная запись Владельца ──────────────────────────────────────────────

/** Отдельный вход Владельца. Виден только Владельцу (сервер отвечает 403
 *  остальным). Пока его нет, Владельцем считается главный вход. */
function УчёткаВладельца() {
  const [есть, setЕсть] = useState<{ exists: boolean; login: string } | null>(null);
  const [логин, setЛогин] = useState("");
  const [пароль, setПароль] = useState("");
  const [повтор, setПовтор] = useState("");
  const [занято, setЗанято] = useState(false);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [готово, setГотово] = useState(false);

  useEffect(() => {
    void (async () => {
      const r = await fetch("/api/settings/top-account").catch(() => null);
      if (r?.ok) setЕсть(await r.json());
    })();
  }, []);

  if (!есть) return null;

  async function сохранить() {
    if (пароль !== повтор) {
      setОшибка("Пароли не совпадают");
      return;
    }
    setЗанято(true);
    setОшибка(null);
    try {
      const r = await fetch("/api/settings/top-account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ login: логин, password: пароль }),
      });
      if (!r.ok) {
        setОшибка(await разобратьОшибку(r));
        return;
      }
      setГотово(true);
      setПароль("");
      setПовтор("");
    } catch {
      setОшибка("Сервер не отвечает");
    } finally {
      setЗанято(false);
    }
  }

  return (
    <div className={КАРТОЧКА + " space-y-3"}>
      <div className="flex items-center gap-2 font-semibold text-ink-soft dark:text-cream">
        <ShieldCheck size={18} className="text-bronze dark:text-gold" /> Учётная запись Владельца
      </div>
      <p className="text-sm text-muted-light dark:text-muted max-w-[75ch]">
        {есть.exists
          ? `Заведена, логин «${есть.login}». Здесь можно сменить логин или пароль.`
          : "Пока отдельного входа нет, и Владельцем считается общий вход управляющего. "}
        {" "}Только Владелец видит «Контроль финансов» и добавляет филиалы. После того как
        учётка заведена, общий вход становится входом Управляющего — без этих разделов.
      </p>
      {готово ? (
        <p className="text-sm text-profit max-w-[75ch]">
          Сохранено. Браузер помнит прежний вход, поэтому закройте его полностью (или откройте
          окно инкогнито) и войдите в Пульт под логином Владельца.
        </p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <input className={ПОЛЕ_ВВОДА} placeholder="Логин" value={логин} autoComplete="off"
              onChange={(e) => setЛогин(e.target.value)} />
            <input className={ПОЛЕ_ВВОДА} placeholder="Пароль, от 6 знаков" type="password" value={пароль}
              autoComplete="new-password" onChange={(e) => setПароль(e.target.value)} />
            <input className={ПОЛЕ_ВВОДА} placeholder="Пароль ещё раз" type="password" value={повтор}
              autoComplete="new-password" onChange={(e) => setПовтор(e.target.value)} />
          </div>
          {ошибка && <p role="alert" className="text-sm text-loss">{ошибка}</p>}
          <button className={КНОПКА_ГЛАВНАЯ} disabled={занято || !логин.trim() || !пароль}
            onClick={() => void сохранить()}>
            {занято && <Loader2 size={16} className="animate-spin" />}
            {есть.exists ? "Сменить" : "Завести учётку Владельца"}
          </button>
        </>
      )}
    </div>
  );
}

// ── Журнал изменений ──────────────────────────────────────────────────────

interface Запись {
  at: string | null;
  who: string;
  integration: string;
  key: string;
  action: string;
}

const ДЕЙСТВИЕ: Record<string, string> = {
  changed: "изменён",
  removed: "убран",
};

const КТО: Record<string, string> = {
  owner: "Управляющий",
  operator: "Администратор",
};

function Журнал() {
  const [записи, setЗаписи] = useState<Запись[] | null>(null);
  const [открыт, setОткрыт] = useState(false);

  useEffect(() => {
    if (!открыт || записи) return;
    void (async () => {
      const ответ = await fetch("/api/settings/audit");
      if (ответ.ok) setЗаписи((await ответ.json()).entries ?? []);
    })();
  }, [открыт, записи]);

  return (
    <div className={КАРТОЧКА}>
      <button
        className="text-sm text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
        onClick={() => setОткрыт(!открыт)}
      >
        {открыт ? "Скрыть журнал изменений" : "Журнал изменений"}
      </button>

      {открыт && (
        <div className="mt-4">
          {записи === null && (
            <div className="text-sm text-muted-light dark:text-muted">Загружаю…</div>
          )}
          {записи?.length === 0 && (
            <div className="text-sm text-muted-light dark:text-muted">
              Настройки ещё не меняли.
            </div>
          )}
          {записи && записи.length > 0 && (
            <ul className="space-y-1.5">
              {записи.map((з, i) => (
                <li key={i} className="text-sm text-muted-light dark:text-muted">
                  <span className="font-mono text-xs">
                    {з.at
                      ? new Date(з.at).toLocaleString("ru-RU", {
                          timeZone: "Europe/Moscow",
                          day: "2-digit",
                          month: "2-digit",
                          year: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "—"}
                  </span>
                  {"  "}
                  {КТО[з.who] ?? з.who} · {з.integration} · {з.key}{" "}
                  {ДЕЙСТВИЕ[з.action] ?? з.action}
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-light dark:text-muted mt-3">
            Сами значения здесь не хранятся — только то, какой параметр меняли.
          </p>
        </div>
      )}
    </div>
  );
}
