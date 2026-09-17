/** Фотографии мастеров. Общее для страниц, где мастера в строках.
 *
 *  Фотографии те же, что на сайте: интерфейс и сайт показывают одних людей, и
 *  снимать их дважды незачем. Кадрированы в квадрат по лицу.
 */

import фотоАрташ from "./assets/masters/artash.webp";
import фотоДмитрий from "./assets/masters/dmitry.webp";
import фотоКсения from "./assets/masters/ksenia.webp";

/** Привязка по staff_id, а не по имени: имя в YCLIENTS можно переписать, и
 *  тогда фотография отвалится молча — причём не заметит этого никто, пока не
 *  окажется, что у Арташа лицо Дмитрия. Идентификаторы подтверждены
 *  владельцем 17.09.2026. */
const ФОТО: Record<number, string> = {
  5659614: фотоКсения,
  5659611: фотоАрташ,
  5659617: фотоДмитрий,
};

const РАЗМЕРЫ = {
  обычный: "size-10",
  крупный: "size-12",
} as const;

/** Кружок с фотографией мастера или с первой буквой имени.
 *
 *  Незнакомому мастеру фотографии нет, и подставлять чужую нельзя. Пустое
 *  место тоже не годится: строка потеряет опору, по которой глаз её находит.
 *  Поэтому буква.
 */
export function Аватар({
  staffId,
  name,
  размер = "обычный",
}: {
  staffId: number;
  name: string;
  размер?: keyof typeof РАЗМЕРЫ;
}) {
  const фото = ФОТО[staffId];
  // Обводка тонкая: она отделяет фотографию от фона, не притязая на внимание.
  // Толще — и кружки начнут спорить с числами, ради которых страница.
  const общее = `${РАЗМЕРЫ[размер]} shrink-0 rounded-full ring-1 ring-bronze/25 dark:ring-gold/25`;

  if (!фото) {
    return (
      <span
        className={`${общее} grid place-items-center bg-milk-deep dark:bg-panel-deep
          text-muted-light dark:text-muted text-sm font-semibold`}
        aria-hidden="true"
      >
        {(name || "?").trim().charAt(0).toUpperCase()}
      </span>
    );
  }

  return <img src={фото} alt="" className={`${общее} object-cover`} />;
}
