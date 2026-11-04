import psycopg

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels (
    tracking_id TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS scans (
    id          BIGSERIAL PRIMARY KEY,
    tracking_id TEXT NOT NULL,
    status      TEXT NOT NULL,
    depot       TEXT NOT NULL,
    scanned_at  TIMESTAMPTZ NOT NULL
);
"""


def connect():
    if not config.DB_PASSWORD:
        raise RuntimeError("DB_PASSWORD is not set")
    return psycopg.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        autocommit=True,
    )


def init_schema():
    with connect() as conn:
        conn.execute(SCHEMA)
