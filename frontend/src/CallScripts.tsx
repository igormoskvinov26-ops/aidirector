import { useEffect, useState } from "react";
import { Loader2, MessageSquare, Phone, Plus, RotateCcw, Save, Trash2 } from "lucide-react";

/** Скрипты обзвона: у каждой группы и каждого тега — несколько вариантов
 *  разговора.
 *
 *  Скрипт возврата из регламента салона (файл владельца 16.10.2026) — это
 *  дерево: начало, ветка по причине ухода, завершение, отдельное сообщение,
 *  если не дозвонились. Поэтому здесь не два поля, а список вариантов; админ
 *  в карточке переключает их по ходу разговора. Пустое поле означает
 *  «вернуть текст из регламента» — он показан подсказкой.
 */

interface Вариант {
  kind: string;
  key: string;
  variant: string;
  title: string;
  hint: string;
  phone_text: string | null;
  message_text: string | null;
  default_phone: string;
  default_message: string;
  custom: boolean;
  updated_by: string | null;
}

interface Раздел {
  kind: string;
  key: string;
  label: string;
  variants: Вариант[];
}

interface Данные {
  placeholders: string[];
  groups: Раздел[];
  tags: Раздел[];
}

const КАРТОЧКА =
  "rounded-2xl border border-milk-line dark:border-line/50 bg-milk-card dark:bg-panel/60 p-6";

export default function CallScripts() {
  const [д, setД] = useState<Данные | null>(null);
  const [ошибка, setОшибка] = useState<string | null>(null);
  const [открыт, setОткрыт] = useState<string | null>(null);

  const загрузить = async () => {
    try {
      const r = await fetch("/api/client-base/scripts");
      if (!r.ok) {
        setОшибка("Не удалось загрузить скрипты");
        return;
      }
      const данные: Данные = await r.json();
      setД(данные);
      setОткрыт((к) => к ?? (данные.groups[0] ? `${данные.groups[0].kind}:${данные.groups[0].key}` : null));
      setОшибка(null);
    } catch {
      setОшибка("Сервер не отвечает");
    }
  };

  useEffect(() => {
    void загрузить();
  }, []);

  if (!д) {
    return (
      <div className={КАРТОЧКА + " flex items-center gap-2 text-sm text-muted-light dark:text-muted"}>
        {ошибка ?? (
          <>
            <Loader2 size={16} className="animate-spin" /> Загружаю скрипты…
          </>
        )}
      </div>
    );
  }

  const разделы = [...д.groups, ...д.tags];
  const текущий = разделы.find((р) => `${р.kind}:${р.key}` === открыт) ?? разделы[0];

  return (
    <div className={КАРТОЧКА + " space-y-4"}>
      <div>
        <h2 className="text-lg font-semibold text-ink-soft dark:text-cream">Скрипты обзвона</h2>
        <p className="mt-1 text-sm text-muted-light dark:text-muted">
          У каждой группы и тега несколько вариантов разговора — админ
          переключает их в карточке клиента. Скрипт тега важнее скрипта группы,
          пустое поле возвращает текст из регламента. Подстановки:{" "}
          {д.placeholders.map((п) => (
            <code key={п} className="mx-0.5">{п}</code>
          ))}
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {разделы.map((р) => (
          <button
            key={`${р.kind}:${р.key}`}
            onClick={() => setОткрыт(`${р.kind}:${р.key}`)}
            className={`rounded-lg px-3 py-1.5 text-sm transition-all ${
              текущий && `${текущий.kind}:${текущий.key}` === `${р.kind}:${р.key}`
                ? "bg-milk-deep dark:bg-panel-deep text-ink-soft dark:text-cream font-medium"
                : "border border-milk-line dark:border-line text-muted-light dark:text-muted hover:border-bronze dark:hover:border-gold"
            }`}
          >
            {р.label}
            <span className="ml-1.5 text-xs opacity-70">{р.variants.length}</span>
          </button>
        ))}
      </div>

      {текущий && (
        <div className="space-y-3">
          {текущий.variants.map((в) => (
            <СтрокаВарианта key={в.variant} в={в} приСохранении={загрузить} />
          ))}
          <НовыйВариант раздел={текущий} приСохранении={загрузить} />
        </div>
      )}
    </div>
  );
}

