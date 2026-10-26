"""Pontaj cameriste: cât timp stau conectate în aplicație. Fără dependență de Flask.

Se înregistrează doar orele de conectare. O pauză mai lungă de 10 minute fără activitate închide perioada curentă
(telefon blocat, pagină închisă) și următoarea activitate începe o perioadă nouă, deci pauzele nu se numără ca timp conectat."""
import csv
import io
from datetime import date, datetime, timedelta

from safety import csv_safe

import clock

now_fn = clock.now
FMT = "%Y-%m-%d %H:%M:%S"
IDLE_GAP = timedelta(minutes=10)


def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS staff_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, day TEXT NOT NULL,
        login_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, logout_at TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_staff_sessions_day ON staff_sessions(day, user_id)")


def _parse(value):
    return datetime.strptime(value, FMT)


def start_session(conn, user):
    ts = now_fn()
    cur = conn.execute("INSERT INTO staff_sessions(user_id, user_name, day, login_at, last_seen_at) VALUES (?,?,?,?,?)",
                       (user["id"], user["display_name"], ts.date().isoformat(), ts.strftime(FMT), ts.strftime(FMT)))
    return cur.lastrowid


def touch_or_start(conn, session_id, user):
    """Actualizează ultima activitate; începe o perioadă nouă dacă nu există una sau a fost o pauză lungă."""
    ts = now_fn()
    row = conn.execute("SELECT id, day, last_seen_at, logout_at FROM staff_sessions WHERE id=? AND user_id=?",
                       (session_id, user["id"])).fetchone() if session_id else None
    if (not row or row["logout_at"] or row["day"] != ts.date().isoformat()
            or ts - _parse(row["last_seen_at"]) > IDLE_GAP):
        return start_session(conn, user)
    conn.execute("UPDATE staff_sessions SET last_seen_at=? WHERE id=?", (ts.strftime(FMT), row["id"]))
    return row["id"]


def end_session(conn, session_id):
    if session_id:
        stamp = now_fn().strftime(FMT)
        conn.execute("UPDATE staff_sessions SET logout_at=?, last_seen_at=? WHERE id=? AND logout_at IS NULL", (stamp, stamp, session_id))


def fmt_duration(seconds):
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _union_seconds(intervals):
    total, current_end = 0.0, None
    for start, end in sorted(intervals):
        if current_end is None or start > current_end:
            total += (end - start).total_seconds()
            current_end = end
        elif end > current_end:
            total += (end - current_end).total_seconds()
            current_end = end
    return total


def summarize_day(conn, day):
    """Pe cameristă: prima autentificare, ultima activitate, intervalul total și timpul conectat efectiv."""
    rows = conn.execute("SELECT * FROM staff_sessions WHERE day=? ORDER BY user_name, login_at", (day,)).fetchall()
    grouped = {}
    for row in rows:
        start = _parse(row["login_at"])
        end = max(start, _parse(row["logout_at"] or row["last_seen_at"]))
        grouped.setdefault((row["user_id"], row["user_name"]), []).append((start, end))
    result = []
    for (user_id, name), intervals in grouped.items():
        first = min(s for s, _ in intervals)
        last = max(e for _, e in intervals)
        connected = _union_seconds(intervals)
        result.append({"user_id": user_id, "name": name, "first": first.strftime("%H:%M"), "last": last.strftime("%H:%M"),
                       "span_seconds": (last - first).total_seconds(), "span": fmt_duration((last - first).total_seconds()),
                       "connected_seconds": connected, "connected": fmt_duration(connected), "periods": len(intervals)})
    return sorted(result, key=lambda item: item["name"].lower())


def week_totals(conn, monday):
    """Timp conectat pe zile, luni–duminică, pentru fiecare cameristă."""
    days = [monday + timedelta(days=i) for i in range(7)]
    table = {}
    for day in days:
        for item in summarize_day(conn, day.isoformat()):
            entry = table.setdefault(item["user_id"], {"name": item["name"], "days": {}, "total": 0.0})
            entry["days"][day.isoformat()] = item["connected_seconds"]
            entry["total"] += item["connected_seconds"]
    for entry in table.values():
        entry["total_label"] = fmt_duration(entry["total"])
        entry["day_labels"] = {d: fmt_duration(s) for d, s in entry["days"].items()}
    return days, sorted(table.values(), key=lambda e: e["name"].lower())


def month_csv(conn, year, month):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Data", "Cameristă", "Prima autentificare", "Ultima activitate", "Interval total", "Timp conectat", "Perioade"])
    prefix = f"{year:04d}-{month:02d}-"
    days = [r["day"] for r in conn.execute("SELECT DISTINCT day FROM staff_sessions WHERE day LIKE ? ORDER BY day", (prefix + "%",)).fetchall()]
    for day in days:
        for item in summarize_day(conn, day):
            writer.writerow([day, csv_safe(item["name"]), item["first"], item["last"], item["span"], item["connected"], item["periods"]])
    return "\ufeff" + buffer.getvalue()
