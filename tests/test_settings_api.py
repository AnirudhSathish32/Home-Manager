"""The redesigned-screens flag (docs/ui.md "Migration"): saved per profile with the household settings."""
from fastapi.testclient import TestClient

from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits


def test_ui_screens_round_trip_and_survive_the_preferences_form(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        assert client.put("/api/ui-screens", json={"routes": ["taxes"]}).status_code == 400  # No library yet.
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        assert client.get("/api/settings").json()["household"]["ui_v2_screens"] == []
        saved = client.put("/api/ui-screens", json={"routes": ["taxes", "home"]})
        assert saved.status_code == 200 and saved.json()["ui_v2_screens"] == ["taxes", "home"]
        assert client.get("/api/settings").json()["household"]["ui_v2_screens"] == ["taxes", "home"]
        # Only route names: lower-case letters.
        for bad in (["Taxes"], ["../x"], ["a" * 33], "taxes", ["taxes"] * 33):
            assert client.put("/api/ui-screens", json={"routes": bad}).status_code == 422, bad
        assert client.put("/api/ui-screens", json={"routes": ["taxes"], "extra": 1}).status_code == 422
        # Saving Preferences sends the list back (app.js), so it stays.
        household = client.get("/api/settings").json()["household"]
        client.put("/api/household-settings", json={**household, "checkin_weekday": 2})
        after = client.get("/api/settings").json()["household"]
        assert after["checkin_weekday"] == 2 and after["ui_v2_screens"] == ["taxes", "home"]
        assert client.put("/api/ui-screens", json={"routes": []}).json()["ui_v2_screens"] == []
