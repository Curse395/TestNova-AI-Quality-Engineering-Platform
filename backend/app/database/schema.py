from sqlalchemy import Engine, inspect, text


def ensure_test_case_generation_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("test_cases") or not inspector.has_table(
        "test_case_generation_runs"
    ):
        return

    column_names = {
        column["name"] for column in inspector.get_columns("test_cases")
    }
    with engine.begin() as connection:
        if "generation_run_id" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE test_cases "
                    "ADD COLUMN generation_run_id INTEGER "
                    "REFERENCES test_case_generation_runs (id)"
                )
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_test_cases_generation_run_id "
                "ON test_cases (generation_run_id)"
            )
        )
