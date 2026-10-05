import { useEffect, useState } from "react";
import { Plus } from "lucide-react";

interface Branch {
  id: string;
  name: string;
}

const FIELD =
  "rounded-lg border border-milk-line dark:border-line bg-milk dark:bg-ink px-3 py-2 text-sm text-ink-soft dark:text-cream w-full";

async function errText(r: Response): Promise<string> {
  try {
    return (await r.json()).detail ?? `Ошибка ${r.status}`;
  } catch {
    return `Ошибка ${r.status}`;
  }
}

/** Выбор филиала и «Добавить филиал». Показывается только главному владельцу. */
export default function BranchSwitcher() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [active, setActive] = useState("main");
  const [can, setCan] = useState(false);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    manager_login: "",
    manager_password: "",
    admin_login: "",
    admin_password: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const r = await fetch("/api/branches");
        if (!r.ok) return;
        const d = await r.json();
        setBranches(d.branches);
        setActive(d.active);
        setCan(d.can_manage);
      } catch {
        /* без переключателя Пульт работает как раньше */
      }
    })();
  }, []);

  if (!can) return null;

  async function post(url: string, body: unknown) {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        setErr(await errText(r));
        return false;
      }
      window.location.reload(); // данные всех страниц относятся к прежнему филиалу
      return true;
    } catch {
      setErr("Сервер не отвечает");
      return false;
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  return (
    <div className="mb-6 space-y-2">
      {branches.length > 1 && (
        <select
          className={FIELD}
          value={active}
          disabled={busy}
          onChange={(e) => void post("/api/branches/switch", { id: e.target.value })}
          aria-label="Филиал"
        >
          {branches.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      )}
      {err && !open && <div className="text-xs text-red-600 dark:text-red-400">{err}</div>}
      <button
        onClick={() => setOpen(true)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-muted-light dark:text-muted hover:bg-milk-deep dark:hover:bg-panel"
      >
        <Plus size={16} /> Добавить филиал
      </button>

      {open && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl bg-milk-card dark:bg-panel p-6 space-y-3 text-ink-soft dark:text-cream">
            <h2 className="text-lg font-semibold">Новый филиал</h2>
            <p className="text-xs text-muted-light dark:text-muted">
              У филиала своя база и свои ключи YCLIENTS. Логины и пароли — не короче 6 символов. После создания
              зайдите в «Настройки» и впишите токены YCLIENTS и номер компании этого филиала.
            </p>
            <input className={FIELD} placeholder="Название филиала" value={form.name} onChange={set("name")} />
            <div className="text-xs font-medium pt-1">Управляющий</div>
            <input className={FIELD} placeholder="Логин" value={form.manager_login} onChange={set("manager_login")} />
            <input
              className={FIELD} type="password" placeholder="Пароль"
              value={form.manager_password} onChange={set("manager_password")}
            />
            <div className="text-xs font-medium pt-1">Администратор</div>
            <input className={FIELD} placeholder="Логин" value={form.admin_login} onChange={set("admin_login")} />
            <input
              className={FIELD} type="password" placeholder="Пароль"
              value={form.admin_password} onChange={set("admin_password")}
            />
            {err && <div className="text-sm text-red-600 dark:text-red-400">{err}</div>}
            <div className="flex gap-2 justify-end pt-2">
              <button className="px-4 py-2 rounded-xl text-sm" disabled={busy} onClick={() => setOpen(false)}>
                Отмена
              </button>
              <button
                className="px-4 py-2 rounded-xl text-sm bg-bronze dark:bg-gold text-milk dark:text-ink font-medium disabled:opacity-40"
                disabled={busy}
                onClick={() => void post("/api/branches", form)}
              >
                {busy ? "Создаю…" : "Создать"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
