import time
from logging.config import fileConfig

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import context
from app.config import settings
from app.models.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Миграции запускаются дважды почти одновременно: контейнер делает
# «alembic upgrade head» при каждом старте (local/Dockerfile), и сразу после
# этого bootstrap.ps1 выполняет то же самое через docker exec. Без общей
# блокировки второй запуск мог прочитать старую ревизию и упасть на записи
# новой. Рекомендательная блокировка выстраивает их в очередь: второй
# дождётся первого и увидит, что делать уже нечего.
БЛОКИРОВКА_МИГРАЦИЙ = 7310_2026

# Пока идёт выгрузка из YCLIENTS, ALTER TABLE ждёт её. Ждём ограниченно и
# повторяем, а не висим без конца и не падаем от первой же взаимной
# блокировки. Коды PostgreSQL: deadlock_detected, lock_not_available.
ПОПЫТОК = 5
ЖДАТЬ_БЛОКИРОВКУ = "20s"
ПОВТОРЯЕМЫЕ = {"40P01", "55P03"}

# Ревизии сборок 9.17.4–9.17.13 (ветка, по ошибке собранная мимо 9.25).
# 9.17.13 могла успеть записать в базу свою ревизию слияния — она стоит
# поверх 0016 и уже расширила yclients_id, то есть по схеме это 0016 + 0017.
# Переводим метку на ревизию этой линии, чтобы alembic её узнал; 0017
# идемпотентна и на такой базе ничего не изменит.
ЧУЖИЕ_РЕВИЗИИ = {
    "0014_merge_foreign_heads": "0016_status_loyalty_variants",
    "0013_yclients_id_bigint": "0012_client_do_not_call",
}


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _перевести_чужие_ревизии(connection) -> None:
    if "alembic_version" not in inspect(connection).get_table_names():
        return
    было = [r[0] for r in connection.execute(text("SELECT version_num FROM alembic_version"))]
    # Если файл такой ревизии лежит в папке (обновление не удалило старые
    # файлы), alembic её знает сам — переводить не нужно.
    известные = {r.revision for r in context.script.walk_revisions()}
    стало = {r if r in известные else ЧУЖИЕ_РЕВИЗИИ.get(r, r) for r in было}
    if "0016_status_loyalty_variants" in стало:
        стало.discard("0012_client_do_not_call")
    if стало == set(было):
        return
    print(f"Метка базы {было} переведена на {sorted(стало)}", flush=True)
    connection.execute(text("DELETE FROM alembic_version"))
    for ревизия in sorted(стало):
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": ревизия}
        )


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
                # ней; текущая ревизия базы читается уже после — с учётом
                # того, что успел сделать параллельный запуск.
                connection.execute(text(f"SELECT pg_advisory_xact_lock({БЛОКИРОВКА_МИГРАЦИЙ})"))
            _перевести_чужие_ревизии(connection)
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
