"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # YCLIENTS
    yclients_partner_token: str
    yclients_company_id: int
    yclients_user_token: str
    yclients_old_company_id: int = 0
    yclients_old_user_token: str = ""

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rubl_director"
    postgres_user: str = "rubl"
    # Без значения по умолчанию: прежнее было опубликовано в открытом
    # репозитории. Пустой POSTGRES_PASSWORD теперь останавливает старт.
    postgres_password: str

    # FastAPI
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    # Sync
    sync_interval_minutes: int = 60

    # Admin
    admin_login: str = "admin"
    # Без значения по умолчанию — по той же причине.
    admin_password: str

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

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
