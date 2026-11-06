"""Run once from a local terminal; administrator credentials are never saved."""
import getpass
import secrets
from pathlib import Path

import psycopg
from dotenv import dotenv_values, set_key
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent


def main():
    env_path = ROOT / ".env"
    existing = dotenv_values(env_path) if env_path.exists() else {}
    if existing:
        raise SystemExit(".env already has settings. Review it before running setup.")
    host = input("PostgreSQL host [127.0.0.1]: ").strip() or "127.0.0.1"
    port = int(input("PostgreSQL port [5432]: ").strip() or "5432")
    admin = input("Administrator username [postgres]: ").strip() or "postgres"
    password = getpass.getpass("PostgreSQL administrator password (hidden): ")
    app_password = secrets.token_urlsafe(32)
    with psycopg.connect(
        host=host, port=port, user=admin, password=password,
        dbname="postgres", autocommit=True, connect_timeout=5,
    ) as conn:
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", ("meridian_app",)).fetchone():
            raise SystemExit("Role meridian_app already exists; no changes made.")
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("meridian_it",)).fetchone():
            raise SystemExit("Database meridian_it already exists; no changes made.")
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier("meridian_app"), sql.Literal(app_password)
        ))
        try:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier("meridian_it"), sql.Identifier("meridian_app")
            ))
        except Exception:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier("meridian_app")))
            raise
    for key, value in {
        "DB_HOST": host, "DB_PORT": str(port), "DB_NAME": "meridian_it",
        "DB_USER": "meridian_app", "DB_PASSWORD": app_password,
        "SUPPORT_API_KEY": secrets.token_urlsafe(36),
        "ADMIN_API_KEY": secrets.token_urlsafe(36),
        "AUTH_JWT_SECRET": secrets.token_urlsafe(48),
    }.items():
        set_key(str(env_path), key, value)
    with psycopg.connect(
        host=host, port=port, dbname="meridian_it", user="meridian_app",
        password=app_password, connect_timeout=5,
    ) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
    print("Created meridian_it and meridian_app. Connection verified; credentials saved in .env.")


if __name__ == "__main__":
    main()
