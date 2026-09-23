import time

from fastapi.testclient import TestClient

from home_manager.api import create_app
from home_manager.scanner import ScanLimits


URL = "http://127.0.0.1:8765"
AUTH = {"Authorization": "Bearer test-session-token"}


def test_local_auth_and_browser_origin(tmp_path):
    with TestClient(create_app(tmp_path / "control", "test-session-token"), base_url=URL) as client:
        assert client.get("/").status_code == 200
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
        assert client.get("/api/settings").status_code == 401
        assert client.get("/api/documents/1/image").status_code == 401
        assert client.get("/api/receipt-runs/unknown").status_code == 401
        assert client.get("/api/receipt-runs/unknown/preview").status_code == 401
        assert client.post("/api/documents/1/receipt-runs", json={}).status_code == 401
        assert client.get("/api/settings", headers=AUTH).status_code == 200
        assert client.get("/api/settings", headers={**AUTH, "Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/settings", headers={**AUTH, "Host": "evil.example"}).status_code == 403
        assert client.put("/api/settings", headers=AUTH, content="x" * 17000).status_code == 413


def test_config_scan_history_and_restart(tmp_path):
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    (month / "my.csv").write_bytes(b"date,total\n2026-09-01,123\n")
    control = tmp_path / "control"
    config = {"source_directory": str(source), "managed_directory": str(tmp_path / "managed")}
    with TestClient(create_app(control, "test-session-token", limits=ScanLimits(stability_seconds=0)), base_url=URL, headers=AUTH) as client:
        assert client.post("/api/scans", json={}).status_code == 400
        assert client.put("/api/settings", json=config).status_code == 200
        assert client.post("/api/scans", json={"month": 9}).status_code == 422
        assert client.post("/api/scans", json={"year": "2026"}).status_code == 422
        response = client.post("/api/scans", json={"year": 2026, "month": 9})
        assert response.status_code == 202
        job = response.json()["job_id"]
        for _ in range(200):
            state = client.get(f"/api/scans/{job}").json()
            if state["status"] not in ("queued", "running"):
                break
            time.sleep(.01)
        assert state["status"] == "completed", state
        assert state["counts"] == {"captured": 1}
        docs = client.get("/api/documents").json()
        assert docs["total"] == 1
        assert len(client.get(f"/api/documents/{docs['items'][0]['id']}/versions").json()) == 1
        assert client.get(f"/api/scans/{job}/events").json()[0]["relative_path"] == "2026/09/my.csv"
        assert client.get("/api/documents?offset=-1").status_code == 422
        assert client.get("/api/scans/unknown").status_code == 404
    with TestClient(create_app(control, "new-token"), base_url=URL, headers={"Authorization": "Bearer new-token"}) as client:
        assert client.get("/api/settings").json()["configured"]
        assert client.get("/api/documents").json()["total"] == 1
        assert len(client.get("/api/scans").json()) == 1


def test_configuration_cannot_change_during_scan(tmp_path, monkeypatch):
    import threading
    from home_manager.scanner import Scanner
    entered, release = threading.Event(), threading.Event()
    def blocked(self, job, source, year, month):
        entered.set()
        release.wait(timeout=5)
        self.store.job_state(job, "completed")
    monkeypatch.setattr(Scanner, "run", blocked)
    source = tmp_path / "source"
    source.mkdir()
    config = {"source_directory": str(source), "managed_directory": str(tmp_path / "managed")}
    with TestClient(create_app(tmp_path / "control", "test-session-token"), base_url=URL, headers=AUTH) as client:
        client.put("/api/settings", json=config)
        try:
            assert client.post("/api/scans", json={}).status_code == 202
            assert entered.wait(timeout=2)
            assert client.put("/api/settings", json=config).status_code == 409
            assert client.post("/api/scans", json={}).status_code == 409
        finally:
            release.set()
