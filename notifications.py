"""Alerte între recepție și cameriste, construite din coada de evenimente (room_events).

Fără dependență de Flask. Fiecare persoană primește doar ce o privește și nu primește alerte
pentru acțiunile proprii. Evenimentele mai vechi de 30 de minute nu mai generează alerte.
"""
import json
from datetime import datetime, timedelta

import clock

MAX_AGE = timedelta(minutes=30)
FETCH_LIMIT = 200
MAX_ITEMS = 20
SERVICE_LABELS = {"cleaning": "Curățenie", "towels": "Schimb prosoape", "toilet_paper": "Hârtie igienică"}
SERVICE_ORDER = ["cleaning", "towels", "toilet_paper"]


def parse_services(value):
    """'both' (vechi) = curățenie + prosoape; altfel o listă separată prin virgulă."""
    parts = ["cleaning", "towels"] if value == "both" else [p for p in str(value or "").split(",") if p]
    return [p for p in SERVICE_ORDER if p in parts]


def service_label(value):
    parts = parse_services(value)
    return " + ".join(SERVICE_LABELS[p] for p in parts) if parts else str(value or "Serviciu")


def audience_for(staff_type):
    return "housekeeping" if staff_type == "housekeeping" else "reception"


def _item(row, kind, priority, title, text, request_id=None):
    return {"id": row["id"], "kind": kind, "priority": priority, "title": title, "text": text,
            "room": row["room_name"], "request_id": request_id, "created_at": row["created_at"]}


def _to_item(conn, row, audience, user_id, now):
    payload = json.loads(row["payload"])
    detail = payload.get("detail") or {}
    actor = payload.get("actor") or {}
    if user_id is not None and actor.get("id") == user_id:
        return None  # acțiunea proprie nu generează alertă
    try:
        if now - datetime.fromisoformat(row["created_at"]) > MAX_AGE:
            return None
    except ValueError:
        return None
    who = actor.get("name") or ("Recepție" if audience == "housekeeping" else "Cameristă")
    room = row["room_name"]
    event_type = row["event_type"]

    if event_type == "housekeeping_request_created" and audience == "housekeeping":
        req = conn.execute("SELECT request_type, note, status FROM housekeeping_requests WHERE id=?",
                           (detail.get("request_id"),)).fetchone()
        if not req or req["status"] != "open":
            return None
        text = f"Camera {room} · {service_label(req['request_type'])}"
        if req["note"]:
            text += f" — {req['note']}"
        return _item(row, "request_created", "urgent", "Solicitare nouă de la recepție", f"{text} (de la {who})",
                     detail.get("request_id"))
    if event_type == "housekeeping_request_done" and audience == "reception":
        label = service_label(detail.get("type"))
        return _item(row, "request_done", "normal", "Solicitare rezolvată", f"Camera {room} · {label} · rezolvat de {who}",
                     detail.get("request_id"))
    if event_type == "room_clean_changed" and audience == "reception":
        if detail.get("is_clean"):
            return _item(row, "room_clean", "normal", "Cameră pregătită", f"Camera {room} a fost marcată curată de {who}.")
        return _item(row, "room_unclean", "normal", "Cameră redeschisă", f"Camera {room} a fost debifată de {who} și trebuie verificată din nou.")
    if event_type == "booking_updated" and audience == "housekeeping" and detail.get("status") == "checked_out":
        earlier = conn.execute("""SELECT 1 FROM room_events WHERE booking_id=? AND id<? AND event_type='booking_updated'
                                  AND payload LIKE '%"status": "checked_out"%' LIMIT 1""", (row["booking_id"], row["id"])).fetchone()
        if earlier:
            return None  # editare ulterioară a unei rezervări deja încheiate
        return _item(row, "checkout", "normal", "Cameră eliberată", f"Camera {room} a fost eliberată la recepție și poate fi curățată.")
    if event_type == "room_auto_released":
        when = detail.get("checkout_time", "13:00")
        if audience == "housekeeping":
            return _item(row, "auto_release", "normal", "Cameră eliberată automat",
                         f"Camera {room}: ora de check-out ({when}) a trecut · poate fi curățată.")
        return _item(row, "auto_release", "normal", "Check-out neconfirmat",
                     f"Camera {room} a fost eliberată automat la {when}. Finalizați check-out-ul în PMS.")
    if event_type == "deep_clean_submitted" and audience == "reception":
        note = ""
        if detail.get("has_note"):
            r = conn.execute("SELECT note FROM deep_clean_reports WHERE week_start=? AND room_id=?", (detail.get("week"), row["room_id"])).fetchone()
            note = f" Observații: {r['note']}" if r and r["note"] else ""
        return _item(row, "deep_clean", "normal", "Curățenie extinsă trimisă",
                     f"Camera {room}: {detail.get('done', '?')}/{detail.get('total', '?')} puncte, de {who}.{note}")
    if event_type == "room_maintenance_changed" and audience == "housekeeping":
        if detail.get("action") == "room_out_of_order":
            return _item(row, "maintenance", "normal", "Cameră defectă", f"Camera {room} este blocată de mentenanță; nu se marchează curată.")
        return _item(row, "maintenance", "normal", "Cameră revenită în service", f"Camera {room} poate fi din nou pregătită pentru cazare.")
    return None


def feed(conn, audience, user_id, after_id=None, now=None):
    """Alertele noi pentru o persoană. Fără `after_id` întoarce doar punctul de plecare (fără alerte vechi)."""
    now = now or clock.now().astimezone()
    last_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM room_events").fetchone()[0]
    open_ids = [r["id"] for r in conn.execute("SELECT id FROM housekeeping_requests WHERE status='open'").fetchall()]
    if after_id is None:
        return {"last_id": last_id, "items": [], "open_request_ids": open_ids}
    rows = conn.execute("""SELECT e.*, r.name AS room_name FROM room_events e JOIN rooms r ON r.id = e.room_id
                           WHERE e.id > ? ORDER BY e.id LIMIT ?""", (after_id, FETCH_LIMIT)).fetchall()
    if len(rows) == FETCH_LIMIT:
        last_id = rows[-1]["id"]  # restul se preia la interogarea următoare
    items = [i for i in (_to_item(conn, row, audience, user_id, now) for row in rows) if i]
    return {"last_id": last_id, "items": items[-MAX_ITEMS:], "open_request_ids": open_ids}
