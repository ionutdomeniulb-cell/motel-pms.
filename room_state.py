"""Starea camerelor și coada de evenimente pentru integrări (Home Assistant etc.).

Contract: PMS-ul spune în ce stare este fiecare cameră; sistemele externe decid ce fac cu asta.
Modulul nu depinde de Flask și nu comandă niciun dispozitiv.
"""
import json
import os
import re

import clock
from datetime import date, datetime, time as dtime

now_fn = clock.now  # ceasul aplicației (ceas de test inclus); testele îl pot înlocui

ACTIVE_STATUSES = ("confirmed", "checked_in")

STATE_LABELS = {
    "out_of_order": "Defectă",
    "departing": "Plecare azi",
    "occupied": "Ocupată",
    "arriving": "Sosire azi",
    "vacant_clean": "Liberă curată",
    "vacant_to_check": "Liberă, de verificat",
}
STATE_ORDER = ["occupied", "departing", "arriving", "vacant_to_check", "vacant_clean", "out_of_order"]

# Câmpuri expuse integrărilor. Numele clientului și notele de mentenanță nu pleacă din PMS.
PUBLIC_FIELDS = ["room_id", "room_code", "room_name", "building", "state", "clean_today", "booking_id",
                 "booking_status", "guests", "check_in", "check_out", "arrival_today", "departure_today",
                 "occupied_tonight", "next_arrival_date", "out_of_order", "auto_released", "checkin_time", "checkout_time"]


def _parse_hhmm(value, default):
    try:
        hh, mm = str(value).split(":")
        return dtime(int(hh), int(mm))
    except (ValueError, TypeError):
        return default


def stay_times():
    """Ora de check-in (implicit 12:00) și de check-out (implicit 13:00); se pot schimba cu MOTEL_CHECKIN_TIME / MOTEL_CHECKOUT_TIME."""
    return (_parse_hhmm(os.environ.get("MOTEL_CHECKIN_TIME"), dtime(12, 0)),
            _parse_hhmm(os.environ.get("MOTEL_CHECKOUT_TIME"), dtime(13, 0)))


