import { useState } from "react";
import { ArrowRight, CheckCircle2, KeyRound, Loader2, ShieldCheck } from "lucide-react";
import logo from "./assets/logo.png";

/** Первый запуск: учётной записи ещё нет, значит нет и пароля, которым
 *  закрыть эту страницу. Вместо пароля — короткий код, напечатанный в окне
 *  установки и в файле output/код-настройки.txt рядом с программой.
 *
 *  Мастер делает ровно два шага и на этом заканчивается: заводит владельца и
 *  принимает ключи. Всё остальное настраивается потом, в разделе
 *  «Настройки → Интеграции», — ставить человека перед десятью полями в тот
 *  момент, когда он ещё не видел программу, незачем.
 */
export default function SetupWizard({ приГотовности }: { приГотовности: () => void }) {
  const [шаг, setШаг] = useState<"код" | "владелец" | "ключи">("код");
  const [код, setКод] = useState("");
  const [логин, setЛогин] = useState("");
  const [пароль, setПароль] = useState("");
  const [повтор, setПовтор] = useState("");
  const [занято, setЗанято] = useState(false);
  const [ошибка, setОшибка] = useState<string | null>(null);

  async function проверитьКод() {
    setЗанято(true);
    setОшибка(null);
    try {
      const ответ = await fetch("/api/setup/check-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: код }),
      });
      if (!ответ.ok) {
        setОшибка("Код не подошёл. Он напечатан в окне установки.");
        return;
      }
      setШаг("владелец");
    } catch {
      setОшибка("Сервер не отвечает");
    } finally {
      setЗанято(false);
    }
  }

  async function завестиВладельца() {
    if (пароль !== повтор) {
      setОшибка("Пароли не совпадают");
      return;
    }
    setЗанято(true);
    setОшибка(null);
    try {
      const ответ = await fetch("/api/setup/owner", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Setup-Code": код },
        body: JSON.stringify({ login: логин, password: пароль, code: код }),
      });
      if (!ответ.ok) {
        const тело = await ответ.json().catch(() => ({}));
        setОшибка(тело.detail || "Не удалось завести учётную запись");
        return;
      }
      setШаг("ключи");
    } catch {
      setОшибка("Сервер не отвечает");
    } finally {
      setЗанято(false);
    }
  }

  return (
    <div className="min-h-screen bg-milk dark:bg-ink text-ink-soft dark:text-cream flex items-center justify-center p-6">
      <div className="w-full max-w-lg">
        <div className="flex items-center gap-3 mb-8">
          <img src={logo} alt="РублЪ" className="h-14 w-auto object-contain" />
          <div>
            <div className="text-lg font-bold leading-none">
              Рубл<span className="text-bronze dark:text-gold">Ъ</span>
            </div>
            <div className="text-xs text-muted-light dark:text-muted mt-1">
              Настройка AI Director
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-milk-line dark:border-line/50 bg-milk-card dark:bg-panel/60 p-7">
          {шаг === "код" && (
            <>
              <h1 className="text-xl font-semibold">Директор ещё не настроен</h1>
              <p className="text-sm text-muted-light dark:text-muted mt-2">
                Чтобы настроить его мог только тот, кто ставил программу,
                введите код из окна установки. Он же лежит в файле{" "}
                <code className="text-ink-soft dark:text-cream">
                  output/код-настройки.txt
                </code>{" "}
                рядом с программой.
              </p>

              <input
                autoFocus
                className="mt-5 w-full px-4 py-3 rounded-xl bg-milk dark:bg-ink border border-milk-line dark:border-line/50 text-center text-2xl font-mono tracking-[0.3em] uppercase focus:outline-none focus:border-bronze dark:focus:border-gold"
                maxLength={6}
                placeholder="——————"
                value={код}
                onChange={(e) => setКод(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void проверитьКод()}
              />

              {ошибка && (
                <div className="mt-3 text-sm text-red-600 dark:text-red-400">{ошибка}</div>
              )}

              <button
                className="mt-5 w-full inline-flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-bronze dark:bg-gold text-milk dark:text-ink font-medium disabled:opacity-40"
                disabled={занято || код.trim().length < 6}
                onClick={() => void проверитьКод()}
              >
                {занято ? <Loader2 size={16} className="animate-spin" /> : <KeyRound size={16} />}
                Продолжить
              </button>
            </>
          )}

          {шаг === "владелец" && (
            <>
              <h1 className="text-xl font-semibold">Придумайте вход для себя</h1>
              <p className="text-sm text-muted-light dark:text-muted mt-2">
                Это учётная запись владельца — ей видны все разделы. Пароль
                хранится в зашифрованном виде и нигде не показывается, включая
                эту страницу. Записать его стоит прямо сейчас.
              </p>

              <div className="mt-5 space-y-4">
                <div>
                  <label className="block text-sm mb-1.5">Логин</label>
                  <input
                    autoFocus
                    autoComplete="username"
                    className="w-full px-3 py-2.5 rounded-lg bg-milk dark:bg-ink border border-milk-line dark:border-line/50 focus:outline-none focus:border-bronze dark:focus:border-gold"
                    value={логин}
                    onChange={(e) => setЛогин(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm mb-1.5">
                    Пароль{" "}
                    <span className="text-muted-light dark:text-muted">
                      · не короче 12 символов
                    </span>
                  </label>
                  <input
                    type="password"
                    autoComplete="new-password"
                    className="w-full px-3 py-2.5 rounded-lg bg-milk dark:bg-ink border border-milk-line dark:border-line/50 focus:outline-none focus:border-bronze dark:focus:border-gold"
                    value={пароль}
                    onChange={(e) => setПароль(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm mb-1.5">Пароль ещё раз</label>
                  <input
                    type="password"
                    autoComplete="new-password"
                    className="w-full px-3 py-2.5 rounded-lg bg-milk dark:bg-ink border border-milk-line dark:border-line/50 focus:outline-none focus:border-bronze dark:focus:border-gold"
                    value={повтор}
                    onChange={(e) => setПовтор(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && void завестиВладельца()}
                  />
                </div>
              </div>

              {ошибка && (
                <div className="mt-3 text-sm text-red-600 dark:text-red-400">{ошибка}</div>
              )}

              <button
                className="mt-5 w-full inline-flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-bronze dark:bg-gold text-milk dark:text-ink font-medium disabled:opacity-40"
                disabled={занято || пароль.length < 12 || !логин.trim()}
                onClick={() => void завестиВладельца()}
              >
                {занято ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <ShieldCheck size={16} />
                )}
                Создать учётную запись
              </button>
            </>
          )}

          {шаг === "ключи" && (
            <>
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={18} />
                <span className="text-sm">Учётная запись создана</span>
              </div>
              <h1 className="text-xl font-semibold mt-3">Осталось подключить YCLIENTS</h1>
              <p className="text-sm text-muted-light dark:text-muted mt-2">
                Дальше Директор попросит войти под только что созданным логином.
                Ключи можно загрузить готовым файлом <code>.env</code> или
                вписать руками — то и другое в разделе «Настройки → Интеграции».
              </p>
              <p className="text-sm text-muted-light dark:text-muted mt-3">
                Без ключей программа работает, просто показывать ей пока нечего.
              </p>

              <button
                className="mt-6 w-full inline-flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-bronze dark:bg-gold text-milk dark:text-ink font-medium"
                onClick={приГотовности}
              >
                <ArrowRight size={16} />
                Перейти в Директора
              </button>
            </>
          )}
        </div>

        <p className="text-xs text-muted-light dark:text-muted mt-5 text-center">
          Код действует до тех пор, пока не заведена учётная запись владельца.
        </p>
      </div>
    </div>
  );
}
