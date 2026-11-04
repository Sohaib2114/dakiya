import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import redis
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from . import config, db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("dakiya")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    log.info("schema ready")
    yield


app = FastAPI(title="Dakiya Tracking API", lifespan=lifespan)


class ScanEvent(BaseModel):
    tracking_id: str
    status: str  # booked, in_transit, out_for_delivery, delivered, returned
    depot: str
    scanned_at: datetime


def get_redis():
    return redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT)


def get_db():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@app.get("/")
def root():
    return {"service": "dakiya-api"}


@app.get("/healthz")
def healthz():
    # liveness: the process is running and answering
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    # readiness: the api can reach postgres and redis
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
        get_redis().ping()
    except Exception as exc:
        log.warning("not ready: %s", exc)
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@app.post("/scans", status_code=202)
def create_scan(event: ScanEvent, r=Depends(get_redis)):
    payload = event.model_dump(mode="json")
    log.debug("received scan %s", payload)
    r.lpush(config.QUEUE_NAME, json.dumps(payload))
    return {"queued": True}


@app.get("/parcels/{tracking_id}")
def get_parcel(tracking_id: str, conn=Depends(get_db)):
    parcel = conn.execute(
        "SELECT tracking_id, status, updated_at FROM parcels WHERE tracking_id = %s",
        (tracking_id,),
    ).fetchone()
    if parcel is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    history = conn.execute(
        "SELECT status, depot, scanned_at FROM scans WHERE tracking_id = %s ORDER BY scanned_at",
        (tracking_id,),
    ).fetchall()
    return {
        "tracking_id": parcel[0],
        "status": parcel[1],
        "updated_at": parcel[2],
        "history": [{"status": h[0], "depot": h[1], "scanned_at": h[2]} for h in history],
    }
