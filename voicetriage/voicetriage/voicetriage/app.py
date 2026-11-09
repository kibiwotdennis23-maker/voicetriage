"""Flask app: voice webhook, clinic dashboard API and static dashboard."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.parse
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from .callflow import CallFlow
from .config import default_config
from .engine import LEVEL_RANK, Tree
from .facilities import Directory
from .languages import LANG_DIR, available, load_packs, required_keys
from .notify import send_sms
from .storage import Store, loads

DASH_DIR = Path(__file__).resolve().parent.parent / "dashboard"
log = logging.getLogger("voicetriage")

SAFE_FALLBACK = (
    "<Response><Say>Sorry, there is a technical problem. "
    "If someone is unwell, please go to the nearest health facility.</Say></Response>"
)


def mask(number: str) -> str:
    """+254711000111 -> +254*****111"""
    if len(number) <= 7:
        return "*" * len(number)
    return number[:4] + "*" * (len(number) - 7) + number[-3:]


def create_app(config=None, sms=send_sms) -> Flask:
    cfg = default_config()
    cfg.update(config or {})

    tree = Tree.load()
    problems = tree.validate()
    if problems:
        raise RuntimeError("Invalid triage tree:\n" + "\n".join(problems))
    directory = Directory.load()
    packs = load_packs(cfg.get("LANG_DIR", LANG_DIR))
    required = required_keys(tree, directory)
    store = Store(cfg["DB_PATH"])
    flow = CallFlow(cfg, store, tree, packs, directory, required, sms)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.extensions["voicetriage"] = {"cfg": cfg, "store": store, "flow": flow, "tree": tree}

    # ---- helpers ----------------------------------------------------------
    def xml(body: str) -> Response:
        return Response('<?xml version="1.0" encoding="UTF-8"?>' + body, mimetype="application/xml")

    def authenticate():
        header = request.headers.get("Authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        match = None
        for token, scope in cfg["TOKENS"].items():  # compare against all: no early exit
            if hmac.compare_digest(token.encode(), supplied.encode()):
                match = (token, scope)
        if match is None:
            abort(401)
        return match[1], hashlib.sha256(match[0].encode()).hexdigest()[:8]

    def scoped_alert(alert_id, scope):
        row = store.get_alert(alert_id)
        if row is None or (scope != "*" and row["facility_id"] != scope):
            abort(404)  # same answer either way: do not reveal other facilities' alerts
        return row

    def alert_json(row):
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "level": row["level"],
            "rank": LEVEL_RANK.get(row["level"], 99),
            "group": row["group_label"],
            "reported": loads(row["reported"], []),
            "facility_id": row["facility_id"],
            "facility": directory.facility(row["facility_id"])["name"],
            "region": row["region"],
            "lang": row["lang"],
            "status": row["status"],
            "ack_by": row["ack_by"],
            "sms_status": row["sms_status"],
            "caller_masked": mask(row["caller_number"]),
        }

    # ---- voice webhook ----------------------------------------------------
    @app.post("/voice")
    def voice():
        secret = cfg["WEBHOOK_SECRET"]
        if secret and not hmac.compare_digest(request.args.get("s", ""), secret):
            abort(403)
        base = (cfg["BASE_URL"] or request.url_root).rstrip("/")
        callback = base + "/voice" + ("?" + urllib.parse.urlencode({"s": secret}) if secret else "")
        try:
            body = flow.handle(request.form.to_dict(), callback, base)
        except Exception:  # never leave a caller in silence
            log.exception("call flow error")
            body = SAFE_FALLBACK
        return xml(body)

    # ---- public info ------------------------------------------------------
    @app.get("/health")
    def health():
        live = [p.code for p in available(packs, required, cfg["REQUIRE_REVIEWED"])]
        return jsonify(status="ok", languages_live=live)

    @app.get("/api/languages")
    def languages():
        return jsonify(languages=[
            {
                "code": p.code,
                "name": p.name,
                "ready": p.is_ready(required),
                "reviewed": p.reviewed,
                "missing": len(p.missing(required)),
            }
            for p in sorted(packs.values(), key=lambda p: (p.order, p.code))
        ])

    @app.get("/audio/<code>/<path:filename>")
    def audio(code, filename):
        if code not in packs:
            abort(404)
        return send_from_directory(packs[code].path / "audio", filename, max_age=3600)

    # ---- clinic dashboard API ---------------------------------------------
    @app.get("/api/alerts")
    def list_alerts():
        scope, _ = authenticate()
        rows = store.list_alerts(scope, include_acked=request.args.get("include") == "all")
        alerts = sorted((alert_json(r) for r in rows), key=lambda a: (a["rank"], a["created_at"]))
        return jsonify(alerts=alerts)

    @app.post("/api/alerts/<int:alert_id>/ack")
    def ack(alert_id):
        scope, actor = authenticate()
        scoped_alert(alert_id, scope)
        store.ack_alert(alert_id, actor)
        store.log_audit(actor, "ack", alert_id)
        return jsonify(ok=True)

    @app.get("/api/alerts/<int:alert_id>/contact")
    def contact(alert_id):
        scope, actor = authenticate()
        row = scoped_alert(alert_id, scope)
        store.log_audit(actor, "view_contact", alert_id)  # every reveal is recorded
        return jsonify(number=row["caller_number"])

    @app.get("/dashboard/")
    def dashboard_index():
        return send_from_directory(DASH_DIR, "index.html")

    @app.get("/dashboard/<path:name>")
    def dashboard_file(name):
        return send_from_directory(DASH_DIR, name)

    # ---- errors and headers -----------------------------------------------
    @app.errorhandler(401)
    def unauthorised(_):
        return jsonify(error="unauthorised"), 401

    @app.errorhandler(403)
    def forbidden(_):
        return jsonify(error="forbidden"), 403

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="not found"), 404

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="request too large"), 413

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith(("/api/", "/voice")):
            response.headers["Cache-Control"] = "no-store"
        if request.path.startswith("/dashboard"):
            response.headers["Content-Security-Policy"] = "default-src 'self'"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    return app
