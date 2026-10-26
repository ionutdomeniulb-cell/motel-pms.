"""Administrare din consola PC-ului (necesită acces fizic la PC):
    python manage.py reset-2fa <utilizator>   – dezactivează autentificarea în 2 pași (telefon pierdut)
    python manage.py backup                   – copie de siguranță imediată, verificată
    python manage.py users                    – lista utilizatorilor
"""
import sys

import app


def main(argv):
    if len(argv) < 2 or argv[1] not in ("reset-2fa", "backup", "users"):
        print(__doc__)
        return 2
    conn = app.connect()
    if argv[1] == "users":
        for row in conn.execute("SELECT username, display_name, role, staff_type, active, totp_enabled FROM users ORDER BY username"):
            print(f"{row['username']:<16} {row['display_name']:<24} {row['role']:<10} {row['staff_type'] or '':<16} activ={row['active']} 2pasi={row['totp_enabled']}")
        return 0
    if argv[1] == "backup":
        result = app.backup.run(app.DB_PATH, app.backup.folder(app.DB_PATH), app.settings.number("backup_keep_days"), app.clock.now())
        print(f"Copie salvată și verificată: {result['path']} ({result['bookings']} rezervări)")
        return 0
    if len(argv) != 3:
        print("Utilizare: python manage.py reset-2fa <utilizator>")
        return 2
    cur = conn.execute("UPDATE users SET totp_secret=NULL, totp_enabled=0, totp_last_step=NULL, totp_recovery='[]', session_epoch=session_epoch+1 WHERE username=?", (argv[2].lower(),))
    if not cur.rowcount:
        print("Utilizator inexistent.")
        return 1
    conn.execute("INSERT INTO audit_log(user_id, username, action, entity_type, entity_id, details, ip_address, created_at) VALUES (NULL, 'consola', 'totp_reset_cli', 'user', NULL, ?, '', ?)",
                 (app.json.dumps({"username": argv[2].lower()}), app.clock.now().isoformat(timespec="seconds")))
    print(f"Autentificarea în 2 pași a fost resetată pentru {argv[2]}. La următoarea autentificare o va configura din nou.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
