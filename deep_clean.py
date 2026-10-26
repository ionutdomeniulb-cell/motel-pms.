"""Formular săptămânal de curățenie extinsă (cameriste → recepție). Fără dependență de Flask."""
import json
import os
import re
from datetime import date, timedelta

import clock

ITEMS = [
    ("spiders", "Păianjeni și pânze", "Colțuri, tavan, în spatele mobilierului"),
    ("beds", "Paturi trase și aspirat dedesubt", "Trase de la perete; aspirat sub pat, noptiere și dulap"),
    ("dust", "Praf", "Mobilier, rafturi, tablouri, plinte, tocul ușilor"),
    ("radiators", "Calorifere curățate", "Față, spate și între elemenți"),
    ("shower", "Cabină de duș, curățare extinsă", "Rosturi, calcar, sifon, garnituri, pară de duș"),
    ("windows", "Geamuri, oglinzi și pervazuri", ""),
    ("plants", "Flori udate", "Bifați și dacă în cameră nu sunt flori"),
    ("textiles", "Perdele, covorașe și saltele controlate", "Pete, miros, aerisire"),
]
ITEM_KEYS = [k for k, _, _ in ITEMS]
NOTE_MAX = 500


def max_occupied():
    """Pragul de ocupare redusă (implicit 4 camere ocupate); se schimbă cu MOTEL_DEEPCLEAN_MAX_OCCUPIED."""
    try:
        return max(0, int(os.environ.get("MOTEL_DEEPCLEAN_MAX_OCCUPIED", "4")))
    except ValueError:
        return 4


def week_start(day):
    return (day - timedelta(days=day.weekday())).isoformat()


def migrate(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deep_clean_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            room_id INTEGER NOT NULL REFERENCES rooms(id),
            items TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','sent')),
            updated_by INTEGER,
            updated_by_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            UNIQUE(week_start, room_id)
        )""")


def migrate_request_types(conn):
    """Elimină restricția veche asupra tipului de solicitare (cleaning/towels/both) ca să existe și hârtia igienică."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='housekeeping_requests'").fetchone()
    if not row or "request_type IN" not in row["sql"]:
        return False
    new_sql = re.sub(r"\s*CHECK\s*\(\s*request_type\s+IN\s*\([^)]*\)\s*\)", "", row["sql"])
    conn.execute("BEGIN")
    try:
        conn.execute("ALTER TABLE housekeeping_requests RENAME TO housekeeping_requests_old")
        conn.execute(new_sql)
        conn.execute("INSERT INTO housekeeping_requests SELECT * FROM housekeeping_requests_old")
        conn.execute("DROP TABLE housekeeping_requests_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_housekeeping_requests_day_status ON housekeeping_requests(service_date, status)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return True


def reports_for_week(conn, week):
    result = {}
    for row in conn.execute("SELECT * FROM deep_clean_reports WHERE week_start=?", (week,)).fetchall():
        item = dict(row)
        item["items"] = json.loads(row["items"] or "{}")
        item["done"] = sum(1 for key in ITEM_KEYS if item["items"].get(key))
        result[row["room_id"]] = item
    return result


def eligibility(state):
    """Motivul pentru care o cameră nu poate fi curățată extins acum (None = poate)."""
    if state["out_of_order"]:
        return "defectă"
    if state["occupied_tonight"]:
        return "ocupată sau cu sosire astăzi"
    if state["state"] == "departing":
        return "plecare nefinalizată"
    return None


def due_info(conn, states, day=None):
    """Dacă formularul trebuie oferit cameristelor azi: ocupare redusă și camere rămase de făcut în săptămâna curentă."""
    day = day or clock.today()
    occupied = sum(1 for s in states if s["occupied_tonight"])
    reports = reports_for_week(conn, week_start(day))
    sent = sum(1 for r in reports.values() if r["status"] == "sent")
    remaining = [s for s in states if eligibility(s) is None and reports.get(s["room_id"], {}).get("status") != "sent"]
    low = occupied <= max_occupied()
    return {"occupied": occupied, "max": max_occupied(), "low_occupancy": low, "sent": sent, "total": len(states),
            "remaining": len(remaining), "due": low and bool(remaining)}


def save_report(conn, week, room_id, checked, note, user, send):
    items = {key: (key in checked) for key in ITEM_KEYS}
    done = sum(items.values())
    note = (note or "").strip()[:NOTE_MAX]
    status = "sent" if send else "draft"
    conn.execute("""INSERT INTO deep_clean_reports(week_start, room_id, items, note, status, updated_by, updated_by_name, updated_at, sent_at)
        VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP, CASE WHEN ?='sent' THEN CURRENT_TIMESTAMP END)
        ON CONFLICT(week_start, room_id) DO UPDATE SET items=excluded.items, note=excluded.note, status=excluded.status,
        updated_by=excluded.updated_by, updated_by_name=excluded.updated_by_name, updated_at=CURRENT_TIMESTAMP,
        sent_at=CASE WHEN excluded.status='sent' THEN CURRENT_TIMESTAMP ELSE deep_clean_reports.sent_at END""",
        (week, room_id, json.dumps(items, sort_keys=True), note, status, user["id"], user["display_name"], status))
    return {"done": done, "total": len(ITEM_KEYS), "has_note": bool(note), "status": status}
