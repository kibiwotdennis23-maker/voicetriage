import pytest

from conftest import ADMIN

UG = {"Authorization": "Bearer ug"}
NANDI = {"Authorization": "Bearer nandi"}


@pytest.fixture
def two_alerts(phone):
    """One emergency in Uasin Gishu, one in Nandi, from different callers."""
    a = phone(sid="a", caller="+254711000001")
    a.send()
    a.press("1", "1", "1", "1", "1")  # county key 1 = Uasin Gishu
    b = phone(sid="b", caller="+254711000002")
    b.send()
    b.press("1", "1", "1", "1", "2")  # county key 2 = Nandi


def test_api_requires_a_valid_token(client):
    assert client.get("/api/alerts").status_code == 401
    assert client.get("/api/alerts", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/alerts", headers={"Authorization": "admin"}).status_code == 401
    assert client.get("/api/alerts", headers=ADMIN).status_code == 200


def test_facility_tokens_only_see_their_own_alerts(client, two_alerts):
    assert len(client.get("/api/alerts", headers=ADMIN).get_json()["alerts"]) == 2
    ug = client.get("/api/alerts", headers=UG).get_json()["alerts"]
    assert [a["facility_id"] for a in ug] == ["SAMPLE-UG-01"]
    nandi = client.get("/api/alerts", headers=NANDI).get_json()["alerts"]
    assert [a["facility_id"] for a in nandi] == ["SAMPLE-ND-01"]


def test_list_masks_the_number_and_contact_reveals_it_with_audit(client, store, two_alerts):
    listing = client.get("/api/alerts", headers=UG)
    assert b"+254711000001" not in listing.data
    alert_id = listing.get_json()["alerts"][0]["id"]

    revealed = client.get(f"/api/alerts/{alert_id}/contact", headers=UG)
    assert revealed.get_json()["number"] == "+254711000001"
    entry = store.audit_log()[0]
    assert entry["action"] == "view_contact" and entry["alert_id"] == alert_id


def test_cannot_touch_another_facilitys_alert(client, store, two_alerts):
    nandi_id = client.get("/api/alerts", headers=NANDI).get_json()["alerts"][0]["id"]
    assert client.get(f"/api/alerts/{nandi_id}/contact", headers=UG).status_code == 404
    assert client.post(f"/api/alerts/{nandi_id}/ack", headers=UG).status_code == 404
    assert store.audit_log() == []  # nothing was revealed, nothing logged


def test_ack_hides_alert_from_default_list(client, two_alerts):
    alert_id = client.get("/api/alerts", headers=UG).get_json()["alerts"][0]["id"]
    assert client.post(f"/api/alerts/{alert_id}/ack", headers=UG).status_code == 200
    assert client.get("/api/alerts", headers=UG).get_json()["alerts"] == []
    shown = client.get("/api/alerts?include=all", headers=UG).get_json()["alerts"]
    assert shown[0]["status"] == "acknowledged"


def test_most_urgent_alerts_come_first(phone, client):
    soon = phone(sid="s", caller="+254711000003")
    soon.send()
    soon.press("1", "1", "3", "2", "2", "2", "2", "2", "1", "1")  # a_cough yes: within 3 days
    emergency = phone(sid="e", caller="+254711000004")
    emergency.send()
    emergency.press("1", "1", "1", "1", "1")
    levels = [a["level"] for a in client.get("/api/alerts", headers=ADMIN).get_json()["alerts"]]
    assert levels == ["emergency", "within_3_days"]


def test_language_and_health_endpoints_are_public(client):
    langs = {l["code"]: l for l in client.get("/api/languages").get_json()["languages"]}
    assert langs["en"]["ready"] and langs["sw"]["ready"]
    assert client.get("/health").get_json()["languages_live"][:2] == ["en", "sw"]


def test_audio_route_refuses_traversal_and_unknown_languages(client):
    assert client.get("/audio/xx/a.mp3").status_code == 404
    assert client.get("/audio/en/../pack.json").status_code == 404
    assert client.get("/audio/en/%2e%2e/pack.json").status_code == 404


def test_dashboard_is_served_with_a_strict_csp(client):
    page = client.get("/dashboard/")
    assert page.status_code == 200
    assert page.headers["Content-Security-Policy"] == "default-src 'self'"
    assert client.get("/dashboard/app.js").status_code == 200
    assert client.get("/dashboard/../voicetriage/app.py").status_code == 404
