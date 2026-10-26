"""Recepția de noapte: stări de cameră pentru noapte, sosiri târzii și acțiunile permise. Fără dependență de Flask.

Reguli:
- Programul recepției de zi se încheie la 21:00 (MOTEL_RECEPTION_CLOSE); recepția de noapte lucrează 21:00–06:00 (MOTEL_NIGHT_START / MOTEL_NIGHT_END).
- Recepția de noapte vede doar starea camerelor (fără detalii). Singurele detalii vizibile sunt numele și telefonul sosirilor târzii.
- O cameră ocupată de recepția de noapte NU mai poate fi modificată de aceasta: starea o schimbă aplicația (ora de check-out), recepția de zi sau administratorul.
- Cazările făcute noaptea sunt pentru o singură noapte; prelungirile se fac la recepția de zi.
"""
import os
from datetime import date, datetime, time as dtime, timedelta

import clock
import settings

now_fn = clock.now  # ceas injectabil (teste)
SOURCE = "Recepție noapte"
OPEN_STATUSES = ("confirmed", "provisional", "unconfirmed")      # rezervări care încă nu au sosit
PAYMENTS = {"cash": "Încasat cash", "morning": "Se încasează la recepție dimineața"}
NAME_MIN, NAME_MAX = 2, 80


def _hhmm(name, default):
    try:
        hh, mm = os.environ.get(name, "").split(":")
        return dtime(int(hh), int(mm))
    except ValueError:
        return default


def window():
    """Programul de noapte: setat de administrator, apoi MOTEL_NIGHT_START / MOTEL_NIGHT_END, implicit 21:00–06:00."""
    return settings.time_value("night_start"), settings.time_value("night_end")


def reception_close():
    return settings.time_value("reception_close")


def is_night(now):
    start, end = window()
    return now.time() >= start or now.time() < end


def night_date(now):
    """Data în care a început noaptea: după miezul nopții, tot noaptea de ieri."""
    _, end = window()
    return now.date() - timedelta(days=1) if now.time() < end else now.date()


def default_rate(room):
    """Tariful camerei; dacă lipsește, tariful implicit din MOTEL_NIGHT_DEFAULT_RATE (0 = nesetat)."""
    rate = float(room["default_rate"] or 0)
    if rate > 0:
        return rate
    try:
        return max(0.0, float(os.environ.get("MOTEL_NIGHT_DEFAULT_RATE", "0")))
    except ValueError:
        return 0.0


def _is_late(booking, night_iso):
    return booking["check_in"] == night_iso and booking["status"] in OPEN_STATUSES and (
        booking["late_arrival"] or booking["status"] == "unconfirmed")


def grid(conn, night):
    """Starea fiecărei camere pentru noaptea `night`: free | occupied | reserved | late | out_of_order, fără detalii personale."""
    night_iso = night.isoformat()
    rooms = conn.execute("""SELECT id, name, building, out_of_order, default_rate FROM rooms WHERE active=1
        ORDER BY CASE building WHEN 'Corp A' THEN 1 WHEN 'Corp B' THEN 2 WHEN 'Corp C' THEN 3 ELSE 4 END, sort_order, name""").fetchall()
    by_room = {}
    for b in conn.execute("""SELECT id, room_id, check_in, check_out, status, late_arrival FROM bookings
                             WHERE status != 'cancelled' AND check_out > ?""", (night_iso,)).fetchall():
        by_room.setdefault(b["room_id"], []).append(b)
    rank = {"occupied": 3, "late": 2, "reserved": 1}
    result = []
    for room in rooms:
        state = "free"
        for b in by_room.get(room["id"], []):
            if not (b["check_in"] <= night_iso < b["check_out"]):
                continue
            if b["status"] in ("checked_in", "checked_out") or b["check_in"] < night_iso:
                candidate = "occupied"
            elif _is_late(b, night_iso):
                candidate = "late"
            else:
                candidate = "reserved"
            if state == "free" or rank[candidate] > rank.get(state, 0):
                state = candidate
        if room["out_of_order"]:
            state = "out_of_order"
        rate = default_rate(room)
        result.append({"room_id": room["id"], "name": room["name"], "building": room["building"], "state": state,
                       "rate": rate, "can_sell": state == "free" and rate > 0})
    return result


def late_arrivals(conn, night):
    """Sosirile după ora 21:00: nume, telefon, observații. Singurele detalii personale pe care le vede recepția de noapte."""
    night_iso = night.isoformat()
    rows = conn.execute("""SELECT b.id, b.room_id, b.guest_name, b.phone, b.guests, b.status, b.night_note, b.late_arrival, r.name AS room_name,
                                  r.building, r.out_of_order
        FROM bookings b JOIN rooms r ON r.id=b.room_id
        WHERE r.active=1 AND b.check_in=? AND b.status IN ('confirmed','provisional','unconfirmed') AND (b.late_arrival=1 OR b.status='unconfirmed')
        ORDER BY r.building, r.sort_order, r.name""", (night_iso,)).fetchall()
    items = []
    for row in rows:
        clash = conn.execute("""SELECT 1 FROM bookings WHERE room_id=? AND id!=? AND status IN ('confirmed','provisional','checked_in')
                                AND check_in < date(?, '+1 day') AND check_out > ? LIMIT 1""", (row["room_id"], row["id"], night_iso, night_iso)).fetchone()
        item = dict(row)
        item["conflict"] = bool(clash)
        item["blocked"] = bool(clash) or bool(row["out_of_order"])
        items.append(item)
    return items


