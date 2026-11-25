"""Свести в одну все «головы» истории миграций, включая чужие файлы.

Revision ID: 0014_merge_foreign_heads
Revises: 0013_yclients_id_bigint и все прочие головы, найденные в этой папке

Зачем. Пакет обновления копирует файлы поверх app\\ и лишнего не удаляет.
На машине салона в alembic/versions остались миграции другой сборки
Директора — не из этого репозитория. Вместе с нашей 0013 получилось две
головы, и «alembic upgrade head», которым установщик обновляет базу, падал:
«Multiple head revisions are present» (журнал владельца, 25.11.2026).
Удалять чужие файлы нельзя: база, скорее всего, уже стоит на одной из
этих ревизий, и без файла alembic её не найдёт.

Поэтому эта миграция — слияние, а её down_revision вычисляется при загрузке:
все ревизии из соседних файлов, на которые никто не ссылается. Когда чужих
файлов нет, это просто «0013_yclients_id_bigint», и история остаётся прямой.
Когда есть — alembic сначала применяет недостающие ветки (нашу 0013 и
неприменённые чужие), потом сводит их здесь в одну голову.

Схему эта миграция не меняет.
"""

import ast
from pathlib import Path

revision = "0014_merge_foreign_heads"
НАША_ПРЕДЫДУЩАЯ = "0013_yclients_id_bigint"


def _строки(узел: ast.expr | None) -> list[str] | None:
    """Значение revision/down_revision из исходника: строка, None или кортеж."""
    if узел is None:
        return None
    try:
        значение = ast.literal_eval(узел)
    except (ValueError, SyntaxError):
        return None
    if значение is None:
        return []
    if isinstance(значение, str):
        return [значение]
    if isinstance(значение, (tuple, list)) and all(isinstance(v, str) for v in значение):
        return list(значение)
    return None


def _ревизии_папки(папка: Path) -> dict[str, list[str]]:
    """{ревизия: [её down_revision]} по всем файлам папки, кроме этого.

    Файлы разбираются как текст (ast), а не импортируются: загружать чужой
    код ради двух строк незачем, а сломанный файл не должен ронять этот.
    """
    найдено: dict[str, list[str]] = {}
    for файл in sorted(папка.glob("*.py")):
        if файл.name == Path(__file__).name or файл.name.startswith("__"):
            continue
        try:
            дерево = ast.parse(файл.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        поля: dict[str, ast.expr | None] = {}
        for узел in дерево.body:
            if isinstance(узел, ast.Assign):
                for цель in узел.targets:
                    if isinstance(цель, ast.Name):
                        поля[цель.id] = узел.value
            elif isinstance(узел, ast.AnnAssign) and isinstance(узел.target, ast.Name):
                поля[узел.target.id] = узел.value
        rev = _строки(поля.get("revision"))
        if not rev or len(rev) != 1:
            continue
        down = _строки(поля.get("down_revision")) if "down_revision" in поля else []
        найдено[rev[0]] = down or []
    return найдено


def головы(папка: Path) -> tuple[str, ...]:
    """Ревизии, на которые не ссылается ни одна другая. Наша 0013 — всегда первой."""
    ревизии = _ревизии_папки(папка)
    упомянутые = {d for downs in ревизии.values() for d in downs}
    найдено = sorted(r for r in ревизии if r not in упомянутые and r != revision)
    if НАША_ПРЕДЫДУЩАЯ in найдено:
        найдено.remove(НАША_ПРЕДЫДУЩАЯ)
    return (НАША_ПРЕДЫДУЩАЯ, *найдено)


_головы = головы(Path(__file__).resolve().parent)
down_revision: str | tuple[str, ...] = _головы[0] if len(_головы) == 1 else _головы
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
