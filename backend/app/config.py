"""Application configuration loaded from environment variables.

Secrets have NO defaults on purpose: if a value is missing the app refuses to
start instead of silently running with a well-known password.
"""

import hashlib
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

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

    # -- YCLIENTS (required) --
    yclients_partner_token: str
    yclients_company_id: int
    yclients_user_token: str
    yclients_old_company_id: int = 0
    yclients_old_user_token: str = ""

    # -- PostgreSQL (password required) --
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rubl_director"
    postgres_user: str = "rubl"
    postgres_password: str

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

    # -- Cache --
    cache_ttl_seconds: int = 300

    # -- Доступ (обязательно, без значений по умолчанию) --
    # Две учётные записи с разным объёмом прав:
    #   owner    — видит всё;
    #   operator — только база обзвона, /api/client-base/*.
    # Разделение не косметическое: на странице обзвона лежат имена и телефоны
    # клиентов, и объём доступа к ним должен быть минимально необходимым.
    owner_login: str
    owner_password: str
    operator_login: str
    operator_password: str

    # -- Telegram --
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # -- Filesystem --
    output_dir: Path = Field(default=PROJECT_ROOT / "output")
    fonts_dir: Path = Field(default=PROJECT_ROOT / "assets" / "fonts")

    # -- Business hours (fallback when YCLIENTS schedule is unavailable) --
    work_open_hour: int = 10
    work_close_hour: int = 22
    slot_step_minutes: int = 30

    @field_validator("owner_password", "operator_password")
    @classmethod
    def _reject_weak_access_password(cls, v: str, info) -> str:
        env_name = info.field_name.upper()
        if _is_known_weak(v):
            raise ValueError(
                f"{env_name} is a known weak/default value. "
                "Set a unique password in .env before starting."
            )
        if len(v) < 12:
            raise ValueError(f"{env_name} must be at least 12 characters long.")
        return v

    @field_validator("postgres_password")
    @classmethod
    def _reject_weak_db_password(cls, v: str) -> str:
        if _is_known_weak(v):
            raise ValueError(
                "POSTGRES_PASSWORD is a known weak/default value. Set a unique password in .env."
            )
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
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
