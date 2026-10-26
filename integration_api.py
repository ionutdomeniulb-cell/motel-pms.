"""API de integrare (v1) pentru Home Assistant sau alte sisteme din rețeaua locală.

Citește starea camerelor și evenimentele; nu poate crea sau modifica rezervări.
Dezactivat implicit: se activează setând variabila de mediu MOTEL_API_TOKEN (minimum 24 de caractere).
"""
import json
import os
import secrets
import time
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

import clock
import room_state
import version as app_version_info

bp = Blueprint("integration_api", __name__, url_prefix="/api/v1")
_connect = None
MIN_TOKEN_LENGTH = 24
_failures = {}          # ip -> momente ale încercărilor eșuate (limitare împotriva ghicirii tokenului)
MAX_FAILURES, WINDOW = 10, 900


def register(app, connect):
    global _connect
    _connect = connect
    app.register_blueprint(bp)


def _json(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.before_request
def require_token():
    expected = os.environ.get("MOTEL_API_TOKEN", "")
    if len(expected) < MIN_TOKEN_LENGTH:
        return _json({"error": "API-ul de integrare este dezactivat. Setați MOTEL_API_TOKEN (minimum 24 de caractere)."}, 503)
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    ip, now = request.remote_addr or "?", time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < WINDOW]
    if len(recent) >= MAX_FAILURES:
        return _json({"error": "Prea multe încercări. Reîncercați mai târziu."}, 429)
    if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
        _failures[ip] = recent + [now]
        current_app.logger.warning("API v1: token invalid de la %s", ip)
        return _json({"error": "Token invalid."}, 401)
    return None


@bp.get("/health")
def health():
    conn = _connect()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    last_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM room_events").fetchone()[0]
    conn.close()
    return _json({"ok": True, "time": clock.now().astimezone().isoformat(timespec="seconds"),
                  "schema_version": version, "last_event_id": last_id, "app_version": app_version_info.label(), "test_clock": clock.is_test()})


@bp.get("/rooms")
def rooms():
    conn = _connect()
    states = room_state.compute_room_states(conn)
    conn.close()
    return _json({"generated_at": clock.now().astimezone().isoformat(timespec="seconds"),
                  "rooms": [room_state.public_view(s) for s in states]})


@bp.get("/rooms/<code>")
def room(code):
    conn = _connect()
    row = conn.execute("SELECT id FROM rooms WHERE code=? AND active=1", (code,)).fetchone()
    states = room_state.compute_room_states(conn, room_id=row["id"]) if row else []
    conn.close()
    if not states:
        return _json({"error": "Camera nu există."}, 404)
    return _json(room_state.public_view(states[0]))


@bp.get("/events")
def events():
    try:
        after_id = max(0, int(request.args.get("after_id", "0")))
        limit = max(1, min(500, int(request.args.get("limit", "100"))))
    except ValueError:
        return _json({"error": "after_id și limit trebuie să fie numere întregi."}, 400)
    conn = _connect()
    rows = conn.execute("SELECT * FROM room_events WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit)).fetchall()
    last_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM room_events").fetchone()[0]
    conn.close()
    items = []
    for r in rows:
        payload = json.loads(r["payload"])
        payload.pop("actor", None)  # numele personalului rămâne în PMS
        items.append({"id": r["id"], "created_at": r["created_at"], "event_type": r["event_type"],
                      "room_code": r["room_code"], "booking_id": r["booking_id"], **payload})
    return _json({"events": items, "last_event_id": last_id, "has_more": bool(items) and items[-1]["id"] < last_id})


@bp.post("/events/ack")
def ack_events():
    body = request.get_json(silent=True) or {}
    try:
        up_to = int(body.get("up_to_id"))
    except (TypeError, ValueError):
        return _json({"error": "Trimiteți JSON cu up_to_id (număr întreg)."}, 400)
    conn = _connect()
    cur = conn.execute("UPDATE room_events SET acked_at=? WHERE id<=? AND acked_at IS NULL",
                       (clock.now().astimezone().isoformat(timespec="seconds"), up_to))
    conn.close()
    return _json({"acknowledged": cur.rowcount, "up_to_id": up_to})
