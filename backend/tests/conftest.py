import pytest
"""Test environment: dummy credentials so config validation passes offline."""

import os

os.environ.setdefault("YCLIENTS_PARTNER_TOKEN", "test-partner-token")
os.environ.setdefault("YCLIENTS_COMPANY_ID", "1")
os.environ.setdefault("YCLIENTS_USER_TOKEN", "test-user-token")
os.environ.setdefault("POSTGRES_PASSWORD", "test-db-password-not-weak")
os.environ.setdefault("OWNER_LOGIN", "tester")
os.environ.setdefault("OWNER_PASSWORD", "test-owner-password")
os.environ.setdefault("OPERATOR_LOGIN", "tester-operator")
os.environ.setdefault("OPERATOR_PASSWORD", "test-operator-password")
# Одна учётная запись мастера: без неё проверки прав для роли «мастер»
# пропускались бы, а это та роль, которой видно меньше всех.
os.environ.setdefault(
    "MASTER_ACCOUNTS",
    '[{"login":"test-master","password":"test-master-password","staff_id":5659614}]',
)


@pytest.fixture(autouse=True)
def _salon_state_restored():
    """Настройки заведения глобальные: тест не должен оставлять их другому."""
    from app.config import settings
    from app.services import salon

    before = (list(settings.barber_payroll_rules), salon.name, salon.booking_url)
    yield
    settings.barber_payroll_rules, salon.name, salon.booking_url = before


@pytest.fixture(autouse=True)
def _branch_flags_restored():
    from app.services import configuration, salon

    before = (configuration.изолирован, salon.главная)
    yield
    configuration.изолирован, salon.главная = before
