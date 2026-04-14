"""Tests for the databases API."""
import bcrypt as _bcrypt
import pytest

from app.utils.hashing import hash_db_password, verify_db_password, pwd_context


def test_hash_db_password_long_password():
    """Passwords longer than 72 bytes must be hashable without error (argon2 has no byte limit)."""
    long_password = "x" * 80  # 80 bytes — bcrypt would raise ValueError here
    hashed = hash_db_password(long_password)
    assert hashed.startswith("$argon2")
    assert verify_db_password(long_password, hashed)


def test_hash_db_password_verify_wrong():
    """Incorrect password must not verify."""
    hashed = hash_db_password("correct")
    assert not verify_db_password("wrong", hashed)


def test_pwd_context_verifies_bcrypt_hash():
    """Existing bcrypt hashes stored in the database must still verify (backward compat)."""
    short_pw = "short_password"
    bcrypt_hash = _bcrypt.hashpw(short_pw.encode(), _bcrypt.gensalt()).decode()
    assert pwd_context.verify(short_pw, bcrypt_hash)



def test_create_database(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})

    resp = client.post(
        "/sites/dbsite/database",
        json={"engine": "postgres"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["db_name"] == "site_dbsite"
    assert data["db_user"] == "user_dbsite"
    assert data["engine"] == "postgres"
    assert data["db_password"] != ""
    assert "postgresql://" in data["dsn"]


def test_create_mysql_database(client):
    client.post("/sites", json={"name": "mysqlsite", "site_type": "python"})

    resp = client.post(
        "/sites/mysqlsite/database",
        json={"engine": "mysql"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["db_name"] == "site_mysqlsite"
    assert data["db_user"] == "user_mysqlsite"
    assert data["engine"] == "mysql"
    assert data["db_password"] != ""
    assert "mysql://" in data["dsn"]
    assert data["port"] == 3306
    assert data["host"] == "db-mysql"


def test_create_database_site_not_found(client):
    resp = client.post("/sites/nonexistent/database", json={"engine": "postgres"})
    assert resp.status_code == 404


def test_create_database_duplicate(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})
    client.post("/sites/dbsite/database", json={"engine": "postgres"})
    resp = client.post("/sites/dbsite/database", json={"engine": "postgres"})
    assert resp.status_code == 409


def test_create_postgres_and_mysql_for_same_site(client):
    """A site can have both a postgres and a mysql database."""
    client.post("/sites", json={"name": "dualsite", "site_type": "python"})
    r1 = client.post("/sites/dualsite/database", json={"engine": "postgres"})
    r2 = client.post("/sites/dualsite/database", json={"engine": "mysql"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    dbs = client.get("/sites/dualsite/database").json()
    assert len(dbs) == 2
    engines = {d["engine"] for d in dbs}
    assert engines == {"postgres", "mysql"}


def test_list_databases(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})
    client.post("/sites/dbsite/database", json={"engine": "postgres"})

    resp = client.get("/sites/dbsite/database")
    assert resp.status_code == 200
    dbs = resp.json()
    assert len(dbs) == 1
    assert dbs[0]["db_name"] == "site_dbsite"


def test_delete_database(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})
    client.post("/sites/dbsite/database", json={"engine": "postgres"})

    dbs = client.get("/sites/dbsite/database").json()
    db_id = dbs[0]["id"]

    resp = client.delete(f"/sites/dbsite/database/{db_id}")
    assert resp.status_code == 204

    resp = client.get("/sites/dbsite/database")
    assert resp.json() == []


def test_db_name_with_hyphen(client):
    """Site names with hyphens should produce valid db identifiers."""
    client.post("/sites", json={"name": "my-site", "site_type": "node"})
    resp = client.post("/sites/my-site/database", json={"engine": "postgres"})
    assert resp.status_code == 201
    data = resp.json()
    assert "_" in data["db_name"]  # hyphen replaced with underscore
