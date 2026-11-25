/** Переход «к клиенту в базе» из журнала обзвона (запрос владельца 30.10.2026).
 *  Отдельный модуль, чтобы журнал и база не импортировали друг друга. */
let ждёт: number | null = null;

export const СОБЫТИЕ = "rubl:open-client";

export function открытьВБазе(clientId: number) {
  ждёт = clientId;
  window.dispatchEvent(new CustomEvent(СОБЫТИЕ, { detail: clientId }));
}

/** Забрать клиента, к которому просили перейти (один раз). */
export function забратьФокус(): number | null {
  const id = ждёт;
  ждёт = null;
  return id;
}
