"""Household settings saved before the redesign became the only UI still load (finance/ledger.py HouseholdConfig)."""
from fastapi.testclient import TestClient

from home_manager.app.api import create_app
from home_manager.finance.ledger import HouseholdConfig
from home_manager.library.scanner import ScanLimits


def test_a_saved_config_with_the_retired_screens_flag_loads():
    stored = {"checkin_weekday": 2, "ui_v2_screens": ["taxes", "home"]}
    config = HouseholdConfig.model_validate(stored)
    assert config.checkin_weekday == 2 and "ui_v2_screens" not in config.model_dump()
    assert HouseholdConfig.model_validate_json('{"ui_v2_screens": []}') == HouseholdConfig()


def test_the_flag_endpoint_is_gone_and_old_preferences_still_save(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        assert client.put("/api/ui-screens", json={"routes": ["taxes"]}).status_code in (404, 405)
        household = client.get("/api/settings").json()["household"]
        assert "ui_v2_screens" not in household
        # A page still open from before sends the old key back with Preferences; it's dropped, not refused.
        saved = client.put("/api/household-settings", json={**household, "checkin_weekday": 3, "ui_v2_screens": ["taxes"]})
        assert saved.status_code == 200, saved.text
        after = client.get("/api/settings").json()["household"]
        assert after["checkin_weekday"] == 3 and "ui_v2_screens" not in after
