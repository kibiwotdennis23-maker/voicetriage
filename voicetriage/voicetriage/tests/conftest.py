import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voicetriage.app import create_app  # noqa: E402

ADMIN = {"Authorization": "Bearer admin"}


class FakeSms:
    def __init__(self):
        self.sent = []

    def __call__(self, cfg, to, message):
        self.sent.append((to, message))
        return "captured"


class Phone:
    """A pretend caller. Every response is parsed, so malformed XML fails the test."""

    def __init__(self, client, sid="call-1", caller="+254711000111"):
        self.client, self.sid, self.caller = client, sid, caller

    def send(self, digits=None, active="1"):
        form = {"sessionId": self.sid, "callerNumber": self.caller, "isActive": active, "direction": "Inbound"}
        if digits is not None:
            form["dtmfDigits"] = digits
        response = self.client.post("/voice", data=form)
        assert response.status_code == 200
        self.root = ET.fromstring(response.data)
        return self.root

    def press(self, *digits):
        root = None
        for digit in digits:
            root = self.send(digit)
        return root

    @staticmethod
    def says(root):
        return " ".join((e.text or "") for e in root.iter("Say"))

    @staticmethod
    def asking(root):
        return root.find("GetDigits") is not None


@pytest.fixture
def sms():
    return FakeSms()


@pytest.fixture
def app(tmp_path, sms):
    config = {
        "DB_PATH": str(tmp_path / "test.db"),
        "SECRET_KEY": "test-secret",
        "TOKENS": {"admin": "*", "ug": "SAMPLE-UG-01", "nandi": "SAMPLE-ND-01"},
        "ALERTS_PER_HOUR": 3,
        "BASE_URL": "http://test",
    }
    return create_app(config, sms=sms)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def store(app):
    return app.extensions["voicetriage"]["store"]


@pytest.fixture
def phone(client):
    def make(sid="call-1", caller="+254711000111"):
        return Phone(client, sid, caller)

    return make
