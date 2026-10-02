"""Конфигурация обязана отказываться стартовать со слабым паролем.

Сами скомпрометированные значения в тестах не приводятся: они лежали в
публичном репозитории, и повторять их в коде незачем. Проверяется механизм —
пароль, чей sha256 попал в чёрный список, должен отвергаться.
"""

import hashlib

import pytest
from pydantic import ValidationError

from app.config import WEAK_PASSWORD_HASHES, Settings, _is_known_weak

BASE = {
    "yclients_partner_token": "x",
    "yclients_company_id": 1,
    "yclients_user_token": "x",
    "postgres_password": "a-strong-db-password",
    "owner_login": "igor",
    "owner_password": "a-strong-owner-password",
    "operator_login": "admin",
    "operator_password": "a-strong-operator-password",
}


@pytest.fixture
def blacklisted_password(monkeypatch) -> str:
    """Пароль, добавленный в чёрный список на время теста."""
    value = "a-password-that-was-burned"
    digest = hashlib.sha256(value.encode()).hexdigest()
    monkeypatch.setattr(
        "app.config.WEAK_PASSWORD_HASHES", WEAK_PASSWORD_HASHES | {digest}
    )
    return value


@pytest.mark.parametrize("field", ["owner_password", "operator_password"])
def test_rejects_blacklisted_access_password(blacklisted_password, field):
    with pytest.raises(ValidationError):
        Settings(**{**BASE, field: blacklisted_password}, _env_file=None)


def test_rejects_blacklisted_db_password(blacklisted_password):
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "postgres_password": blacklisted_password}, _env_file=None)


@pytest.mark.parametrize("field", ["owner_password", "operator_password"])
def test_rejects_short_access_password(field):
    with pytest.raises(ValidationError):
        Settings(**{**BASE, field: "short"}, _env_file=None)


def test_missing_account_does_not_crash_startup(monkeypatch):
    """Незаполненная учётная запись больше не роняет запуск, но и не работает.

    Раньше отсутствие любого обязательного ключа означало, что приложение не
    поднимается вообще; починить это можно было только через .env на сервере.
    Теперь недостающее показывается в разделе «Настройки → Интеграции», а
    пустая пара логин-пароль не пускает никого: пустой логин с пустым
    паролем совпал бы сам с собой.

    Переменные окружения убираются явно: conftest выставляет их для всех
    остальных тестов, и без этого Settings подхватил бы их в обход аргументов.
    """
    monkeypatch.delenv("OPERATOR_LOGIN", raising=False)
    monkeypatch.delenv("OPERATOR_PASSWORD", raising=False)
    without_operator = {k: v for k, v in BASE.items() if not k.startswith("operator_")}

    конфиг = Settings(**without_operator, _env_file=None)
    assert конфиг.operator_login == ""
    assert конфиг.operator_password == ""


def test_empty_credentials_let_nobody_in(monkeypatch):
    """Пустой логин и пустой пароль не должны совпадать друг с другом.

    Проверка не теоретическая: secrets.compare_digest("", "") возвращает
    истину, и без отдельной проверки на заполненность незаведённая учётная
    запись администратора пускала бы любого, кто оставит оба поля пустыми.
    """
    from app.config import settings as живые
    from app.main import _resolve_identity

    monkeypatch.setattr(живые, "operator_login", "")
    monkeypatch.setattr(живые, "operator_password", "")
    monkeypatch.setattr(живые, "owner_login", "")
    monkeypatch.setattr(живые, "owner_password", "")
    monkeypatch.setattr(живые, "master_accounts", [])

    assert _resolve_identity("", "") is None


def test_rejects_empty_password():
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "postgres_password": "   "}, _env_file=None)


def test_blacklist_is_case_insensitive(blacklisted_password):
    assert _is_known_weak(blacklisted_password.upper())


def test_known_weak_list_is_not_empty():
    """Защита от случайной очистки списка при рефакторинге."""
    assert len(WEAK_PASSWORD_HASHES) >= 5


def test_cors_origins_parse_into_a_list():
    s = Settings(**BASE, cors_origins="https://a.ru, https://b.ru", _env_file=None)
    assert s.cors_origin_list == ["https://a.ru", "https://b.ru"]


def test_cors_defaults_to_empty_not_wildcard():
    assert Settings(**BASE, _env_file=None).cors_origin_list == []
