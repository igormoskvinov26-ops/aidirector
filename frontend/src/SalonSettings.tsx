import { useEffect, useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";

interface Barber {
  staff_id: number;
  name: string;
  service_rate: number;
  product_rate: number;
  guarantee: number;
}
interface Staff {
  id: number;
  name: string;
}
interface Salon {
  name: string;
  booking_url: string;
  has_logo: boolean;
  backgrounds?: { light: number | null; dark: number | null };
}

const CARD = "rounded-2xl border border-milk-line dark:border-line bg-milk-card dark:bg-panel p-5";
const FIELD =
  "rounded-lg border border-milk-line dark:border-line bg-milk dark:bg-ink px-3 py-2 text-sm text-ink-soft dark:text-cream";
const BTN =
  "inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm bg-bronze dark:bg-gold text-milk dark:text-ink font-medium hover:opacity-90 disabled:opacity-40";

async function errText(r: Response): Promise<string> {
  try {
    return (await r.json()).detail ?? `Ошибка ${r.status}`;
  } catch {
    return `Ошибка ${r.status}`;
  }
}

export default function SalonSettings() {
  const [salon, setSalon] = useState<Salon | null>(null);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [barbers, setBarbers] = useState<Barber[]>([]);
  const [staffErr, setStaffErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [flags, setFlags] = useState<{
    error?: string;
    candidates?: string[];
    staff?: { id: number; name: string; barber: boolean; flags: Record<string, unknown> }[];
  } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const s = await fetch("/api/salon");
      if (s.ok) setSalon(await s.json());
      const b = await fetch("/api/settings/barbers");
      if (b.ok) {
        const d = await b.json();
        setStaff(d.staff);
        setBarbers(d.barbers);
      } else setStaffErr(await errText(b));
    })();
  }, []);

  async function post(url: string, body: unknown, ok: string) {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) setErr(await errText(r));
      else {
        setMsg(ok);
        return await r.json();
      }
    } catch {
      setErr("Сервер не отвечает");
    } finally {
      setBusy(false);
    }
  }

  async function uploadLogo(file: File) {
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/salon/logo", { method: "POST", body: fd });
    setBusy(false);
    if (!r.ok) return setErr(await errText(r));
    setMsg("Логотип загружен. Обновите страницу, чтобы увидеть его в шапке.");
    setSalon((s) => (s ? { ...s, has_logo: true } : s));
  }

  async function фон(тема: "light" | "dark", file: File | null) {
    setBusy(true);
    setErr(null);
    let r: Response;
    if (file) {
      const fd = new FormData();
      fd.append("file", file);
      r = await fetch(`/api/salon/background/${тема}`, { method: "POST", body: fd });
    } else {
      r = await fetch(`/api/salon/background/${тема}`, { method: "DELETE" });
    }
    setBusy(false);
    if (!r.ok) return setErr(await errText(r));
    const d = await r.json();
    setSalon((s) => (s ? { ...s, backgrounds: d.backgrounds } : s));
    setMsg(file ? "Фон загружен. Обновите страницу, чтобы увидеть его." : "Вернул встроенный фон. Обновите страницу.");
  }

  if (!salon) return null;
  const byId = new Map(barbers.map((b) => [b.staff_id, b]));
  const toggle = (s: Staff) =>
    setBarbers((cur) =>
      byId.has(s.id)
        ? cur.filter((b) => b.staff_id !== s.id)
        : [...cur, { staff_id: s.id, name: s.name, service_rate: 0.4, product_rate: 0.1, guarantee: 0 }],
    );
  const patch = (id: number, p: Partial<Barber>) =>
    setBarbers((cur) => cur.map((b) => (b.staff_id === id ? { ...b, ...p } : b)));

  return (
    <section className={CARD + " space-y-5"}>
      <h2 className="text-lg font-semibold text-ink-soft dark:text-cream">Заведение</h2>
      {msg && (
        <div className="text-sm text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
          <CheckCircle2 size={16} /> {msg}
        </div>
      )}
      {err && <div className="text-sm text-red-600 dark:text-red-400">{err}</div>}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          Название (в сообщениях, сторис, шапке)
          <input
            className={FIELD + " w-full mt-1"}
            value={salon.name}
            maxLength={60}
            onChange={(e) => setSalon({ ...salon, name: e.target.value })}
          />
        </label>
        <label className="text-sm">
          Адрес онлайн-записи (для сторис)
          <input
            className={FIELD + " w-full mt-1"}
            value={salon.booking_url}
            placeholder="n123456.yclients.com"
            onChange={(e) => setSalon({ ...salon, booking_url: e.target.value })}
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          className={BTN}
          disabled={busy}
          onClick={() => post("/api/salon", { name: salon.name, booking_url: salon.booking_url }, "Сохранено")}
        >
          Сохранить
        </button>
        <label className="text-sm cursor-pointer underline">
          {salon.has_logo ? "Заменить логотип" : "Загрузить логотип"}
          <input
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && void uploadLogo(e.target.files[0])}
          />
        </label>
      </div>

      <div className="space-y-2">
        <div className="text-sm font-medium text-ink-soft dark:text-cream">Фон под карточками</div>
        <p className="text-xs text-muted-light dark:text-muted max-w-[70ch]">
          Горизонтальное фото от 1920 px шириной, спокойная фактура без мелких деталей и текста.
          Поверх ляжет полупрозрачная вуаль, чтобы цифры читались. Фото ужимается автоматически.
        </p>
        <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          {([["light", "Светлая тема"], ["dark", "Тёмная тема"]] as const).map(([тема, подпись]) => (
            <div key={тема} className="flex items-center gap-3">
              <span>{подпись}:</span>
              <label className="cursor-pointer underline">
                {salon.backgrounds?.[тема] ? "заменить фото" : "загрузить фото"}
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) void фон(тема, f);
                  }}
                />
              </label>
              {salon.backgrounds?.[тема] != null && (
                <button className="underline text-muted-light dark:text-muted" disabled={busy} onClick={() => void фон(тема, null)}>
                  вернуть встроенный
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        <button
          className="text-sm underline"
          onClick={async () => {
            const r = await fetch("/api/settings/staff-flags");
            setFlags(r.ok ? await r.json() : { error: await errText(r) });
          }}
        >
          Показать признаки сотрудников из YCLIENTS
        </button>
        {flags?.error && <div className="text-sm text-red-600 dark:text-red-400">{flags.error}</div>}
        {flags?.staff && (
          <div className="mt-2 text-xs space-y-1">
            <div>
              Поля, которые у барберов «истина», а у остальных «ложь»:{" "}
              <b>{flags.candidates?.length ? flags.candidates.join(", ") : "не найдено"}</b>
            </div>
            {flags.staff.map((s) => (
              <details key={s.id}>
                <summary>
                  {s.name} {s.barber ? "(барбер)" : ""}
                </summary>
                <div className="font-mono">
                  {Object.entries(s.flags).map(([k, v]) => `${k}=${String(v)}`).join(" · ")}
                </div>
              </details>
            ))}
          </div>
        )}
      </div>

      <div>
        <h3 className="font-medium text-ink-soft dark:text-cream">Барберы и условия оплаты</h3>
        <p className="text-xs text-muted-light dark:text-muted mb-3">
          Барберы определяются сами: это сотрудники YCLIENTS, у которых за последние 60 дней были визиты клиентов. Здесь можно поменять ставки. Если кто-то определился по ошибке, снимите галочку, и он больше не вернётся.
        </p>
        {staffErr && <div className="text-sm text-red-600 dark:text-red-400">{staffErr}</div>}
        {!staffErr && staff.length === 0 && <Loader2 size={16} className="animate-spin" />}
        {barbers.length === 0 && staff.length > 0 && (
          <div className="text-sm text-amber-600 mb-2">Барберы пока не определены: они появятся после первой выгрузки данных из YCLIENTS.</div>
        )}
        <div className="space-y-2">
          {staff.map((s) => {
            const b = byId.get(s.id);
            return (
              <div key={s.id} className="flex flex-wrap items-center gap-3 text-sm">
                <label className="flex items-center gap-2 w-56">
                  <input type="checkbox" checked={!!b} onChange={() => toggle(s)} />
                  {s.name}
                </label>
                {b && (
                  <>
                    <label>
                      Услуги %{" "}
                      <input
                        type="number" min={0} max={100} className={FIELD + " w-20"}
                        value={Math.round(b.service_rate * 100)}
                        onChange={(e) => patch(s.id, { service_rate: Number(e.target.value) / 100 })}
                      />
                    </label>
                    <label>
                      Товары %{" "}
                      <input
                        type="number" min={0} max={100} className={FIELD + " w-20"}
                        value={Math.round(b.product_rate * 100)}
                        onChange={(e) => patch(s.id, { product_rate: Number(e.target.value) / 100 })}
                      />
                    </label>
                    <label>
                      Гарантия ₽/смена{" "}
                      <input
                        type="number" min={0} className={FIELD + " w-24"}
                        value={b.guarantee}
                        onChange={(e) => patch(s.id, { guarantee: Number(e.target.value) })}
                      />
                    </label>
                  </>
                )}
              </div>
            );
          })}
        </div>
        <button
          className={BTN + " mt-3"}
          disabled={busy || staff.length === 0}
          onClick={() => post("/api/settings/barbers", { barbers }, "Барберы сохранены")}
        >
          Сохранить барберов
        </button>
      </div>
    </section>
  );
}
