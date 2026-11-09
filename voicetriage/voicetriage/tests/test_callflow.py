from conftest import ADMIN


def test_first_request_plays_language_menu(phone):
    root = phone().send()
    assert root.find("GetDigits") is not None
    assert root.find("Redirect") is not None
    callback = root.find("GetDigits").get("callbackUrl")
    assert callback == "http://test/voice"


def test_emergency_call_creates_alert_and_sms(phone, client, sms):
    p = phone()
    p.send()
    # English, share with clinic, child under 5, cannot drink = yes, Uasin Gishu
    root = p.press("1", "1", "1", "1")
    assert "emergency" in p.says(root).lower()
    assert p.asking(root)  # now waiting for the county key
    root = p.press("1")
    assert not p.asking(root)  # call is finished
    assert "Sample referral hospital" in p.says(root)
    assert "told you are coming" in p.says(root)

    alerts = client.get("/api/alerts", headers=ADMIN).get_json()["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["level"] == "emergency"
    assert alert["group"] == "Child under 5 years"
    assert alert["reported"] == ["Unable to drink or breastfeed, or vomits everything"]
    assert alert["facility_id"] == "SAMPLE-UG-01"

    assert len(sms.sent) == 1
    to, text = sms.sent[0]
    assert to == "+254000000001"
    assert "EMERGENCY" in text
    assert "+254711000111" not in text  # the clinic SMS never carries the caller's number


def test_swahili_path_ends_with_home_care_and_no_alert(phone, client, sms):
    p = phone()
    p.send()
    root = p.press("2")
    assert "Karibu" in p.says(root)
    root = p.press("2")  # decline sharing
    assert "Ni nani mgonjwa" in p.says(root)
    root = p.press("3")  # adult
    for _ in range(6):
        root = p.press("2")
        assert p.asking(root)
    root = p.press("2")  # last question: no
    assert not p.asking(root)
    assert "nyumbani" in p.says(root)
    assert client.get("/api/alerts?include=all", headers=ADMIN).get_json()["alerts"] == []
    assert sms.sent == []


def test_declining_consent_gives_advice_but_no_alert(phone, client, sms):
    p = phone()
    p.send()
    p.press("1", "2", "1", "1")  # English, no sharing, child, cannot drink
    root = p.press("1")
    assert "has not been told" in p.says(root)
    assert client.get("/api/alerts?include=all", headers=ADMIN).get_json()["alerts"] == []
    assert sms.sent == []


def test_three_wrong_keys_hang_up_politely(phone, store):
    p = phone()
    p.send()
    p.press("9")
    p.press("9")
    root = p.press("9")
    assert not p.asking(root)
    assert "Goodbye" in p.says(root)
    assert store.session_count() == 0


def test_silence_counts_as_a_retry(phone):
    p = phone()
    p.send()
    root = p.send()  # no digit: caller said nothing, Africa's Talking re-posts
    assert p.asking(root)
    p.send()
    root = p.send()
    assert not p.asking(root)


def test_unfinished_language_is_not_on_the_menu(phone):
    p = phone()
    p.send()
    p.press("3")  # only two languages are ready, so 3 is invalid
    assert p.asking(p.root)


def test_hangup_deletes_the_session(phone, store):
    p = phone()
    p.send()
    p.press("1")
    assert store.session_count() == 1
    root = p.send(active="0")
    assert root.tag == "Response"
    assert store.session_count() == 0


def test_same_number_cannot_flood_a_clinic(phone, client, app, sms):
    app.extensions["voicetriage"]["cfg"]["ALERTS_PER_HOUR"] = 1
    for sid in ("a", "b"):
        p = phone(sid=sid)
        p.send()
        p.press("1", "1", "1", "1", "1")
    assert len(client.get("/api/alerts", headers=ADMIN).get_json()["alerts"]) == 1
    assert len(sms.sent) == 1
    assert "has not been told" in p.says(p.root)  # second caller still got advice


def test_within_three_days_goes_to_dashboard_but_not_sms(phone, client, sms):
    p = phone()
    p.send()
    p.press("1", "1", "3")  # English, share, adult
    p.press("2", "2", "2", "2", "2")  # five "no"
    p.press("1")  # a_cough: yes -> within 3 days
    root = p.press("1")  # county
    assert "told you are coming" in p.says(root)
    alerts = client.get("/api/alerts", headers=ADMIN).get_json()["alerts"]
    assert alerts[0]["level"] == "within_3_days"
    assert sms.sent == []


def test_sms_failure_does_not_break_the_call(tmp_path):
    from conftest import Phone
    from voicetriage.app import create_app

    def broken(cfg, to, message):
        raise OSError("network down")

    app = create_app({"DB_PATH": str(tmp_path / "x.db"), "SECRET_KEY": "k", "TOKENS": {"admin": "*"}}, sms=broken)
    p = Phone(app.test_client())
    p.send()
    root = p.press("1", "1", "1", "1", "1")
    assert "told you are coming" in p.says(root)
    alert = app.extensions["voicetriage"]["store"].list_alerts()[0]
    assert alert["sms_status"].startswith("failed")


def test_garbage_input_never_breaks_xml(phone):
    p = phone()
    p.send()
    for junk in ("", "0", "*", "#", "abc", "12", "<script>", "1;DROP TABLE sessions", "\u0000"):
        p.send(junk)  # Phone.send parses every response as XML


def test_webhook_secret_is_enforced(tmp_path):
    from voicetriage.app import create_app

    app = create_app({"DB_PATH": str(tmp_path / "w.db"), "SECRET_KEY": "k", "WEBHOOK_SECRET": "s3cret", "BASE_URL": "http://t"})
    client = app.test_client()
    form = {"sessionId": "x", "isActive": "1"}
    assert client.post("/voice", data=form).status_code == 403
    assert client.post("/voice?s=wrong", data=form).status_code == 403
    ok = client.post("/voice?s=s3cret", data=form)
    assert ok.status_code == 200
    assert b"s=s3cret" in ok.data  # follow-up callbacks carry the secret too
