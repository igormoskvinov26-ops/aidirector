"""Application configuration loaded from environment variables.

Секретов со значениями по умолчанию здесь нет и не будет: пустое значение
означает «не настроено», а не «возьмём общеизвестный пароль».

Пустое значение больше не роняет запуск. Раньше отсутствие любого
обязательного ключа означало, что приложение не поднимается вообще, и
единственным способом это исправить было открыть .env на сервере. Теперь
недостающее показывается в разделе «Настройки → Интеграции» и заполняется
оттуда; проверки на слабый пароль остались и применяются к заполненным
значениям. Что именно считается обязательным и как это показать человеку —
в app/services/configuration.py, здесь только чтение окружения.
"""

import hashlib
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

def _ключи_файла(путь: Path) -> dict[str, str]:
    """Имена и значения из .env, без выполнения файла. Пусто, если файла нет."""
    найдено: dict[str, str] = {}
    try:
        текст = путь.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return найдено
    for строка in текст.splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("#") or "=" not in строка:
            continue
        имя, _, значение = строка.partition("=")
        значение = значение.strip()
        if len(значение) >= 2 and значение[0] == значение[-1] and значение[0] in "\"'":
            значение = значение[1:-1]
        найдено[имя.strip().upper()] = значение
    return найдено


_ФАЙЛ_ENV = _ключи_файла(PROJECT_ROOT / ".env")

# Какие ключи задала инфраструктура, а какие просто лежат в .env.
#
# Различие не формальное: заданное инфраструктурой (docker-compose, systemd,
# панель хостинга) веб-интерфейс перекрыть не может — при следующем
# перезапуске вернётся значение инфраструктуры, а человек будет смотреть на
# настройку, которая «не применяется». Такие ключи показываются только для
# чтения.
#
# Одного os.environ для этого мало. docker-compose передаёт весь .env внутрь
# контейнера настоящими переменными окружения (env_file), то есть там в
# os.environ лежит ровно то же, что в файле. Поэтому ключ считается заданным
# инфраструктурой, только если файл его не объясняет: либо не упоминает
# вовсе, либо задаёт другое значение.
#
# Снимок делается один раз при импорте, до того как что-либо успевает
# дописать в os.environ.
ИЗ_ОКРУЖЕНИЯ_ПРОЦЕССА: frozenset[str] = frozenset(
    имя
    for имя, значение in os.environ.items()
    if _ФАЙЛ_ENV.get(имя.upper()) != значение
)

# Заведомо слабые и ранее скомпрометированные пароли.
# Хранятся хешами: сами значения публиковались в открытом репозитории,
# и повторять их здесь открытым текстом незачем.
WEAK_PASSWORD_HASHES = {
    "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",  # generic
    "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",  # generic
    "24b115d24370d48be27c8758664c3dbae9eab1b248db4650e71b16f0e08d3866",  # сожжён 09.2026
    "f08a6995b79dcb5752655c2375694ce9e1e8116c6be9cfcfceedf535ef86d251",  # сожжён 09.2026
    "057ba03d6c44104863dc7361fe4578965d1887360f90a0895882e58a6248fc86",  # generic
}


# Минимальная длина пароля любой учётной записи. Решение владельца 04.10.2026:
# 6 знаков (было 12). Заведомо слабые пароли по-прежнему отвергаются.
MIN_PASSWORD = 6


def _is_known_weak(value: str) -> bool:
    """True, если пароль пустой или входит в список известных слабых."""
    normalized = value.strip().lower()
    if not normalized:
        return True
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return digest in WEAK_PASSWORD_HASHES


