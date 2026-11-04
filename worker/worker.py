import json
import logging
import os

import psycopg
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dakiya-worker")

conn = psycopg.connect(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    dbname=os.getenv("DB_NAME", "dakiya"),
    user=os.getenv("DB_USER", "dakiya"),
    password=os.environ["DB_PASSWORD"],  # no default: fail fast if it is missing
)
r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379)

log.info("worker started")

while True:
    _, raw = r.brpop("scans")
    event = json.loads(raw)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (tracking_id, status, depot, scanned_at) VALUES (%s, %s, %s, %s)",
            (event["tracking_id"], event["status"], event["depot"], event["scanned_at"]),
        )
        cur.execute(
            """
            INSERT INTO parcels (tracking_id, status, updated_at) VALUES (%s, %s, %s)
            ON CONFLICT (tracking_id) DO UPDATE
            SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at
            """,
            (event["tracking_id"], event["status"], event["scanned_at"]),
        )
    conn.commit()
    log.info("processed %s -> %s", event["tracking_id"], event["status"])
