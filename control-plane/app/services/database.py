"""Database provisioning service."""
import logging
import secrets
import string
from typing import Optional

from app.config import settings
from app.models import DatabaseEngine

log = logging.getLogger(__name__)

POSTGRES_HOST = "db-pg"
POSTGRES_PORT = 5432
MYSQL_HOST = "db-mysql"
MYSQL_PORT = 3306

# Superuser credentials (loaded from env)
PG_ADMIN_DSN = settings.database_url  # reuse control-plane db host for simplicity


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _pg_connection():
    import psycopg2
    import re
    # Parse DSN from settings to get superuser credentials
    dsn = settings.database_url
    return psycopg2.connect(dsn)


def create_postgres_db(db_name: str, db_user: str, password: str) -> None:
    """Create a PostgreSQL database and user."""
    if settings.dev_mode:
        log.info("[DEV] Would create postgres db=%s user=%s", db_name, db_user)
        return

    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = _pg_connection()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    try:
        # Create user
        cur.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (db_user,)
        )
        if not cur.fetchone():
            cur.execute(
                f"CREATE USER {psycopg2.extensions.quote_ident(db_user, cur)} WITH PASSWORD %s",
                (password,),
            )
        # Create database owned by user
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        )
        if not cur.fetchone():
            cur.execute(
                f"CREATE DATABASE {psycopg2.extensions.quote_ident(db_name, cur)} "
                f"OWNER {psycopg2.extensions.quote_ident(db_user, cur)}"
            )
        log.info("Created postgres db=%s user=%s", db_name, db_user)
    finally:
        cur.close()
        conn.close()


def drop_postgres_db(db_name: str, db_user: str) -> None:
    """Drop a PostgreSQL database and user."""
    if settings.dev_mode:
        log.info("[DEV] Would drop postgres db=%s user=%s", db_name, db_user)
        return

    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = _pg_connection()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    try:
        cur.execute(
            f"DROP DATABASE IF EXISTS {psycopg2.extensions.quote_ident(db_name, cur)}"
        )
        cur.execute(
            f"DROP ROLE IF EXISTS {psycopg2.extensions.quote_ident(db_user, cur)}"
        )
        log.info("Dropped postgres db=%s user=%s", db_name, db_user)
    finally:
        cur.close()
        conn.close()


def provision_database(
    site_name: str,
    engine: DatabaseEngine = DatabaseEngine.postgres,
) -> tuple[str, str, str, str, int]:
    """
    Create a database for the given site.
    Returns (db_name, db_user, password, host, port).
    """
    db_name = f"site_{site_name.replace('-', '_')}"
    db_user = f"user_{site_name.replace('-', '_')}"
    password = _random_password()

    if engine == DatabaseEngine.postgres:
        create_postgres_db(db_name, db_user, password)
        return db_name, db_user, password, POSTGRES_HOST, POSTGRES_PORT

    raise NotImplementedError(f"Engine {engine} not yet implemented")


def deprovision_database(
    db_name: str,
    db_user: str,
    engine: DatabaseEngine = DatabaseEngine.postgres,
) -> None:
    if engine == DatabaseEngine.postgres:
        drop_postgres_db(db_name, db_user)
    else:
        raise NotImplementedError(f"Engine {engine} not yet implemented")