class Settings(BaseSettings):
    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # -- YCLIENTS --
    # Пусто = не настроено. Приложение поднимается и показывает мастер
    # настройки; выгрузка при этом не идёт и честно об этом сообщает.
    yclients_partner_token: str = ""
    yclients_company_id: int = 0
    yclients_user_token: str = ""

    # -- Общий сервер расчётных показателей (hub). Адрес зашит по умолчанию
    # (не секрет) — новый Пульт уже знает, куда подключаться. Ключ секретный,
    # в код не зашивается: его вводят один раз в «Настройки → Интеграции →
    # Общий сервер», либо установщик берёт его из отдельного файла hub-token.txt.
    hub_url: str = "https://igor-moskvinov.fvds.ru"
    hub_token: str = ""
    yclients_old_company_id: int = 0
    yclients_old_user_token: str = ""

    # -- PostgreSQL --
    # Пароль базы остаётся в .env и через веб не настраивается: управляемые
    # настройки лежат в самой базе, и менять через них доступ к базе — значит
    # пилить сук, на котором сидишь. Файл .env создают local/start.sh и
    # bootstrap.ps1, пароль они генерируют сами.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rubl_director"
    postgres_user: str = "rubl"
    postgres_password: str = ""

    # -- FastAPI --
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    debug: bool = False

    # Comma-separated list of allowed browser origins.
    cors_origins: str = ""


    # -- Sync --
    sync_interval_minutes: int = 60
    # How far back the hourly sync pulls data. Never "everything".
    sync_window_days: int = 90
    # Насколько вперёд. Без этого окно кончалось сегодняшним днём, и раздел
    # предстоящих записей был пуст по построению: в базе их просто не было.
    # Значение согласовано с MAX_DAYS_AHEAD в app/services/bookings.py —
    # смотреть дальше горизонта, который умеет показывать интерфейс, незачем.
    sync_window_ahead_days: int = 60
    # Предел на один прогон. Без него зависший ответ YCLIENTS останавливал
    # обновление насовсем: флаг «идёт выгрузка» не снимался, и все следующие
    # запуски по расписанию тихо пропускались как «уже идёт».
    sync_timeout_minutes: int = 30

    # -- Cache --
    cache_ttl_seconds: int = 300

    # -- Доступ (обязательно, без значений по умолчанию) --
    # Две учётные записи с разным объёмом прав:
    #   owner    — видит всё;
    #   operator — только база обзвона, /api/client-base/*.
    # Разделение не косметическое: на странице обзвона лежат имена и телефоны
    # клиентов, и объём доступа к ним должен быть минимально необходимым.
    #
    # Пусто = учётная запись не заведена. При пустом владельце приложение
    # переходит в режим первичной настройки: открыт только мастер, всё
    # остальное отвечает «требуется настройка». Пароль, заданный через мастер,
    # хранится в базе хешем — см. app/services/credentials.py.
    owner_login: str = ""
    owner_password: str = ""
    operator_login: str = ""
    operator_password: str = ""

    # Учётные записи мастеров: каждый видит только свою зарплату. Задаются
    # списком в .env, потому что состав команды меняется чаще, чем код.
    # Формат: [{"login": "ksenia", "password": "...", "staff_id": 5659614}]
    master_accounts: list[dict] = []

    # Барберы и условия их оплаты. Управляющий сюда не входит: он на окладе,
    # и в статистике мастеров ему делать нечего.
    #
    # Идентификаторы подтверждены владельцем 17.09.2026: Ксения 5659614,
    # Арташ 5659611, Дмитрий 5659617, филиал 2036703. До этого они лежали
    # здесь без подтверждения, перенесённые из прежней версии. Ошибка в
    # одном числе означает, что мастер видит чужую зарплату, поэтому менять
    # их можно только по ответу YCLIENTS или по слову владельца.
    barber_payroll_rules: list[dict] = [
        {"staff_id": 5659614, "name": "Ксения", "service_rate": 0.4,
         "product_rate": 0.1, "guarantee": 4000},
        {"staff_id": 5659611, "name": "Арташ", "service_rate": 0.4,
         "product_rate": 0.1, "guarantee": 4000},
        {"staff_id": 5659617, "name": "Дмитрий", "service_rate": 0.4,
         "product_rate": 0.1, "guarantee": 4000},
    ]

    # -- Telegram --
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # -- Filesystem --
    output_dir: Path = Field(default=PROJECT_ROOT / "output")
    fonts_dir: Path = Field(default=PROJECT_ROOT / "assets" / "fonts")

    # Часовой пояс заведения (IANA). Читается при запуске, из .env: TIMEZONE=Asia/Yekaterinburg
    timezone: str = "Europe/Moscow"

    # -- Business hours (fallback when YCLIENTS schedule is unavailable) --
    work_open_hour: int = 10
    work_close_hour: int = 22
    slot_step_minutes: int = 30

    @field_validator("owner_password", "operator_password")
    @classmethod
    def _reject_weak_access_password(cls, v: str, info) -> str:
        """Пустое — «не заведено», это разрешено. Заполненное — по всей строгости.

        Послабление касается только отсутствия значения. Заведомо слабый или
        короткий пароль отвергается ровно как раньше: иначе достаточно было бы
        стереть строку в .env и вписать «12345678», чтобы обойти проверку.
        """
        if not v:
            return v
        env_name = info.field_name.upper()
        if _is_known_weak(v):
            raise ValueError(
                f"{env_name} is a known weak/default value. "
                "Set a unique password in .env before starting."
            )
        if len(v) < MIN_PASSWORD:
            raise ValueError(f"{env_name} must be at least {MIN_PASSWORD} characters long.")
        return v

    @field_validator("postgres_password")
    @classmethod
    def _reject_weak_db_password(cls, v: str) -> str:
        if v and _is_known_weak(v):
            raise ValueError(
                "POSTGRES_PASSWORD is a known weak/default value. Set a unique password in .env."
            )
        return v

    @field_validator("master_accounts")
    @classmethod
    def _check_master_accounts(cls, v: list[dict]) -> list[dict]:
        """Учётная запись мастера бесполезна и опасна без привязки к человеку.

        Без staff_id роль не знает, чью зарплату показывать, и показала бы
        либо ничью, либо всех. Пароли проверяются на длину так же, как у
        остальных: это доступ к деньгам, пусть и к своим.
        """
        seen_logins: set[str] = set()
        seen_staff: set[int] = set()
        for account in v:
            login = str(account.get("login", "")).strip()
            password = str(account.get("password", ""))
            staff_id = account.get("staff_id")
            if not login:
                raise ValueError("MASTER_ACCOUNTS: у записи нет логина")
            if login in seen_logins:
                raise ValueError(f"MASTER_ACCOUNTS: логин {login} повторяется")
            if not isinstance(staff_id, int) or staff_id <= 0:
                raise ValueError(f"MASTER_ACCOUNTS: у {login} нет staff_id")
            if staff_id in seen_staff:
                raise ValueError(f"MASTER_ACCOUNTS: staff_id {staff_id} повторяется")
            if _is_known_weak(password) or len(password) < MIN_PASSWORD:
                raise ValueError(
                    f"MASTER_ACCOUNTS: пароль {login} слабый или короче {MIN_PASSWORD} символов"
                )
            seen_logins.add(login)
            seen_staff.add(staff_id)
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def stories_dir(self) -> Path:
        return self.output_dir / "stories"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
