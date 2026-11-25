import time
from logging.config import fileConfig

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from alembic import context
from app.config import settings
from app.models.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Миграцию запускают, пока приложение уже работает: установщик сначала
# поднимает контейнер, потом выполняет в нём alembic upgrade head. В это время
# может идти выгрузка из YCLIENTS, а ALTER TABLE ждёт, пока она отпустит
# таблицу. Чтобы не висеть бесконечно за чужой транзакцией и не падать от
# взаимной блокировки с первого раза, ждём ограниченно и пробуем снова.
ПОПЫТОК = 5
ЖДАТЬ_БЛОКИРОВКУ = "20s"
# Коды PostgreSQL: deadlock_detected, lock_not_available.
ПОВТОРЯЕМЫЕ = {"40P01", "55P03"}
# Номер общей рекомендательной блокировки: два одновременных запуска
# (установщик и повтор, два окна) не должны накатывать одно и то же
# параллельно — второй дождётся первого и увидит, что делать уже нечего.
БЛОКИРОВКА_МИГРАЦИЙ = 7310_2026


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _один_прогон(connectable) -> None:
    with connectable.connect() as connection:
        постгрес = connection.dialect.name == "postgresql"
        if постгрес:
            connection.execute(text(f"SET lock_timeout = '{ЖДАТЬ_БЛОКИРОВКУ}'"))
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            if постгрес:
                # Берётся внутри транзакции миграции и отпускается вместе с
                # ней; текущая ревизия базы читается уже после — то есть
                # с учётом того, что успел сделать параллельный запуск.
                connection.execute(text(f"SELECT pg_advisory_xact_lock({БЛОКИРОВКА_МИГРАЦИЙ})"))
            context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.database_url_sync, pool_pre_ping=True)
    try:
        for попытка in range(1, ПОПЫТОК + 1):
            try:
                _один_прогон(connectable)
                return
            except OperationalError as сбой:
                код = getattr(сбой.orig, "pgcode", None)
                if код not in ПОВТОРЯЕМЫЕ or попытка == ПОПЫТОК:
                    raise
                print(
                    f"Таблица занята работающим приложением (код {код}), "
                    f"повтор {попытка + 1} из {ПОПЫТОК} через 5 секунд",
                    flush=True,
                )
                time.sleep(5)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
