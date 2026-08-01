-- Rubl AI Director — Database Initialization
-- This runs once when PostgreSQL container starts for the first time.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Will be extended with Alembic migrations.
-- Core tables are defined via SQLAlchemy models in backend/app/models/
