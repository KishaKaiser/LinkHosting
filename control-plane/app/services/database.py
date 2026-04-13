"""Database provisioning service."""
import logging
import re
import secrets
import string

from app.config import settings
from app.models import DatabaseEngine

log = logging.getLogger(__name__)

POSTGRES_HOST = "db-pg"
POSTGRES_PORT = 5432
MYSQL_HOST = "db-mysql"
MYSQL_PORT = 3306

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-z0-9_]{1,64}$")


def _validate_identifier(name: str) -> None:
    """Raise ValueError if name is not a safe SQL identifier (alphanumeric + underscore)."""
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe database identifier: {name!r}")


def db_identifiers(site_name: str) -> tuple[str, str]:
    """Return (db_name, db_user) for a site — deterministic, no secrets."""
    safe = site_name.replace("-", "_")
    db_name = f"site_{safe}"
    db_user = f"user_{safe}"
    _validate_identifier(db_name)
    _validate_identifier(db_user)
    return db_name, db_user


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _pg_connection():
    import psycopg2
    return psycopg2.connect(settings.site_pg_dsn)


def _mysql_connection():
    import pymysql
    # Parse the DSN: mysql://user:pass@host:port
    m = re.match(
        r"mysql://(?P<user>[^:]+):(?P<password>[^@]*)@(?P<host>[^:/]+)(?::(?P<port>\d+))?",
        settings.site_mysql_dsn,
    )
    if not m:
        raise ValueError(f"Invalid SITE_MYSQL_DSN: {settings.site_mysql_dsn!r}")
    return pymysql.connect(
        host=m.group("host"),
        port=int(m.group("port") or 3306),
        user=m.group("user"),
        password=m.group("password"),
        autocommit=True,
    )


def create_postgres_db(db_name: str, db_user: str, password: str) -> None:
    """Create a PostgreSQL database and user."""
    if settings.dev_mode:
        log.info("[DEV] Would create postgres db=%s user=%s", db_name, db_user)
        return

    import psycopg2
    from psycopg2 import sql
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
                sql.SQL("CREATE USER {} WITH PASSWORD %s").format(
                    sql.Identifier(db_user)
                ),
                (password,),
            )
        # Create database owned by user
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        )
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(db_name),
                    sql.Identifier(db_user),
                )
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
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = _pg_connection()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    try:
        cur.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
        )
        cur.execute(
            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(db_user))
        )
        log.info("Dropped postgres db=%s user=%s", db_name, db_user)
    finally:
        cur.close()
        conn.close()


def create_mysql_db(db_name: str, db_user: str, password: str) -> None:
    """Create a MySQL/MariaDB database and user."""
    if settings.dev_mode:
        log.info("[DEV] Would create mysql db=%s user=%s", db_name, db_user)
        return

    # _validate_identifier() ensures db_name and db_user contain only
    # [a-z0-9_] characters (no backticks, semicolons or other special chars),
    # making backtick-quoted f-string interpolation safe. MySQL/MariaDB drivers
    # do not support parameterized identifiers, so this is the standard approach.
    _validate_identifier(db_name)
    _validate_identifier(db_user)

    conn = _mysql_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        # Create user if it doesn't exist (compatible with MySQL 5.7+ and MariaDB)
        cur.execute("SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = '%%'", (db_user,))
        if cur.fetchone()[0] == 0:
            cur.execute(f"CREATE USER `{db_user}`@'%%' IDENTIFIED BY %s", (password,))
        cur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{db_user}`@'%'")
        cur.execute("FLUSH PRIVILEGES")
        log.info("Created mysql db=%s user=%s", db_name, db_user)
    finally:
        cur.close()
        conn.close()


def drop_mysql_db(db_name: str, db_user: str) -> None:
    """Drop a MySQL/MariaDB database and user."""
    if settings.dev_mode:
        log.info("[DEV] Would drop mysql db=%s user=%s", db_name, db_user)
        return

    # See create_mysql_db for why backtick-quoted f-strings are used here.
    _validate_identifier(db_name)
    _validate_identifier(db_user)

    conn = _mysql_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        cur.execute(f"DROP USER IF EXISTS `{db_user}`@'%'")
        cur.execute("FLUSH PRIVILEGES")
        log.info("Dropped mysql db=%s user=%s", db_name, db_user)
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
    db_name, db_user = db_identifiers(site_name)
    password = _random_password()

    if engine == DatabaseEngine.postgres:
        create_postgres_db(db_name, db_user, password)
        return db_name, db_user, password, POSTGRES_HOST, POSTGRES_PORT

    if engine == DatabaseEngine.mysql:
        create_mysql_db(db_name, db_user, password)
        return db_name, db_user, password, MYSQL_HOST, MYSQL_PORT

    raise NotImplementedError(f"Engine {engine} not yet implemented")


def deprovision_database(
    db_name: str,
    db_user: str,
    engine: DatabaseEngine = DatabaseEngine.postgres,
) -> None:
    if engine == DatabaseEngine.postgres:
        drop_postgres_db(db_name, db_user)
    elif engine == DatabaseEngine.mysql:
        drop_mysql_db(db_name, db_user)
    else:
        raise NotImplementedError(f"Engine {engine} not yet implemented")

