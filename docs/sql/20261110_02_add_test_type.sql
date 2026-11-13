-- Forward-only, additive fallback for environments managed outside Alembic.
-- Inspect the target schema and obtain deployment approval before execution.
-- This file is a reference script; it has not been run against any database.
ALTER TABLE test_cases
    ADD COLUMN IF NOT EXISTS test_type VARCHAR(60);
