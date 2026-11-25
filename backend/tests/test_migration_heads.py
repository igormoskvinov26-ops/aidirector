"""История миграций сходится в одну голову, даже с чужими файлами в папке.

На машине салона в alembic/versions остались миграции другой сборки
Директора, и «alembic upgrade head» падал с «Multiple head revisions»
(25.11.2026). 0014_merge_foreign_heads сводит все головы в одну.
"""

import shutil
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]


def _головы(tmp_path: Path, чужие: dict[str, str]) -> list[str]:
    копия = tmp_path / "alembic"
    shutil.copytree(BACKEND / "alembic", копия, ignore=shutil.ignore_patterns("__pycache__"))
    for имя, текст in чужие.items():
        (копия / "versions" / имя).write_text(текст, encoding="utf-8")
    config = Config()
    config.set_main_option("script_location", str(копия))
    return ScriptDirectory.from_config(config).get_heads()


def test_без_чужих_файлов_одна_голова(tmp_path):
    assert _головы(tmp_path, {}) == ["0014_merge_foreign_heads"]


def test_чужая_ветка_сводится_в_одну_голову(tmp_path):
    чужие = {
        # Так пишет autogenerate: аннотации типов, хеш вместо номера.
        "0013_fork.py": (
            "from typing import Union\n"
            "revision: str = 'a1b2c3d4e5f6'\n"
            "down_revision: Union[str, None] = '0012_client_do_not_call'\n"
            "def upgrade(): pass\n"
            "def downgrade(): pass\n"
        ),
        "0014_fork.py": (
            "revision = '0014_fork_more'\n"
            "down_revision = 'a1b2c3d4e5f6'\n"
            "def upgrade(): pass\n"
            "def downgrade(): pass\n"
        ),
    }
    assert _головы(tmp_path, чужие) == ["0014_merge_foreign_heads"]


def test_сломанный_чужой_файл_не_мешает_разбору(tmp_path):
    чужие = {"zz_broken.py": "это не питон ((("}
    # Сам alembic такой файл не загрузит — но не из-за нашего слияния:
    # разбор соседей в 0014 ошибки синтаксиса пропускает молча.
    from importlib import util

    путь = BACKEND / "alembic" / "versions" / "0014_merge_foreign_heads.py"
    spec = util.spec_from_file_location("m0014", путь)
    модуль = util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    папка = tmp_path / "v"
    shutil.copytree(
        BACKEND / "alembic" / "versions", папка, ignore=shutil.ignore_patterns("__pycache__")
    )
    (папка / "zz_broken.py").write_text(чужие["zz_broken.py"], encoding="utf-8")
    assert модуль.головы(папка) == ("0013_yclients_id_bigint",)
