from __future__ import annotations

import os
import subprocess
import sys

import psycopg
from psycopg import sql


def main() -> None:
    admin_url = os.environ["DATABASE_ADMIN_URL"]
    app_user = os.environ["DATABASE_APP_USER"]
    app_password = os.environ["DATABASE_APP_PASSWORD"]
    app_url = os.environ["DATABASE_URL"]
    if not app_user.replace("_", "").isalnum():
        raise ValueError("DATABASE_APP_USER must contain only letters, digits, or underscores.")
    if len(app_password) < 16:
        raise ValueError("DATABASE_APP_PASSWORD must be at least 16 characters.")

    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
            role_exists = cursor.fetchone() is not None
            role_statement = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(app_user),
                sql.Literal(app_password),
            )
            if not role_exists:
                role_statement = sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(app_user),
                    sql.Literal(app_password),
                )
            cursor.execute(role_statement)
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(connection.info.dbname),
                    sql.Identifier(app_user),
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                    sql.Identifier(app_user)
                )
            )

    environment = {**os.environ, "DATABASE_URL": app_url}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "backend/alembic.ini",
            "upgrade",
            "head",
        ],
        check=True,
        env=environment,
    )


if __name__ == "__main__":
    main()
