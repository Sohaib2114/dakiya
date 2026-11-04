from fastapi.testclient import TestClient

from app.main import app, get_db, get_redis


class FakeRedis:
    def __init__(self):
        self.items = []

    def lpush(self, queue, value):
        self.items.append((queue, value))
        return len(self.items)


class FakeCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakeConn:
    def execute(self, *args, **kwargs):
        return FakeCursor()


client = TestClient(app)

VALID_SCAN = {
    "tracking_id": "DKY-1001",
    "status": "in_transit",
    "depot": "ISB-01",
    "scanned_at": "2026-10-01T09:30:00Z",
}


def test_root():
    assert client.get("/").json() == {"service": "dakiya-api"}


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_scan_is_queued():
    fake = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake
    try:
        response = client.post("/scans", json=VALID_SCAN)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 202
    assert len(fake.items) == 1


def test_rejects_unknown_status():
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    try:
        response = client.post("/scans", json={**VALID_SCAN, "status": "teleported"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


def test_unknown_parcel_returns_404():
    app.dependency_overrides[get_db] = lambda: FakeConn()
    try:
        response = client.get("/parcels/DKY-NOPE")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
