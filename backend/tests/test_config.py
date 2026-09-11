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
    "admin_login": "igor",
    "admin_password": "a-strong-admin-password",
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


def test_rejects_blacklisted_admin_password(blacklisted_password):
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "admin_password": blacklisted_password}, _env_file=None)


def test_rejects_blacklisted_db_password(blacklisted_password):
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "postgres_password": blacklisted_password}, _env_file=None)


def test_rejects_short_admin_password():
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "admin_password": "short"}, _env_file=None)


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
