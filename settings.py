"""Setări administrate din aplicație: module pornite/oprite și ore. Prioritate: valoarea salvată de administrator,
apoi variabila de mediu, apoi valoarea implicită."""
import os
import re
from datetime import time as dtime

# cheie, titlu, descriere, implicit
MODULES = [
    ("mod_reconfirm", "Reconfirmări de seară", "Panoul de reconfirmare de pe prima pagină și trecerea automată la „Neconfirmată” la ora reconfirmării.", True),
    ("mod_late_confirm", "Confirmare automată „vine după 21:00”", "La închiderea recepției de zi, neconfirmatele cu sosire azi apar la recepția de noapte.", True),
    ("mod_room_board", "Starea camerelor acum", "Panoul cu camerele colorate după stare, de pe prima pagină.", True),
    ("mod_housekeeping_comm", "Comunicare cu cameristele", "Panoul de solicitări de pe prima pagină și butonul „Solicită serviciu”.", True),
    ("mod_alerts", "Alerte sonore și text", "Alertele dintre recepție și cameriste.", True),
    ("mod_deep_clean", "Curățenie extinsă săptămânală", "Formularul pentru cameriste și rapoartele pentru recepție.", True),
    ("mod_night_desk", "Recepție de noapte", "Pagina pentru telefonul de noapte.", True),
    ("night_time_restriction", "Restricție orară la recepția de noapte", "Acțiunile recepției de noapte sunt permise doar în programul de noapte.", True),
    ("mod_night_pending", "De încasat dimineața", "Lista cazărilor de noapte cu plata la recepție, de pe prima pagină.", True),
    ("mod_upcoming", "Rezervări viitoare și căutare rapidă", "Lista de pe prima pagină.", True),
    ("mod_timesheet", "Pontaj cameriste", "Înregistrarea timpului conectat și pagina de pontaj.", True),
    ("mod_shift_report", "Raport șef de tură", "Raportul de ocupare al nopții precedente.", True),
    ("admin_2fa_required", "Autentificare în 2 pași pentru administratori", "Administratorii introduc și un cod din aplicația de autentificare de pe telefon.", True),
]
# cheie, titlu, variabilă de mediu, implicit
TIMES = [
    ("reconfirm_time", "Ora reconfirmării de seară", "MOTEL_RECONFIRM_TIME", "20:30"),
    ("reception_close", "Închiderea recepției de zi", "MOTEL_RECEPTION_CLOSE", "21:00"),
    ("night_start", "Începutul recepției de noapte", "MOTEL_NIGHT_START", "21:00"),
    ("night_end", "Sfârșitul recepției de noapte", "MOTEL_NIGHT_END", "06:00"),
    ("backup_time", "Ora copiei de siguranță automate", "MOTEL_BACKUP_TIME", "03:00"),
]
NUMBERS = [("backup_keep_days", "Câte zile se păstrează copiile automate", 30, 1, 365)]
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

connect = None          # setat de aplicație
_cache = None


def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL,
                    updated_by TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def _values():
    global _cache
    if _cache is None:
        if connect is None:
            return {}
        conn = connect()
        try:
            _cache = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_settings").fetchall()}
        except Exception:
            _cache = {}
        finally:
            conn.close()
    return _cache


def invalidate():
    global _cache
    _cache = None


def enabled(key):
    default = next((d for k, _, _, d in MODULES if k == key), True)
    value = _values().get(key)
    return default if value is None else value == "1"


def time_text(key):
    _, _, env, default = next(t for t in TIMES if t[0] == key)
    for value in (_values().get(key), os.environ.get(env, "")):
        if value and HHMM.fullmatch(value):
            return value
    return default


def time_value(key):
    hh, mm = time_text(key).split(":")
    return dtime(int(hh), int(mm))


def number(key):
    _, _, default, low, high = next(n for n in NUMBERS if n[0] == key)
    try:
        return max(low, min(high, int(_values().get(key, default))))
    except ValueError:
        return default


def modules_state():
    return {k: enabled(k) for k, _, _, _ in MODULES}


def save(conn, values, user_name):
    """values = {cheie: str}. Validează tot înainte de a salva; întoarce (ok, mesaj, chei_modificate)."""
    known_mod = {k for k, *_ in MODULES}
    known_time = {k for k, *_ in TIMES}
    known_num = {k: (lo, hi) for k, _, _, lo, hi in NUMBERS}
    clean = {}
    for key, value in values.items():
        if key in known_mod:
            clean[key] = "1" if value in ("1", True, "on") else "0"
        elif key in known_time:
            if not HHMM.fullmatch(str(value)):
                return False, f"Ora pentru „{key}” trebuie să fie de forma HH:MM.", []
            clean[key] = value
        elif key in known_num:
            try:
                number_value = int(value)
            except (TypeError, ValueError):
                return False, "Valoare numerică invalidă.", []
            lo, hi = known_num[key]
            if not lo <= number_value <= hi:
                return False, f"Valoarea trebuie să fie între {lo} și {hi}.", []
            clean[key] = str(number_value)
        else:
            return False, "Setare necunoscută.", []
    current = _values() if connect else {}
    changed = [k for k, v in clean.items() if current.get(k) != v]
    for key in changed:
        conn.execute("""INSERT INTO app_settings(key, value, updated_by, updated_at) VALUES (?,?,?,CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP""",
                     (key, clean[key], user_name))
    invalidate()
    return True, "Setările au fost salvate.", changed
