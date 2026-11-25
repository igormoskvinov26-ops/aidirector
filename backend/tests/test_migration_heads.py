"""У истории миграций ровно одна голова — иначе «alembic upgrade head» падает.

Так и случилось на салоне 25.11.2026: файлы сборок 9.17.x легли рядом с
0013–0016 этой линии, и обновление базы встало с «Multiple head revisions».
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]


def test_одна_голова():
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["0018_client_state_stamps"]


def test_файлы_917_не_попадают_в_образ():
    исключено = (BACKEND.parent / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for имя in ("0013_yclients_id_bigint.py", "0014_merge_foreign_heads.py"):
        assert f"backend/alembic/versions/{имя}" in исключено
