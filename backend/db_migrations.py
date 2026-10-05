from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

if __package__:
    from .storage import metadata
else:
    from storage import metadata

BACKEND_DIR = Path(__file__).resolve().parent
INITIAL_TABLES = {"calibration", "screening", "decisions"}


def _matches_metadata(engine, table_name: str) -> bool:
    table = metadata.tables[table_name]
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    primary_key = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
    required_columns = set(table.columns.keys())
    return required_columns <= columns and primary_key == ["id"]


def _stamp_known_schema(config: Config, database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        if "alembic_version" in existing_tables or not existing_tables:
            return

        scripts = ScriptDirectory.from_config(config)
        base_revision = scripts.get_base()
        current_revision = scripts.get_current_head()
        if (
            INITIAL_TABLES <= existing_tables
            and all(_matches_metadata(engine, name) for name in INITIAL_TABLES)
        ):
            if "screening_runs" in existing_tables:
                if not _matches_metadata(engine, "screening_runs"):
                    raise RuntimeError(
                        "Unversioned screening_runs table does not match the known schema."
                    )
                command.stamp(config, current_revision)
            else:
                command.stamp(config, base_revision)
            return
        raise RuntimeError(
            "Database has unversioned tables that do not match a known application "
            f"schema (tables found: {', '.join(sorted(existing_tables))}); "
            "refusing to guess a migration baseline."
        )
    finally:
        engine.dispose()


def upgrade_database(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["database_url"] = database_url
    _stamp_known_schema(config, database_url)
    command.upgrade(config, "head")
