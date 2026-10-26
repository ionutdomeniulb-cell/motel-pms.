"""Copii de siguranță automate ale bazei de date (funcționează cu aplicația pornită) + verificare de integritate + rotație."""
import os
import re
import sqlite3
from datetime import datetime, timedelta

NAME = re.compile(r"motel_(\d{4}-\d{2}-\d{2}_\d{4})\.db$")


def folder(db_path):
    return os.environ.get("MOTEL_BACKUP_DIR") or os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups", "auto")


def list_backups(dest):
    items = []
    if os.path.isdir(dest):
        for name in os.listdir(dest):
            match = NAME.match(name)
            if match:
                path = os.path.join(dest, name)
                items.append({"name": name, "path": path, "size": os.path.getsize(path),
                              "time": datetime.strptime(match.group(1), "%Y-%m-%d_%H%M")})
    return sorted(items, key=lambda i: i["time"], reverse=True)


def run(db_path, dest, keep_days, now):
    """Copie consistentă (API-ul de backup SQLite), verificată cu integrity_check; apoi șterge copiile automate mai vechi de keep_days."""
    os.makedirs(dest, exist_ok=True)
    target = os.path.join(dest, f"motel_{now.strftime('%Y-%m-%d_%H%M')}.db")
    temp = target + ".tmp"
    source = sqlite3.connect(db_path)
    copy = sqlite3.connect(temp)
    try:
        source.backup(copy)
        ok = copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        bookings = copy.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    finally:
        copy.close()
        source.close()
    if not ok:
        os.remove(temp)
        raise RuntimeError("Copia de siguranță nu a trecut verificarea de integritate.")
    os.replace(temp, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    removed = 0
    for item in list_backups(dest):
        if item["time"] < now - timedelta(days=keep_days):
            os.remove(item["path"])
            removed += 1
    return {"path": target, "size": os.path.getsize(target), "bookings": bookings, "removed": removed}


def needed(dest, now, backup_time):
    """O copie pe zi, după ora setată; dacă PC-ul a fost oprit la acea oră, copia se face la prima ocazie (după 26 h)."""
    items = list_backups(dest)
    if not items:
        return True
    latest = items[0]["time"]
    if now - latest > timedelta(hours=26):
        return True
    return latest.date() < now.date() and now.time() >= backup_time