def _clean_name(name):
    name = " ".join(str(name or "").split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        return None
    return name


def _guests(value):
    try:
        number = int(str(value or "").strip())
    except ValueError:
        return None
    return number if number in (1, 2) else None


def _insert(conn, room, night, name, guests, status, late, payment, user, color):
    now = now_fn().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("""INSERT INTO bookings(guest_name, phone, email, room_id, check_in, check_out, guests, rate, deposit, source, status, notes,
                              created_by, created_by_name, created_by_color, late_arrival, night_payment, night_by, night_at)
        VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?)""",
        (name, "", "", room["id"], night.isoformat(), (night + timedelta(days=1)).isoformat(), guests, default_rate(room), SOURCE, status,
         "Creată de recepția de noapte", user["id"], user["display_name"], color, 1 if late else 0, payment, user["id"], now))
    return cur.lastrowid


def create_for_free_room(conn, room_id, night, mode, name, guests, payment, user, color):
    """mode='occupy' (cazare acum, plata obligatorie) sau 'reserve' (vine mai târziu). Întoarce (ok, mesaj, booking_id)."""
    name = _clean_name(name)
    guests = _guests(guests)
    if not name:
        return False, f"Introduceți numele (între {NAME_MIN} și {NAME_MAX} caractere).", None
    if guests is None:
        return False, "Alegeți numărul de persoane din cameră (1 sau 2).", None
    if mode not in ("occupy", "reserve"):
        return False, "Acțiune invalidă.", None
    if mode == "occupy" and payment not in PAYMENTS:
        return False, "Alegeți cum se plătește: cash acum sau la recepție dimineața.", None
    conn.execute("BEGIN IMMEDIATE")
    try:
        room = conn.execute("SELECT id, name, out_of_order, default_rate FROM rooms WHERE id=? AND active=1", (room_id,)).fetchone()
        if not room or room["out_of_order"]:
            conn.rollback()
            return False, "Camera nu este disponibilă.", None
        if default_rate(room) <= 0:
            conn.rollback()
            return False, f"Tariful camerei {room['name']} nu este setat. Anunțați administratorul.", None
        clash = conn.execute("""SELECT 1 FROM bookings WHERE room_id=? AND status != 'cancelled' AND check_in < date(?, '+1 day') AND check_out > ? LIMIT 1""",
                             (room["id"], night.isoformat(), night.isoformat())).fetchone()
        if clash:
            conn.rollback()
            return False, f"Camera {room['name']} nu mai este liberă. Reîncărcați pagina.", None
        booking_id = _insert(conn, room, night, name, guests, "checked_in" if mode == "occupy" else "confirmed",
                             mode == "reserve", payment if mode == "occupy" else None, user, color)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    verb = "cazată" if mode == "occupy" else "rezervată"
    return True, f"Camera {room['name']} a fost {verb} pe numele {name}.", booking_id


def _late_booking(conn, booking_id, night):
    row = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not row or not _is_late(row, night.isoformat()):
        return None
    return row


def mark_arrived(conn, booking_id, night, payment, user):
    """Sosire târzie confirmată: devine „cazat” și nu mai poate fi modificată de recepția de noapte."""
    if payment not in PAYMENTS:
        return False, "Alegeți cum se plătește: cash acum sau la recepție dimineața.", None
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _late_booking(conn, booking_id, night)
        if not row:
            conn.rollback()
            return False, "Rezervarea nu mai este în lista sosirilor târzii.", None
        clash = conn.execute("""SELECT 1 FROM bookings WHERE room_id=? AND id!=? AND status IN ('confirmed','provisional','checked_in')
                                AND check_in < ? AND check_out > ? LIMIT 1""", (row["room_id"], row["id"], row["check_out"], row["check_in"])).fetchone()
        room = conn.execute("SELECT name, out_of_order FROM rooms WHERE id=?", (row["room_id"],)).fetchone()
        if clash or room["out_of_order"]:
            conn.rollback()
            return False, f"Camera {room['name']} nu poate fi ocupată: are altă rezervare sau este defectă.", None
        conn.execute("""UPDATE bookings SET status='checked_in', late_arrival=1, night_payment=?, night_by=?, night_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                     (payment, user["id"], now_fn().strftime("%Y-%m-%d %H:%M:%S"), booking_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True, f"Camera {room['name']} a fost cazată ({row['guest_name']}).", row


def cancel_late(conn, booking_id, night, user):
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _late_booking(conn, booking_id, night)
        if not row:
            conn.rollback()
            return False, "Rezervarea nu mai poate fi anulată de la recepția de noapte.", None
        room = conn.execute("SELECT name FROM rooms WHERE id=?", (row["room_id"],)).fetchone()
        conn.execute("UPDATE bookings SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True, f"Rezervarea pentru camera {room['name']} a fost anulată; camera este liberă.", row


def confirm_late_unconfirmed(conn, today_iso):
    """La încheierea programului recepției de zi, rezervările neconfirmate cu sosire azi devin „vin după ora 21”.
    Dacă între timp camera a fost dată altcuiva, rezervarea rămâne neconfirmată (apare în listă cu avertisment)."""
    done = []
    for row in conn.execute("SELECT id, room_id, check_in, check_out FROM bookings WHERE status='unconfirmed' AND check_in=?", (today_iso,)).fetchall():
        clash = conn.execute("""SELECT 1 FROM bookings WHERE room_id=? AND id!=? AND status IN ('confirmed','provisional','checked_in')
                                AND check_in < ? AND check_out > ? LIMIT 1""", (row["room_id"], row["id"], row["check_out"], row["check_in"])).fetchone()
        if clash:
            continue
        conn.execute("UPDATE bookings SET status='confirmed', late_arrival=1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        done.append(row["id"])
    return done


def night_note_allowed(status, late_arrival, check_in, today_iso):
    """Observațiile pentru recepția de noapte se pot adăuga doar pentru sosiri după ora 21:00."""
    return bool(late_arrival) or (status == "unconfirmed" and check_in == today_iso)