function СтрокаВарианта({ в, приСохранении }: { в: Вариант; приСохранении: () => Promise<void> }) {
  const [звонок, setЗвонок] = useState(в.phone_text ?? "");
  const [сообщение, setСообщение] = useState(в.message_text ?? "");
  const [название, setНазвание] = useState(в.title);
  const [занято, setЗанято] = useState(false);
  const изменено =
    звонок !== (в.phone_text ?? "") || сообщение !== (в.message_text ?? "") || название !== в.title;

  const сохранить = async () => {
    setЗанято(true);
    try {
      const r = await fetch("/api/client-base/scripts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: в.kind, key: в.key, variant: в.variant, title: название,
          phone_text: звонок, message_text: сообщение,
        }),
      });
      if (r.ok) await приСохранении();
    } catch {
      /* молча: текст остался в поле, можно нажать ещё раз */
    }
    setЗанято(false);
  };

  const удалить = async () => {
    if (!window.confirm(`Удалить вариант «${в.title}»?`)) return;
    await fetch(`/api/client-base/scripts/${в.kind}/${в.key}/${в.variant}`, { method: "DELETE" });
    await приСохранении();
  };

  return (
    <div className="rounded-xl border border-milk-line dark:border-line bg-milk dark:bg-panel/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <input
          value={название}
          onChange={(e) => setНазвание(e.target.value)}
          className="font-medium text-ink-soft dark:text-cream bg-transparent border-b border-transparent hover:border-milk-line dark:hover:border-line focus:border-bronze dark:focus:border-gold focus:outline-none"
        />
        <div className="flex items-center gap-2 text-xs text-muted-light dark:text-muted">
          {в.updated_by ? `правил ${в.updated_by}` : "текст из регламента"}
          <button onClick={удалить} title="Удалить вариант" className="hover:text-loss">
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {в.hint && <p className="mt-1 text-xs text-bronze-ink dark:text-gold-2">{в.hint}</p>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Поле icon={<Phone size={12} />} подпись="Скрипт звонка" значение={звонок}
              изменить={setЗвонок} подсказка={в.default_phone} />
        <Поле icon={<MessageSquare size={12} />} подпись="Вариант сообщения" значение={сообщение}
              изменить={setСообщение} подсказка={в.default_message} />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          disabled={занято || !изменено}
          onClick={сохранить}
          className="flex items-center gap-1.5 border border-milk-line dark:border-line hover:border-bronze dark:hover:border-gold px-3 py-1.5 rounded-lg text-xs transition-all disabled:opacity-40"
        >
          <Save size={12} /> {занято ? "Сохраняю…" : "Сохранить"}
        </button>
        {(звонок || сообщение) && (
          <button
            onClick={() => { setЗвонок(""); setСообщение(""); }}
            className="flex items-center gap-1.5 text-xs text-muted-light dark:text-muted hover:text-ink-soft dark:hover:text-cream"
          >
            <RotateCcw size={12} /> вернуть текст из регламента
          </button>
        )}
      </div>
    </div>
  );
}

function НовыйВариант({ раздел, приСохранении }: { раздел: Раздел; приСохранении: () => Promise<void> }) {
  const [название, setНазвание] = useState("");
  const создать = async () => {
    const имя = название.trim();
    if (!имя) return;
    await fetch("/api/client-base/scripts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: раздел.kind, key: раздел.key, variant: `v${Date.now().toString(36)}`,
        title: имя, phone_text: "", message_text: "",
      }),
    });
    setНазвание("");
    await приСохранении();
  };
  return (
    <div className="flex items-center gap-2">
      <input
        value={название}
        onChange={(e) => setНазвание(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && создать()}
        placeholder="Название нового варианта"
        className="flex-1 bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-lg px-3 py-2 text-sm text-ink-soft dark:text-cream placeholder:text-muted-light dark:placeholder:text-muted focus:outline-none focus:border-bronze dark:focus:border-gold"
      />
      <button
        onClick={создать}
        disabled={!название.trim()}
        className="flex items-center gap-1.5 border border-milk-line dark:border-line hover:border-bronze dark:hover:border-gold px-3 py-2 rounded-lg text-sm transition-all disabled:opacity-40"
      >
        <Plus size={14} /> Добавить вариант
      </button>
    </div>
  );
}

function Поле({
  icon, подпись, значение, изменить, подсказка,
}: {
  icon: React.ReactNode;
  подпись: string;
  значение: string;
  изменить: (v: string) => void;
  подсказка: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-muted-light dark:text-muted mb-1.5">
        {icon} {подпись}
      </div>
      <textarea
        value={значение}
        onChange={(e) => изменить(e.target.value)}
        rows={4}
        placeholder={подсказка || "Текст не задан"}
        className="w-full bg-milk-card dark:bg-panel border border-milk-line dark:border-line rounded-lg px-3 py-2 text-sm text-ink-soft dark:text-cream placeholder:text-muted-light dark:placeholder:text-muted focus:outline-none focus:border-bronze dark:focus:border-gold resize-none"
      />
    </div>
  );
}
