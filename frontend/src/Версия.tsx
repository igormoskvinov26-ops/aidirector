import { useEffect, useState } from "react";

/** Версия Пульта в правом нижнем углу любого экрана (запрос владельца
 *  29.10.2026): по ней видно, какая сборка запущена на рабочем компьютере.
 *  Берётся у сервера (/health), а не вшивается в интерфейс — так видно и
 *  расхождение, если обновился только сервер. */
export default function Версия() {
  const [v, setV] = useState<string | null>(null);
  useEffect(() => {
    fetch("/health")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setV(d?.version ?? "?"))
      .catch(() => setV("?"));
  }, []);
  if (!v) return null;
  return (
    <div
      title="Версия Пульта на этом компьютере"
      className="pointer-events-none fixed bottom-2 right-3 z-50 rounded-full border border-milk-line dark:border-line bg-milk-card/90 dark:bg-ink/85 px-2.5 py-0.5 text-[11px] tabular-nums text-muted-light dark:text-muted backdrop-blur"
    >
      Пульт v{v}
    </div>
  );
}
