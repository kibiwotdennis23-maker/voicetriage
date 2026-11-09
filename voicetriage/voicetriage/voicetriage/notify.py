"""SMS pre-alerts to facilities through Africa's Talking.

Default mode is dry_run (log only). The sandbox/live paths follow Africa's
Talking's messaging API but have not been exercised against their servers yet.
"""
from __future__ import annotations

import logging
import urllib.parse
import urllib.request

log = logging.getLogger("voicetriage.sms")

LIVE_URL = "https://api.africastalking.com/version1/messaging"
SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"


def send_sms(cfg: dict, to, message: str) -> str:
    """Send one SMS and return a short status string. May raise on network errors."""
    if not to:
        return "no_number"
    mode = cfg.get("SMS_MODE", "dry_run")
    if mode == "dry_run":
        log.info("[dry-run] SMS to %s: %s", to, message)
        return "dry_run"
    if not cfg.get("AT_API_KEY"):
        return "not_configured"
    url = SANDBOX_URL if mode == "sandbox" else LIVE_URL
    body = urllib.parse.urlencode({"username": cfg["AT_USERNAME"], "to": to, "message": message}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "apiKey": cfg["AT_API_KEY"],
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return f"http_{response.status}"
