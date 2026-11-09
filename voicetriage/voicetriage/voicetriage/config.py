"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
import secrets


def parse_tokens(raw: str) -> dict:
    """'tokenA=SAMPLE-UG-01,tokenB=*' -> {'tokenA': 'SAMPLE-UG-01', 'tokenB': '*'}.

    The value is the facility id a token may see, or '*' for every facility.
    """
    tokens = {}
    for part in (raw or "").split(","):
        token, _, scope = part.strip().partition("=")
        if token.strip() and scope.strip():
            tokens[token.strip()] = scope.strip()
    return tokens


def default_config() -> dict:
    env = os.environ.get
    return {
        "DB_PATH": env("VT_DB", "voicetriage.db"),
        "BASE_URL": env("VT_BASE_URL", ""),  # public https URL, used for audio and callbacks
        "SECRET_KEY": env("VT_SECRET") or secrets.token_hex(32),
        "WEBHOOK_SECRET": env("VT_WEBHOOK_SECRET", ""),  # appended to the voice callback as ?s=
        "TOKENS": parse_tokens(env("VT_TOKENS", "")),
        "SMS_MODE": env("VT_SMS_MODE", "dry_run"),  # dry_run | sandbox | live
        "AT_USERNAME": env("AT_USERNAME", "sandbox"),
        "AT_API_KEY": env("AT_API_KEY", ""),
        "REQUIRE_REVIEWED": env("VT_REQUIRE_REVIEWED", "0") == "1",
        "ALERTS_PER_HOUR": int(env("VT_ALERTS_PER_HOUR", "3")),
    }
