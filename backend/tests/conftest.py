"""Test environment: dummy credentials so config validation passes offline."""

import os

os.environ.setdefault("YCLIENTS_PARTNER_TOKEN", "test-partner-token")
os.environ.setdefault("YCLIENTS_COMPANY_ID", "1")
os.environ.setdefault("YCLIENTS_USER_TOKEN", "test-user-token")
os.environ.setdefault("POSTGRES_PASSWORD", "test-db-password-not-weak")
os.environ.setdefault("ADMIN_LOGIN", "tester")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
