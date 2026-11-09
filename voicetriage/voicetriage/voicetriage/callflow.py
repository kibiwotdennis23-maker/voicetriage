"""Voice call flow for Africa's Talking (XML in response to each webhook POST).

Africa's Talking calls our /voice webhook once when the call starts and again
each time the caller presses a key. We keep the caller's place in a small
session row keyed by sessionId, and answer every request with voice XML.

Stages: lang -> consent -> who -> q (repeated) -> region -> end.

Prompts are played from recorded audio when a pack has it, otherwise read out
with text-to-speech. Keypad input only in v1; speech recognition is a later phase.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from xml.sax.saxutils import escape, quoteattr

from .languages import available
from .notify import send_sms

log = logging.getLogger("voicetriage.callflow")

MAX_RETRIES = 3
SMS_LEVELS = {"emergency", "today"}  # "within 3 days" cases appear on the dashboard only
GENERIC_ERROR = (
    '<Say voice="woman">Sorry, the service is not available. '
    "If someone is unwell, please go to the nearest health facility.</Say>"
)


class CallFlow:
    def __init__(self, cfg, store, tree, packs, directory, required, sms=send_sms):
        self.cfg = cfg
        self.store = store
        self.tree = tree
        self.packs = packs
        self.directory = directory
        self.required = required
        self.sms = sms

    def languages(self):
        return available(self.packs, self.required, self.cfg.get("REQUIRE_REVIEWED", False))

    def handle(self, form: dict, callback_url: str, audio_base: str = "") -> str:
        """Return the voice XML (a <Response> element) for one webhook request."""
        return _Call(self, form, callback_url, audio_base).run()


class _Call:
    def __init__(self, flow, form, callback_url, audio_base):
        self.f = flow
        self.form = form
        self.cb = callback_url
        self.audio_base = (audio_base or "").rstrip("/")

    # ---- XML helpers ------------------------------------------------------
    def _play_or_say(self, pack, filename, text):
        if filename and self.audio_base:
            url = f"{self.audio_base}/audio/{pack.code}/{filename}"
            return f"<Play url={quoteattr(url)}/>"
        if text:
            return f'<Say voice="woman" playBeep="false">{escape(text)}</Say>'
        return ""

    def _speak(self, pack, key):
        if pack is None:
            return ""
        return self._play_or_say(pack, pack.audio.get(key), pack.text(key))

    def _speak_facility(self, pack, facility):
        recorded = (facility.get("audio") or {}).get(pack.code)
        return self._play_or_say(pack, recorded, facility["name"])

    @staticmethod
    def _wrap(inner):
        return f"<Response>{inner}</Response>"

    def _ask(self, inner):
        """Play prompts and wait for one key. On silence, Africa's Talking moves on to
        the Redirect, which re-posts here with no digit and counts as a retry."""
        return (
            f'<Response><GetDigits timeout="15" numDigits="1" callbackUrl={quoteattr(self.cb)}>'
            f"{inner}</GetDigits><Redirect>{escape(self.cb)}</Redirect></Response>"
        )

    @staticmethod
    def _digit(raw):
        raw = (raw or "").strip().rstrip("#")
        return raw if len(raw) == 1 and raw in "123456789" else None

    # ---- menus ------------------------------------------------------------
    def _lang_menu(self, langs):
        return "".join(self._speak(p, "menu") + self._speak(p, f"digit_{i}") for i, p in enumerate(langs, 1))

    def _region_menu(self, pack):
        parts = [self._speak(pack, "region_menu")]
        for i, key in enumerate(self.f.directory.region_keys(), 1):
            parts.append(self._speak(pack, f"region_{key}") + self._speak(pack, f"digit_{i}"))
        return "".join(parts)

    def _question(self, pack, node_id):
        return self._speak(pack, node_id) + self._speak(pack, "yes_no_hint")

    # ---- dispatcher -------------------------------------------------------
    def run(self):
        store = self.f.store
        sid = (self.form.get("sessionId") or "").strip()[:128]
        if not sid:
            return self._wrap(GENERIC_ERROR)
        if self.form.get("isActive") == "0":  # call ended: forget the caller
            store.delete_session(sid)
            return "<Response></Response>"
        langs = self.f.languages()
        if not langs:
            return self._wrap(GENERIC_ERROR)

        sess = store.get_session(sid)
        if sess is None:
            store.purge_sessions(3600)
            store.create_session(sid, (self.form.get("callerNumber") or "")[:20])
            return self._ask(self._lang_menu(langs))

        digit = self._digit(self.form.get("dtmfDigits"))
        if sess["stage"] == "lang":
            return self._on_lang(sess, langs, digit)
        pack = self.f.packs.get(sess["lang"])
        handler = {
            "consent": self._on_consent,
            "who": self._on_who,
            "q": self._on_question,
            "region": self._on_region,
        }.get(sess["stage"])
        if pack is None or handler is None:
            store.delete_session(sid)
            return self._wrap(GENERIC_ERROR)
        return handler(sess, pack, digit)

    def _retry(self, sess, pack, replay, goodbye_pack):
        """Wrong key or silence: replay the prompt, and hang up after MAX_RETRIES."""
        store = self.f.store
        attempts = sess["retries"] + 1
        if attempts >= MAX_RETRIES:
            store.delete_session(sess["session_id"])
            return self._wrap(self._speak(goodbye_pack, "goodbye"))
        store.update_session(sess["session_id"], retries=attempts)
        return self._ask(self._speak(pack, "invalid") + replay)

    # ---- stages -----------------------------------------------------------
    def _on_lang(self, sess, langs, digit):
        index = int(digit) - 1 if digit else None
        if index is None or index >= len(langs):
            return self._retry(sess, None, self._lang_menu(langs), langs[0])
        pack = langs[index]
        self.f.store.update_session(sess["session_id"], lang=pack.code, stage="consent", retries=0)
        return self._ask(self._speak(pack, "consent"))

    def _on_consent(self, sess, pack, digit):
        if digit not in ("1", "2"):
            return self._retry(sess, pack, self._speak(pack, "consent"), pack)
        tree = self.f.tree
        self.f.store.update_session(
            sess["session_id"], consent=1 if digit == "1" else 0, stage="who", node=tree.start, retries=0
        )
        return self._ask(self._speak(pack, "who"))

    def _on_who(self, sess, pack, digit):
        tree = self.f.tree
        if digit not in tree.node(tree.start)["options"]:
            return self._retry(sess, pack, self._speak(pack, "who"), pack)
        return self._advance(sess, pack, [[tree.start, digit]], tree.next_node(tree.start, digit))

    def _on_question(self, sess, pack, digit):
        answer = {"1": "yes", "2": "no"}.get(digit)
        if answer is None:
            return self._retry(sess, pack, self._question(pack, sess["node"]), pack)
        trail = json.loads(sess["trail"]) + [[sess["node"], answer]]
        return self._advance(sess, pack, trail, self.f.tree.next_node(sess["node"], answer))

    def _advance(self, sess, pack, trail, node_id):
        tree, store = self.f.tree, self.f.store
        if tree.is_outcome(node_id):
            return self._outcome(sess, pack, trail, node_id)
        store.update_session(sess["session_id"], stage="q", node=node_id, trail=json.dumps(trail), retries=0)
        return self._ask(self._question(pack, node_id))

    def _outcome(self, sess, pack, trail, outcome_id):
        tree, store = self.f.tree, self.f.store
        said = self._speak(pack, outcome_id)
        if tree.node(outcome_id)["level"] == "home":
            store.delete_session(sess["session_id"])
            return self._wrap(said + self._speak(pack, "disclaimer") + self._speak(pack, "goodbye"))
        store.update_session(
            sess["session_id"], stage="region", outcome=outcome_id, trail=json.dumps(trail), retries=0
        )
        return self._ask(said + self._region_menu(pack))

    def _on_region(self, sess, pack, digit):
        directory = self.f.directory
        regions = directory.regions
        index = int(digit) - 1 if digit else None
        if index is None or index >= len(regions):
            return self._retry(sess, pack, self._region_menu(pack), pack)
        region = regions[index]
        facility = directory.facility_for(region["key"])
        spoken = self._speak(pack, "facility_intro") + self._speak_facility(pack, facility)
        spoken += self._alert(sess, pack, region, facility)
        self.f.store.delete_session(sess["session_id"])
        return self._wrap(spoken + self._speak(pack, "disclaimer") + self._speak(pack, "goodbye"))

    # ---- facility pre-alert -----------------------------------------------
    def _alert(self, sess, pack, region, facility):
        """Create the dashboard alert (and SMS) if the caller consented. Returns speech."""
        f = self.f
        caller = sess["caller"]
        if not sess["consent"] or not caller:
            return self._speak(pack, "no_alert")
        ref = hmac.new(f.cfg["SECRET_KEY"].encode(), caller.encode(), hashlib.sha256).hexdigest()[:12]
        if f.store.recent_alert_count(ref, time.time() - 3600) >= f.cfg["ALERTS_PER_HOUR"]:
            return self._speak(pack, "no_alert")  # stops one number flooding a clinic
        summary = f.tree.summarize(json.loads(sess["trail"]), sess["outcome"])
        alert_id = f.store.add_alert(
            facility_id=facility["id"],
            region=region["key"],
            lang=pack.code,
            level=summary["level"],
            group_label=summary["group"],
            reported=json.dumps(summary["reported"]),
            caller_ref=ref,
            caller_number=caller,
        )
        status = "not_sent"
        if summary["level"] in SMS_LEVELS:
            status = self._notify(alert_id, facility, summary)
        f.store.set_sms_status(alert_id, status)
        return self._speak(pack, "alert_sent")

    def _notify(self, alert_id, facility, summary):
        shown = "; ".join(summary["reported"][:3]) or "none reported"
        # No phone number in the SMS: staff open the dashboard for contact details.
        text = f"VoiceTriage #{alert_id} [{summary['level'].upper()}] {summary['group']}. Reported: {shown}. See dashboard."
        try:
            return self.f.sms(self.f.cfg, facility.get("sms"), text[:300])
        except Exception as exc:  # an SMS failure must never break the caller's advice
            log.warning("SMS failed: %s", type(exc).__name__)
            return f"failed:{type(exc).__name__}"