def slugify_room_code(name):
    return "camera_" + re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def migrate(conn):
    """Schema v9: cod stabil pe cameră + tabel de evenimente. Nu șterge nimic."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(rooms)").fetchall()}
    if "code" not in columns:
        conn.execute("ALTER TABLE rooms ADD COLUMN code TEXT")
    for row in conn.execute("SELECT id, name FROM rooms WHERE code IS NULL OR code=''").fetchall():
        conn.execute("UPDATE rooms SET code=? WHERE id=?", (slugify_room_code(row["name"]), row["id"]))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_code ON rooms(code)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            room_id INTEGER NOT NULL REFERENCES rooms(id),
            room_code TEXT NOT NULL,
            booking_id INTEGER,
            payload TEXT NOT NULL DEFAULT '{}',
            acked_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_room_events_room ON room_events(room_id, id)")


def compute_room_states(conn, today=None, room_id=None, now=None):
    """Starea fiecărei camere active, ținând cont de ora curentă.

    După ora de check-out (13:00) o cameră cu plecare astăzi devine liberă automat, fără intervenția nimănui;
    rămâne vizibilă rezervarea care intră în aceeași zi. Nu se modifică nimic în baza de date."""
    now = now or now_fn()
    today = today or now.date().isoformat()
    checkin_t, checkout_t = stay_times()
    checkout_passed = now.time() >= checkout_t
    params = [room_id] if room_id else []
    rooms = conn.execute(
        "SELECT id, code, name, building, out_of_order, maintenance_note FROM rooms WHERE active=1"
        + (" AND id=?" if room_id else "")
        + " ORDER BY CASE building WHEN 'Corp A' THEN 1 WHEN 'Corp B' THEN 2 WHEN 'Corp C' THEN 3 ELSE 4 END, sort_order, name",
        params).fetchall()
    booking_sql = """SELECT id, room_id, guest_name, check_in, check_out, guests, status FROM bookings
        WHERE (status IN ('provisional','confirmed') AND check_out >= ?) OR status = 'checked_in'"""
    booking_params = [today]
    if room_id:
        booking_sql = "SELECT * FROM (" + booking_sql + ") WHERE room_id=?"
        booking_params.append(room_id)
    by_room = {}
    for b in conn.execute(booking_sql + " ORDER BY check_in, id", booking_params).fetchall():
        by_room.setdefault(b["room_id"], []).append(b)
    clean = {r["room_id"]: bool(r["is_clean"]) for r in
             conn.execute("SELECT room_id, is_clean FROM room_cleaning WHERE service_date=?", (today,)).fetchall()}

    result = []
    for room in rooms:
        items = by_room.get(room["id"], [])
        active = [b for b in items if b["status"] in ACTIVE_STATUSES]
        due = [b for b in active if b["check_out"] == today or (b["status"] == "checked_in" and b["check_out"] < today)]
        gone = lambda b: b["check_out"] < today or checkout_passed          # ora de check-out a trecut
        leaving = next((b for b in due if not gone(b)), None)
        released = next((b for b in due if gone(b)), None)
        in_stay = next((b for b in active if b["check_in"] < today < b["check_out"]
                        or (b["status"] == "checked_in" and b["check_in"] <= today < b["check_out"])), None)
        arriving = next((b for b in items if b["status"] in ("provisional", "confirmed") and b["check_in"] == today), None)
        future = next((b for b in items if b["status"] in ("provisional", "confirmed") and b["check_in"] > today), None)

        if room["out_of_order"]:
            state, main = "out_of_order", None
        elif leaving:
            state, main = "departing", leaving
        elif in_stay:
            state, main = "occupied", in_stay
        elif arriving:
            state, main = "arriving", arriving
        else:
            state, main = ("vacant_clean" if clean.get(room["id"]) else "vacant_to_check"), None
        # Pentru o cameră liberă, booking-ul principal rămâne gol; sosirea viitoare apare separat.
        shown = main or (arriving if state == "out_of_order" else None)
        next_arrival = today if arriving else (future["check_in"] if future else None)
        occupied_tonight = any(b["status"] in ACTIVE_STATUSES and b["check_in"] <= today < b["check_out"] for b in items)
        result.append({
            "room_id": room["id"], "room_code": room["code"], "room_name": room["name"], "building": room["building"],
            "state": state, "state_label": STATE_LABELS[state], "clean_today": clean.get(room["id"], False),
            "booking_id": shown["id"] if shown else None, "booking_status": shown["status"] if shown else None,
            "guests": shown["guests"] if shown else None,
            "check_in": shown["check_in"] if shown else None, "check_out": shown["check_out"] if shown else None,
            "guest_name": shown["guest_name"] if shown else None,
            "arrival_today": bool(arriving), "departure_today": bool(leaving or released),
            "auto_released": bool(released and not leaving and not room["out_of_order"]),
            "released_event_booking_id": released["id"] if released and released["check_out"] == today else None,
            "checkin_time": checkin_t.strftime("%H:%M"), "checkout_time": checkout_t.strftime("%H:%M"),
            "occupied_tonight": occupied_tonight, "next_arrival_date": next_arrival,
            "out_of_order": bool(room["out_of_order"]), "maintenance_note": room["maintenance_note"],
        })
    return result


def public_view(state):
    return {key: state.get(key) for key in PUBLIC_FIELDS} | {"state_label": state.get("state_label")}


def state_counts(states):
    counts = {}
    for item in states:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return counts


def emit_event(conn, event_type, room_id, booking_id=None, detail=None, actor=None, now=None):
    """Adaugă un eveniment cu starea curentă a camerei. Nu ridică excepții către apelant."""
    room = conn.execute("SELECT id, code FROM rooms WHERE id=?", (room_id,)).fetchone()
    if not room:
        return None
    states = compute_room_states(conn, room_id=room["id"], now=now)
    payload = {"state": public_view(states[0]) if states else None, "detail": detail or {}}
    if actor:
        payload["actor"] = {"id": actor.get("id"), "name": actor.get("name")}  # folosit doar pentru alertele din PMS; nu iese prin API
    cur = conn.execute(
        "INSERT INTO room_events(created_at, event_type, room_id, room_code, booking_id, payload) VALUES (?,?,?,?,?,?)",
        (clock.now().astimezone().isoformat(timespec="seconds"), event_type, room["id"], room["code"], booking_id,
         json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    return cur.lastrowid


def emit_time_events(conn, now=None):
    """Evenimente care apar doar prin trecerea timpului (ex. camera eliberată automat la ora de check-out)."""
    emitted = 0
    for item in compute_room_states(conn, now=now):
        booking_id = item.get("released_event_booking_id")
        if not booking_id or not item["auto_released"]:
            continue
        if conn.execute("SELECT 1 FROM room_events WHERE event_type='room_auto_released' AND booking_id=? LIMIT 1", (booking_id,)).fetchone():
            continue
        emit_event(conn, "room_auto_released", item["room_id"], booking_id, {"checkout_time": item["checkout_time"]}, now=now)
        emitted += 1
    return emitted


_BOOKING_ACTIONS = {"create": "booking_created", "update": "booking_updated", "cancel": "booking_cancelled",
                    "reconfirm": "booking_reconfirmed", "automatic_unconfirmed": "booking_unconfirmed",
                    "night_checkin": "booking_created", "night_reserve": "booking_created", "night_arrived": "booking_updated",
                    "night_cancel": "booking_cancelled", "automatic_late_confirm": "booking_updated"}
_ROOM_ACTIONS = {"room_out_of_order": "room_maintenance_changed", "room_returned_to_service": "room_maintenance_changed",
                 "housekeeping_clean": "room_clean_changed", "housekeeping_uncheck": "room_clean_changed",
                 "deep_clean_submit": "deep_clean_submitted"}
_REQUEST_ACTIONS = {"housekeeping_request_created": "housekeeping_request_created",
                    "housekeeping_request_done": "housekeeping_request_done"}


def _room_of_booking(conn, booking_id):
    row = conn.execute("SELECT room_id FROM bookings WHERE id=?", (booking_id,)).fetchone()
    return row["room_id"] if row else None


def emit_for_audit(conn, action, entity_type, entity_id, details, actor=None):
    """Traduce o acțiune din jurnalul de audit într-unul sau mai multe evenimente de cameră."""
    details = details or {}
    try:
        if entity_type == "booking" and action in _BOOKING_ACTIONS:
            booking_id = int(entity_id)
            room_id = details.get("room_id") or _room_of_booking(conn, booking_id)
            if room_id:
                emit_event(conn, _BOOKING_ACTIONS[action], int(room_id), booking_id,
                           {k: details[k] for k in ("status", "check_in", "check_out") if k in details}, actor)
        elif entity_type == "booking_group" and action in ("create_group", "cancel_group"):
            event_type = "booking_created" if action == "create_group" else "booking_cancelled"
            for booking_id in details.get("booking_ids", []):
                room_id = _room_of_booking(conn, int(booking_id))
                if room_id:
                    emit_event(conn, event_type, room_id, int(booking_id), {"group": True}, actor)
        elif entity_type == "room" and action in _ROOM_ACTIONS:
            emit_event(conn, _ROOM_ACTIONS[action], int(entity_id), None,
                       {"action": action, **{k: details[k] for k in ("is_clean", "date", "done", "total", "has_note", "week") if k in details}}, actor)
        elif entity_type == "housekeeping_request" and action in _REQUEST_ACTIONS and details.get("room_id"):
            emit_event(conn, _REQUEST_ACTIONS[action], int(details["room_id"]), None,
                       {"type": details.get("type"), "request_id": int(entity_id)}, actor)
    except (ValueError, TypeError, KeyError):
        return None
    return True
