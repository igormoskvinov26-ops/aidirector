import { useState } from "react";
import { Check, Copy } from "lucide-react";

/** Копирование работает и там, где нет clipboard API: Пульт, открытый с
 *  другого компьютера по http://192.168…, браузер считает небезопасным. */
async function скопировать(текст: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(текст);
    return true;
  } catch {
    const поле = document.createElement("textarea");
    поле.value = текст;
    поле.style.position = "fixed";
    поле.style.opacity = "0";
    document.body.appendChild(поле);
    поле.select();
    const ок = document.execCommand("copy");
    поле.remove();
    return ок;
  }
}

/** Телефон крупно + значок «копировать» + значок YCLIENTS (карточка клиента в новом окне). */
export function Телефон({ phone, yclientsUrl, крупно = false }: {
  phone: string | null;
  yclientsUrl?: string | null;
  крупно?: boolean;
}) {
  const [готово, setГотово] = useState(false);
  if (!phone) return <span className="text-muted-light dark:text-muted">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className={`tabular-nums ${крупно ? "text-base font-semibold text-ink-soft dark:text-cream" : ""}`}>{phone}</span>
      <button
        type="button"
        title="Скопировать номер"
        aria-label="Скопировать номер"
        onClick={async (e) => {
          e.stopPropagation();
          if (await скопировать(phone)) {
            setГотово(true);
            window.setTimeout(() => setГотово(false), 1200);
          }
        }}
        className="rounded-md p-1 text-muted-light dark:text-muted hover:text-bronze dark:hover:text-gold hover:bg-milk-deep dark:hover:bg-panel-deep"
      >
        {готово ? <Check size={14} className="text-profit" /> : <Copy size={14} />}
      </button>
      {yclientsUrl && (
        <a
          href={yclientsUrl}
          target="_blank"
          rel="noopener noreferrer"
          title="Открыть клиента в YCLIENTS"
          onClick={(e) => e.stopPropagation()}
          className="rounded-md px-1.5 py-0.5 text-[10px] font-bold tracking-wide border border-milk-line dark:border-line text-muted-light dark:text-muted hover:text-bronze dark:hover:text-gold hover:border-bronze dark:hover:border-gold"
        >
          YC
        </a>
      )}
    </span>
  );
}
