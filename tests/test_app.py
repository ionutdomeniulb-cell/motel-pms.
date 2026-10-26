"""Smoke tests for the Popas Căprioara PMS. Run with: python -m unittest discover -s tests -v"""
import json
import os
import re
import tempfile
import unittest
import urllib.parse

_fd, _db_path = tempfile.mkstemp(prefix="motel-pms-test-", suffix=".sqlite3")
os.close(_fd)
os.environ["MOTEL_DB_PATH"] = _db_path
os.environ["MOTEL_SECRET_KEY"] = "test-only-secret"
_fd_audit, _audit_path = tempfile.mkstemp(prefix="motel-pms-audit-test-", suffix=".log")
os.close(_fd_audit)
os.environ["MOTEL_AUDIT_FILE"] = _audit_path

import app as pms  # noqa: E402


class PMSAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = pms.app.test_client()
        conn = pms.connect()
        conn.execute("INSERT INTO users(username, display_name, pin_hash, role) VALUES (?, ?, ?, 'admin')",
                     ("admin", "Administrator test", pms.generate_password_hash("123456")))
        conn.close()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        conn = pms.connect()
        conn.execute("DELETE FROM invoice_attempts")
        conn.execute("DELETE FROM invoices")
        conn.execute("DELETE FROM bookings")
        conn.execute("DELETE FROM housekeeping_requests")
        conn.execute("DELETE FROM room_cleaning")
        conn.execute("DELETE FROM room_events")
        conn.execute("DELETE FROM staff_sessions")
        conn.execute("DELETE FROM app_settings")
        conn.execute("INSERT INTO app_settings(key, value) VALUES ('admin_2fa_required', '0')")   # scenariile generale; 2 pași are teste dedicate
        conn.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL, session_epoch=0")
        conn.execute("UPDATE users SET display_name='Administrator test', role='admin', active=1 WHERE username='admin'")
        conn.execute("DELETE FROM auth_attempts")
        conn.execute("DELETE FROM deep_clean_reports")
        conn.execute("DELETE FROM audit_log")
        conn.execute("UPDATE rooms SET out_of_order=0, maintenance_note=''")
        conn.close()
        pms.settings.invalidate()
        token = self.csrf("/login")
        self.client.post("/login", data={"csrf_token": token, "username": "admin", "pin": "123456"}, follow_redirects=True)

    def csrf(self, path="/booking/new"):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match, "CSRF token not found in form")
        return match.group(1)

    def post_booking(self, name, room_id="1", check_in="2026-11-01", check_out="2026-11-03", guests="2"):
        token = self.csrf()
        return self.client.post("/booking/new", data={
            "csrf_token": token, "guest_name": name, "phone": "", "email": "", "room_id": room_id,
            "check_in": check_in, "check_out": check_out, "guests": guests,
            "rate": "200", "deposit": "0", "source": "Direct",
            "status": "confirmed", "notes": ""
        }, follow_redirects=True)

    def test_inventory_has_exactly_25_rooms_in_three_buildings(self):
        conn = pms.connect()
        rows = conn.execute("SELECT building, COUNT(*) AS n FROM rooms GROUP BY building").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        conn.close()
        self.assertEqual(total, 25)
        self.assertEqual({r["building"]: r["n"] for r in rows}, {"Corp A": 10, "Corp B": 6, "Corp C": 9})

    def test_calendar_is_grouped_and_cells_link_to_new_booking(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        for building in ("Corp A", "Corp B", "Corp C"):
            self.assertIn(building, html)
        self.assertIn("day-cell-link", html)
        self.assertIn("room_id=", html)

    def test_reception_dashboard_shows_daily_tasks_and_quick_actions(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("OPERARE ZILNICĂ", html)
        self.assertIn("Sosiri de astăzi", html)
        self.assertIn("Plecări de astăzi", html)
        self.assertIn("Reconfirmări · procedura 20:30", html)
        self.assertIn("Rezervare astăzi", html)
        self.assertIn("Rezervare grup", html)
        self.assertIn("Caută rezervări", html)

    def test_quick_search_filters_future_reservations(self):
        self.post_booking("Client cautare special", check_in="2026-11-01", check_out="2026-11-03")
        response = self.client.get("/?q=cautare%20special")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Client cautare special", html)
        response = self.client.get("/?q=nu-exista-client")
        listing = response.get_data(as_text=True).split("Căutare și toate rezervările viitoare", 1)[1]
        self.assertNotIn("Client cautare special", listing)

    def test_cell_query_prefills_room_date_and_calendar_back_link(self):
        response = self.client.get("/booking/new?room_id=1&check_in=2026-11-10")
        html = response.get_data(as_text=True)
        self.assertIn('value="2026-11-10"', html)
        self.assertRegex(html, r'selectedAtLoad\s*=\s*"?1"?')
        self.assertIn('start=2026-11-10', html)

    def test_rejects_more_than_two_guests(self):
        response = self.post_booking("Capacitate depășită", guests="3")
        self.assertIn("2 persoane", response.get_data(as_text=True))
        conn = pms.connect()
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_rejects_overlapping_reservation_for_same_room(self):
        self.post_booking("Primul client")
        response = self.post_booking("Al doilea client", check_in="2026-11-02", check_out="2026-11-04")
        self.assertIn("Conflict", response.get_data(as_text=True))
        conn = pms.connect()
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_allows_arrival_on_previous_booking_checkout_date(self):
        self.post_booking("Primul client", check_in="2026-11-01", check_out="2026-11-03")
        response = self.post_booking("Următorul client", check_in="2026-11-03", check_out="2026-11-04")
        self.assertIn("Următorul client", response.get_data(as_text=True))
        conn = pms.connect()
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

    def test_oblio_test_invoice_is_idempotent(self):
        self.post_booking("Client facturare")
        conn = pms.connect()
        booking_id = conn.execute("SELECT id FROM bookings WHERE guest_name='Client facturare'").fetchone()[0]
        conn.close()
        token = self.csrf(f"/booking/{booking_id}/edit")
        self.client.post(f"/booking/{booking_id}/oblio-test", data={"csrf_token": token}, follow_redirects=True)
        self.client.post(f"/booking/{booking_id}/oblio-test", data={"csrf_token": token}, follow_redirects=True)
        conn = pms.connect()
        invoices = conn.execute("SELECT COUNT(*) FROM invoices WHERE booking_id=?", (booking_id,)).fetchone()[0]
        attempts = conn.execute("SELECT COUNT(*) FROM invoice_attempts WHERE booking_id=?", (booking_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(invoices, 1)
        self.assertEqual(attempts, 2)

    def test_new_booking_stores_creator_snapshot_and_color(self):
        self.post_booking("Rezervare cu utilizator")
        conn = pms.connect()
        row = conn.execute("SELECT created_by, created_by_name, created_by_color FROM bookings WHERE guest_name=?", ("Rezervare cu utilizator",)).fetchone()
        conn.close()
        self.assertEqual(row["created_by_name"], "Administrator test")
        self.assertTrue(row["created_by_color"].startswith("#"))
        self.assertIsNotNone(row["created_by"])

    def test_admin_reports_are_available_and_calculate_occupancy(self):
        self.post_booking("Rezervare raport", check_in="2026-11-01", check_out="2026-11-03")
        response = self.client.get("/admin/reports?start=2026-11-01&end=2026-11-02")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Grad de ocupare", html)
        self.assertIn("Nopți vândute", html)
        self.assertIn("2", html)

    def test_audit_export_is_text_and_file_is_written(self):
        self.post_booking("Rezervare audit")
        response = self.client.get("/admin/audit/export")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.content_type)
        self.assertIn("POPAS CĂPRIOARA PMS", response.get_data(as_text=True))
        with open(os.environ["MOTEL_AUDIT_FILE"], encoding="utf-8") as stream:
            self.assertIn('"action": "create"', stream.read())

    def test_admin_can_delete_other_user_but_not_self(self):
        conn = pms.connect()
        cur = conn.execute("INSERT INTO users(username, display_name, pin_hash, role) VALUES (?, ?, ?, 'reception')", ("gestor", "Gestor test", pms.generate_password_hash("123456")))
        user_id = cur.lastrowid
        conn.close()
        token = self.csrf("/admin/users")
        response = self.client.post(f"/admin/users/{user_id}/delete", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("a fost șters", response.get_data(as_text=True))
        conn = pms.connect()
        self.assertIsNone(conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone())
        self.assertIsNotNone(conn.execute("SELECT id FROM audit_log WHERE action='delete' AND entity_type='user' AND entity_id=?", (str(user_id),)).fetchone())
        conn.close()
        conn = pms.connect()
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        conn.close()
        response = self.client.post(f"/admin/users/{admin_id}/delete", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("Nu vă puteți șterge propriul cont", response.get_data(as_text=True))


    def test_rate_is_mandatory_and_must_be_positive(self):
        token = self.csrf()
        response = self.client.post("/booking/new", data={
            "csrf_token": token, "guest_name": "Fără tarif", "room_id": "1",
            "check_in": "2026-11-01", "check_out": "2026-11-02", "guests": "2",
            "rate": "", "deposit": "0", "source": "Direct", "status": "confirmed"
        }, follow_redirects=True)
        self.assertIn("Tariful pe noapte este obligatoriu", response.get_data(as_text=True))
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0], 0)
        conn.close()

    def test_group_booking_starts_provisional_and_requires_receipt_to_confirm(self):
        token = self.csrf("/booking/group/new")
        response = self.client.post("/booking/group/new", data={
            "csrf_token": token, "guest_name": "Grup test", "phone": "0712345678", "email": "",
            "check_in": "2026-11-10", "check_out": "2026-11-12", "room_ids": ["1", "2"],
            "guests": "2", "rate": "180", "deposit": "0", "source": "Direct", "notes": ""
        }, follow_redirects=True)
        self.assertIn("creată provizoriu", response.get_data(as_text=True))
        conn = pms.connect()
        rows = conn.execute("SELECT * FROM bookings WHERE guest_name='Grup test' ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['status'] for r in rows}, {'provisional'})
        self.assertEqual(len({r['group_id'] for r in rows}), 1)
        booking_id = rows[0]['id']
        conn.close()
        token = self.csrf(f"/booking/{booking_id}/edit")
        data = {"csrf_token": token, "guest_name": "Grup test", "room_id": str(rows[0]['room_id']),
                "check_in": "2026-11-10", "check_out": "2026-11-12", "guests": "2", "rate": "180",
                "deposit": "0", "source": "Direct", "status": "confirmed", "notes": "", "receipt_number": ""}
        response = self.client.post(f"/booking/{booking_id}/edit", data=data, follow_redirects=True)
        self.assertIn("fără numărul chitanței", response.get_data(as_text=True))
        conn = pms.connect()
        self.assertEqual({r['status'] for r in conn.execute("SELECT status FROM bookings WHERE guest_name='Grup test'").fetchall()}, {'provisional'})
        conn.close()
        data['receipt_number'] = 'CH-1001'
        data['apply_to_group'] = '1'
        response = self.client.post(f"/booking/{booking_id}/edit", data=data, follow_redirects=True)
        self.assertIn("întregul grup au fost confirmate", response.get_data(as_text=True))
        conn = pms.connect()
        rows = conn.execute("SELECT status, receipt_number FROM bookings WHERE guest_name='Grup test'").fetchall()
        conn.close()
        self.assertEqual({r['status'] for r in rows}, {'confirmed'})
        self.assertEqual({r['receipt_number'] for r in rows}, {'CH-1001'})

    def test_report_export_downloads_xls_workbook(self):
        self.post_booking("Rezervare Excel", check_in="2026-11-01", check_out="2026-11-03")
        response = self.client.get("/admin/reports/export?start=2026-11-01&end=2026-11-02")
        self.assertEqual(response.status_code, 200)
        self.assertTrue("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in response.content_type or "text/csv" in response.content_type)
        disposition = response.headers.get("Content-Disposition", "")
        self.assertTrue(".xlsx" in disposition or ".csv" in disposition)
        self.assertTrue(response.data.startswith(b"PK\x03\x04") or response.data.startswith(b"\xef\xbb\xbf"))


    def test_group_requires_contact_phone(self):
        token = self.csrf("/booking/group/new")
        response = self.client.post("/booking/group/new", data={
            "csrf_token": token, "guest_name": "Grup fără telefon", "phone": "", "email": "",
            "check_in": "2026-11-10", "check_out": "2026-11-12", "room_ids": ["1"],
            "guests": "2", "rate": "180", "deposit": "0", "source": "Direct", "notes": ""
        }, follow_redirects=True)
        self.assertIn("telefon", response.get_data(as_text=True).lower())
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM bookings WHERE guest_name='Grup fără telefon'").fetchone()[0], 0)
        conn.close()

    def test_group_picker_script_is_rendered_inside_page(self):
        response = self.client.get("/booking/group/new?check_in=2026-11-10&check_out=2026-11-12")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("refreshRooms()", html)
        self.assertIn("available-room-list", html)
        self.assertIn("name=\"room_ids\"", html)

    def test_guest_name_autocomplete_returns_previous_names(self):
        self.post_booking("Popescu Ion Autocomplete", check_in="2026-11-01", check_out="2026-11-03")
        response = self.client.get("/api/guest-name-suggestions?q=Popescu")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Popescu Ion Autocomplete", response.get_json()["names"])

    def test_group_picker_api_excludes_occupied_rooms(self):
        self.post_booking("Client ocupă camera", room_id="1", check_in="2026-11-10", check_out="2026-11-12")
        response = self.client.get("/api/available-rooms?start=2026-11-10&end=2026-11-12")
        self.assertEqual(response.status_code, 200)
        room_ids = {r["id"] for r in response.get_json()["rooms"]}
        self.assertNotIn(1, room_ids)
        self.assertIn(2, room_ids)

    def test_admin_can_mark_room_defective_and_api_excludes_it(self):
        token = self.csrf("/admin/rooms")
        response = self.client.post("/admin/rooms", data={
            "csrf_token": token, "room_id": "1", "out_of_order": "1", "maintenance_note": "Defecțiune test"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        conn = pms.connect()
        row = conn.execute("SELECT out_of_order, maintenance_note FROM rooms WHERE id=1").fetchone()
        conn.close()
        self.assertEqual(row["out_of_order"], 1)
        self.assertEqual(row["maintenance_note"], "Defecțiune test")
        response = self.client.get("/api/available-rooms?start=2026-11-10&end=2026-11-12")
        self.assertNotIn(1, {r["id"] for r in response.get_json()["rooms"]})
        token = self.csrf("/booking/new")
        response = self.client.post("/booking/new", data={
            "csrf_token": token, "guest_name": "Nu rezerva camera defectă", "room_id": "1",
            "check_in": "2026-11-10", "check_out": "2026-11-11", "guests": "2",
            "rate": "100", "deposit": "0", "source": "Direct", "status": "confirmed"
        }, follow_redirects=True)
        self.assertIn("Selectați o cameră validă", response.get_data(as_text=True))
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM bookings WHERE guest_name='Nu rezerva camera defectă'").fetchone()[0], 0)
        conn.close()
        group_token = self.csrf("/booking/group/new")
        group_response = self.client.post("/booking/group/new", data={
            "csrf_token": group_token, "guest_name": "Grup cu cameră defectă", "phone": "0712345678", "email": "",
            "check_in": "2026-11-10", "check_out": "2026-11-11", "room_ids": ["1"],
            "guests": "2", "rate": "100", "deposit": "0", "source": "Direct", "notes": ""
        }, follow_redirects=True)
        self.assertIn("cameră disponibilă", group_response.get_data(as_text=True).lower())
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM bookings WHERE guest_name='Grup cu cameră defectă'").fetchone()[0], 0)
        conn.close()


    def test_available_rooms_api_excludes_occupied_and_defective_and_orders_by_building(self):
        self.post_booking("Client ocupă camera A", room_id="1", check_in="2026-11-10", check_out="2026-11-12")
        token = self.csrf("/admin/rooms")
        self.client.post("/admin/rooms", data={"csrf_token": token, "room_id": "11", "out_of_order": "1", "maintenance_note": "Test defect"}, follow_redirects=True)
        response = self.client.get("/api/available-rooms?start=2026-11-10&end=2026-11-12")
        self.assertEqual(response.status_code, 200)
        rooms = response.get_json()["rooms"]
        ids = {r["id"] for r in rooms}
        self.assertNotIn(1, ids)
        self.assertNotIn(11, ids)
        rank = {"Corp A": 0, "Corp B": 1, "Corp C": 2}
        self.assertEqual([rank[r["building"]] for r in rooms], sorted(rank[r["building"]] for r in rooms))

    def test_csv_report_export_downloads_excel_friendly_csv(self):
        self.post_booking("Rezervare CSV", check_in="2026-11-01", check_out="2026-11-03")
        response = self.client.get("/admin/reports/export.csv?start=2026-11-01&end=2026-11-02")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        self.assertIn(".csv", response.headers.get("Content-Disposition", ""))
        self.assertIn("ID rezervare".encode(), response.data)

    def test_group_confirmation_can_be_applied_only_to_current_room(self):
        token = self.csrf("/booking/group/new")
        self.client.post("/booking/group/new", data={
            "csrf_token": token, "guest_name": "Grup selectiv", "phone": "0712345678", "email": "",
            "check_in": "2026-11-10", "check_out": "2026-11-12", "room_ids": ["1", "2"],
            "guests": "2", "rate": "180", "deposit": "0", "source": "Direct", "notes": ""
        }, follow_redirects=True)
        conn = pms.connect()
        rows = conn.execute("SELECT * FROM bookings WHERE guest_name='Grup selectiv' ORDER BY id").fetchall()
        conn.close()
        first = rows[0]
        token = self.csrf(f"/booking/{first['id']}/edit")
        response = self.client.post(f"/booking/{first['id']}/edit", data={
            "csrf_token": token, "guest_name": first['guest_name'], "phone": first['phone'], "room_id": str(first['room_id']),
            "check_in": first['check_in'], "check_out": first['check_out'], "guests": "2", "rate": "180",
            "deposit": "0", "source": "Direct", "status": "confirmed", "notes": "", "receipt_number": "CH-LOCAL", "apply_to_group": "0"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        conn = pms.connect()
        states = conn.execute("SELECT status, receipt_number FROM bookings WHERE group_id=? ORDER BY id", (first['group_id'],)).fetchall()
        conn.close()
        self.assertEqual(states[0]['status'], 'confirmed')
        self.assertEqual(states[0]['receipt_number'], 'CH-LOCAL')
        self.assertEqual(states[1]['status'], 'provisional')
        self.assertEqual(states[1]['receipt_number'], '')

    def test_housekeeping_marks_room_clean_and_shows_three_days(self):
        response = self.client.get("/housekeeping")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Camere și solicitări pentru astăzi", html)
        self.assertIn("Corp A", html)
        self.assertIn("Marchează curată", html)
        self.assertNotIn("Mâine", html)
        token = self.csrf("/housekeeping")
        conn = pms.connect()
        room_id = conn.execute("SELECT id FROM rooms ORDER BY sort_order LIMIT 1").fetchone()["id"]
        conn.close()
        today = pms.date.today().isoformat()
        response = self.client.post("/housekeeping", data={
            "csrf_token": token, "room_id": str(room_id), "service_date": today, "is_clean": "1"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        conn = pms.connect()
        mark = conn.execute("SELECT is_clean FROM room_cleaning WHERE room_id=? AND service_date=?", (room_id, today)).fetchone()
        conn.close()
        self.assertEqual(mark["is_clean"], 1)

    def test_group_cancellation_can_cancel_selected_rooms_only(self):
        token = self.csrf("/booking/group/new")
        self.client.post("/booking/group/new", data={
            "csrf_token": token, "guest_name": "Grup de anulat", "phone": "0712345678", "email": "",
            "check_in": "2026-11-10", "check_out": "2026-11-12", "room_ids": ["1", "2"],
            "guests": "2", "rate": "180", "deposit": "0", "source": "Direct", "notes": ""
        }, follow_redirects=True)
        conn = pms.connect()
        rows = conn.execute("SELECT * FROM bookings WHERE guest_name='Grup de anulat' ORDER BY id").fetchall()
        conn.close()
        token = self.csrf(f"/booking/{rows[0]['id']}/edit")
        response = self.client.post(f"/booking/group/{rows[0]['group_id']}/cancel", data={
            "csrf_token": token, "scope": "selected", "confirmed": "1", "booking_ids": [str(rows[0]['id'])]
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        conn = pms.connect()
        states = conn.execute("SELECT status FROM bookings WHERE group_id=? ORDER BY id", (rows[0]['group_id'],)).fetchall()
        conn.close()
        self.assertEqual(states[0]["status"], "cancelled")
        self.assertEqual(states[1]["status"], "provisional")

    def test_cutoff_marks_unreconfirmed_same_day_direct_booking_unconfirmed(self):
        today = pms.date.today().isoformat()
        conn = pms.connect()
        conn.execute("INSERT INTO bookings(guest_name, room_id, check_in, check_out, guests, rate, source, status) VALUES (?, ?, ?, ?, 1, 100, 'Direct', 'confirmed')",
                     ("Sosire azi", 1, today, (pms.date.today() + pms.timedelta(days=1)).isoformat()))
        booking_id = conn.execute("SELECT id FROM bookings WHERE guest_name='Sosire azi'").fetchone()[0]
        conn.close()
        cutoff_time = pms.datetime.combine(pms.date.today(), pms.datetime.min.time()).astimezone() + pms.timedelta(hours=21)
        count = pms.apply_direct_booking_cutoff(cutoff_time)
        self.assertGreaterEqual(count, 1)
        conn = pms.connect()
        status = conn.execute("SELECT status FROM bookings WHERE id=?", (booking_id,)).fetchone()['status']
        conn.close()
        self.assertEqual(status, 'unconfirmed')

    def test_reception_request_is_shared_with_housekeeping_and_can_be_completed(self):
        token = self.csrf("/")
        conn = pms.connect()
        room_id = conn.execute("SELECT id FROM rooms WHERE active=1 AND out_of_order=0 ORDER BY sort_order LIMIT 1").fetchone()["id"]
        conn.close()
        response = self.client.post("/housekeeping/request", data={"csrf_token": token, "room_id": str(room_id), "request_type": "towels", "note": "Test prosoape"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Test prosoape", response.get_data(as_text=True))
        conn = pms.connect()
        task = conn.execute("SELECT id, status FROM housekeeping_requests WHERE note='Test prosoape'").fetchone()
        conn.close()
        self.assertIsNotNone(task)
        token = self.csrf("/housekeeping")
        response = self.client.post("/housekeeping", data={"csrf_token": token, "action": "complete_request", "request_id": str(task["id"])}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        conn = pms.connect()
        state = conn.execute("SELECT status, completed_by_name FROM housekeeping_requests WHERE id=?", (task["id"],)).fetchone()
        conn.close()
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["completed_by_name"], "Administrator test")

    def test_admin_can_create_housekeeping_account_with_restricted_access(self):
        token = self.csrf("/admin/users")
        response = self.client.post("/admin/users", data={"csrf_token": token, "username": "camerista1", "display_name": "Cameristă test", "pin": "482915", "role": "housekeeping"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        conn = pms.connect()
        user = conn.execute("SELECT id, role, staff_type FROM users WHERE username='camerista1'").fetchone()
        conn.close()
        self.assertEqual(user["role"], "reception")
        self.assertEqual(user["staff_type"], "housekeeping")
        with self.client.session_transaction() as sess:
            sess.clear()
        self.client.post("/login", data={"csrf_token": self.csrf("/login"), "username": "camerista1", "pin": "482915"}, follow_redirects=True)
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/housekeeping", response.headers["Location"])

    def test_unauthenticated_user_is_redirected_to_login(self):
        self.client.post("/logout", data={"csrf_token": self.csrf("/")})
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


    # ---- v14: stări cameră, evenimente și API de integrare ----
    API_TOKEN = "test-token-0123456789abcdef0123"

    def api(self, path, method="get", token=API_TOKEN, **kwargs):
        client = pms.app.test_client()  # fără sesiune de recepție
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return getattr(client, method)(path, headers=headers, **kwargs)

    def insert_booking(self, room_id, check_in, check_out, status="confirmed"):
        conn = pms.connect()
        conn.execute("""INSERT INTO bookings(guest_name, room_id, check_in, check_out, guests, rate, source, status)
                        VALUES ('Client test', ?, ?, ?, 2, 200, 'Telefon', ?)""", (room_id, check_in, check_out, status))
        conn.close()

    def test_room_codes_are_stable_and_unique(self):
        conn = pms.connect()
        codes = [r["code"] for r in conn.execute("SELECT code FROM rooms").fetchall()]
        conn.close()
        self.assertEqual(len(codes), 25)
        self.assertEqual(len(set(codes)), 25)
        self.assertIn("camera_101", codes)
        self.assertIn("camera_01", codes)

    def test_state_engine_covers_every_state(self):
        from datetime import date, timedelta
        t = date.today()
        d = lambda n: (t + timedelta(days=n)).isoformat()
        self.insert_booking(1, d(-1), d(1))                       # în sejur -> occupied
        self.insert_booking(2, d(0), d(2), "checked_in")          # cazat azi -> occupied
        self.insert_booking(3, d(0), d(1))                        # sosire azi -> arriving
        self.insert_booking(4, d(-2), d(0), "checked_in")         # plecare azi -> departing
        self.insert_booking(4, d(0), d(1))                        # + sosire în aceeași zi
        self.insert_booking(8, d(0), d(2), "cancelled")           # anulată nu contează
        self.insert_booking(9, d(3), d(5))                        # doar sosire viitoare
        conn = pms.connect()
        conn.execute("UPDATE rooms SET out_of_order=1 WHERE id=5")
        conn.execute("INSERT INTO room_cleaning(room_id, service_date, is_clean) VALUES (6, ?, 1)", (d(0),))
        from datetime import datetime as _dt
        states = {s["room_id"]: s for s in pms.room_state.compute_room_states(conn, now=_dt.combine(t, _dt.strptime("10:00", "%H:%M").time()))}
        conn.close()
        self.assertEqual(states[1]["state"], "occupied")
        self.assertEqual(states[2]["state"], "occupied")
        self.assertEqual(states[3]["state"], "arriving")
        self.assertTrue(states[3]["arrival_today"])
        self.assertEqual(states[4]["state"], "departing")
        self.assertTrue(states[4]["arrival_today"] and states[4]["departure_today"])
        self.assertEqual(states[5]["state"], "out_of_order")
        self.assertEqual(states[6]["state"], "vacant_clean")
        self.assertEqual(states[7]["state"], "vacant_to_check")
        self.assertEqual(states[8]["state"], "vacant_to_check")
        self.assertEqual(states[9]["state"], "vacant_to_check")
        self.assertEqual(states[9]["next_arrival_date"], d(3))
        self.assertTrue(states[1]["occupied_tonight"])
        self.assertFalse(states[7]["occupied_tonight"])

    def test_dashboard_shows_room_board(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Starea camerelor acum", html)
        self.assertIn("rb-vacant_to_check", html)

    def test_booking_and_cancel_create_room_events_with_state(self):
        self.post_booking("Client evenimente")
        conn = pms.connect()
        booking_id = conn.execute("SELECT id FROM bookings").fetchone()["id"]
        conn.close()
        self.client.post(f"/booking/{booking_id}/cancel", data={"csrf_token": self.csrf("/")}, follow_redirects=True)
        conn = pms.connect()
        rows = conn.execute("SELECT * FROM room_events ORDER BY id").fetchall()
        conn.close()
        self.assertEqual([r["event_type"] for r in rows], ["booking_created", "booking_cancelled"])
        self.assertEqual(rows[0]["room_code"], "camera_101")
        self.assertEqual(rows[0]["booking_id"], booking_id)
        import json
        self.assertIn("state", json.loads(rows[1]["payload"]))

    def test_housekeeping_clean_emits_event(self):
        token = self.csrf("/housekeeping")
        self.client.post("/housekeeping", data={"csrf_token": token, "action": "mark_clean", "room_id": "7", "is_clean": "1"})
        conn = pms.connect()
        row = conn.execute("SELECT * FROM room_events WHERE event_type='room_clean_changed'").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["room_code"], "camera_203")
        import json
        self.assertEqual(json.loads(row["payload"])["state"]["state"], "vacant_clean")

    def test_failed_event_does_not_block_booking(self):
        original = pms.room_state.emit_for_audit
        pms.room_state.emit_for_audit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("test"))
        try:
            self.post_booking("Client rezistent")
        finally:
            pms.room_state.emit_for_audit = original
        conn = pms.connect()
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_api_disabled_without_token_configuration(self):
        previous = os.environ.pop("MOTEL_API_TOKEN", None)
        try:
            self.assertEqual(self.api("/api/v1/rooms").status_code, 503)
        finally:
            if previous is not None:
                os.environ["MOTEL_API_TOKEN"] = previous

    def test_api_requires_valid_token_and_hides_personal_data(self):
        os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
        self.insert_booking(1, __import__("datetime").date.today().isoformat(),
                            (__import__("datetime").date.today() + __import__("datetime").timedelta(days=1)).isoformat())
        self.assertEqual(self.api("/api/v1/rooms", token=None).status_code, 401)
        self.assertEqual(self.api("/api/v1/rooms", token="gresit" * 6).status_code, 401)
        response = self.api("/api/v1/rooms")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rooms"]), 25)
        self.assertNotIn("guest_name", data["rooms"][0])
        self.assertNotIn("maintenance_note", data["rooms"][0])
        self.assertNotIn("Client test", response.get_data(as_text=True))
        one = self.api("/api/v1/rooms/camera_101").get_json()
        self.assertEqual(one["state"], "arriving")
        self.assertEqual(self.api("/api/v1/rooms/camera_nu_exista").status_code, 404)

    def test_api_events_pagination_and_ack_without_csrf(self):
        os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
        self.post_booking("Client A", room_id="1")
        self.post_booking("Client B", room_id="2")
        first = self.api("/api/v1/events?limit=1").get_json()
        self.assertEqual(len(first["events"]), 1)
        self.assertTrue(first["has_more"])
        rest = self.api(f"/api/v1/events?after_id={first['events'][0]['id']}").get_json()
        self.assertEqual(len(rest["events"]), 1)
        self.assertEqual(rest["events"][0]["room_code"], "camera_102")
        ack = self.api("/api/v1/events/ack", method="post", json={"up_to_id": rest["last_event_id"]})
        self.assertEqual(ack.get_json()["acknowledged"], 2)
        self.assertEqual(self.api("/api/v1/events?limit=abc").status_code, 400)
        self.assertEqual(self.api("/api/v1/health").get_json()["schema_version"], 13)

    def test_init_db_is_idempotent_and_keeps_codes(self):
        pms.init_db()
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT code FROM rooms WHERE name='101'").fetchone()["code"], "camera_101")
        conn.close()


    # ---- v14: alerte recepție ↔ cameriste ----
    def make_housekeeper(self):
        conn = pms.connect()
        conn.execute("DELETE FROM users WHERE username='camerista'")
        conn.execute("INSERT INTO users(username, display_name, pin_hash, role, staff_type) VALUES ('camerista','Maria',?, 'reception','housekeeping')",
                     (pms.generate_password_hash("654321"),))
        conn.close()
        client = pms.app.test_client()
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
        client.post("/login", data={"csrf_token": token, "username": "camerista", "pin": "654321"}, follow_redirects=True)
        return client

    def feed(self, client, after_id=None):
        url = "/api/notifications" + ("" if after_id is None else f"?after_id={after_id}")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def reception_request(self, room_id="3", request_type="cleaning", note="Pat murdar"):
        token = self.csrf("/")
        return self.client.post("/housekeeping/request", data={"csrf_token": token, "room_id": room_id,
                                "request_type": request_type, "note": note}, follow_redirects=True)

    def test_new_request_alerts_housekeeper_but_not_the_sender(self):
        maid = self.make_housekeeper()
        base = self.feed(maid)["last_id"]                      # fără after_id: doar punct de plecare
        self.assertEqual(self.feed(maid)["items"], [])
        self.reception_request(note="Pat murdar")
        data = self.feed(maid, base)
        self.assertEqual(len(data["items"]), 1)
        item = data["items"][0]
        self.assertEqual((item["kind"], item["priority"]), ("request_created", "urgent"))
        self.assertIn("Camera 103", item["text"])
        self.assertIn("Pat murdar", item["text"])
        self.assertIn(item["request_id"], data["open_request_ids"])
        self.assertEqual(self.feed(self.client, base)["items"], [])   # expeditorul nu primește alertă pentru propria acțiune

    def test_completed_request_and_clean_mark_alert_reception(self):
        maid = self.make_housekeeper()
        self.reception_request()
        conn = pms.connect()
        request_id = conn.execute("SELECT id FROM housekeeping_requests").fetchone()["id"]
        conn.close()
        base = self.feed(self.client)["last_id"]
        token = re.search(r'name="csrf_token" value="([^"]+)"', maid.get("/housekeeping").get_data(as_text=True)).group(1)
        maid.post("/housekeeping", data={"csrf_token": token, "action": "complete_request", "request_id": str(request_id)}, follow_redirects=True)
        maid.post("/housekeeping", data={"csrf_token": token, "action": "mark_clean", "room_id": "3", "is_clean": "1"}, follow_redirects=True)
        items = self.feed(self.client, base)["items"]
        self.assertEqual([i["kind"] for i in items], ["request_done", "room_clean"])
        self.assertIn("Maria", items[0]["text"])
        self.assertEqual(self.feed(maid, base)["items"], [])
        self.assertNotIn(request_id, self.feed(self.client, base)["open_request_ids"])

    def test_checkout_alerts_housekeeper_once(self):
        from datetime import date, timedelta
        self.insert_booking(5, (date.today() - timedelta(days=1)).isoformat(), (date.today() + timedelta(days=1)).isoformat(), "checked_in")
        conn = pms.connect()
        booking_id = conn.execute("SELECT id FROM bookings").fetchone()["id"]
        conn.close()
        maid = self.make_housekeeper()
        base = self.feed(maid)["last_id"]
        def save(status):
            r = self.client.get(f"/booking/{booking_id}/edit").get_data(as_text=True)
            token = re.search(r'name="csrf_token" value="([^"]+)"', r).group(1)
            self.client.post(f"/booking/{booking_id}/edit", data={
                "csrf_token": token, "guest_name": "Client test", "phone": "", "email": "", "room_id": "5",
                "check_in": (date.today() - timedelta(days=1)).isoformat(), "check_out": (date.today() + timedelta(days=1)).isoformat(),
                "guests": "2", "rate": "200", "deposit": "0", "source": "Direct", "status": status, "notes": ""}, follow_redirects=True)
        save("checked_out")
        first = self.feed(maid, base)["items"]
        self.assertEqual([i["kind"] for i in first], ["checkout"])
        save("checked_out")                                    # o simplă re-salvare nu mai alertează
        self.assertEqual(len(self.feed(maid, base)["items"]), 1)

    def test_old_events_do_not_alert_and_staff_names_stay_out_of_api(self):
        from datetime import datetime, timedelta
        maid = self.make_housekeeper()
        base = self.feed(maid)["last_id"]
        self.reception_request()
        conn = pms.connect()
        conn.execute("UPDATE room_events SET created_at=?", ((datetime.now().astimezone() - timedelta(minutes=45)).isoformat(timespec="seconds"),))
        conn.close()
        self.assertEqual(self.feed(maid, base)["items"], [])
        os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
        raw = self.api("/api/v1/events").get_data(as_text=True)
        self.assertNotIn("Administrator test", raw)
        self.assertNotIn('"actor"', raw)

    def test_housekeeper_can_use_live_endpoints_but_not_reception_pages(self):
        maid = self.make_housekeeper()
        self.assertEqual(maid.get("/api/housekeeping-updates").status_code, 200)
        self.assertEqual(maid.get("/api/notifications").status_code, 200)
        self.assertEqual(maid.get("/api/notifications?after_id=abc").status_code, 400)
        self.assertEqual(maid.get("/booking/new").status_code, 302)
        page = maid.get("/housekeeping").get_data(as_text=True)
        self.assertIn('id="pmsNotify"', page)
        self.assertIn("notify.js", page)

    def test_reception_panel_shows_only_open_actions_until_expanded(self):
        self.reception_request(room_id="3", note="Solicitare deschisă test")
        self.reception_request(room_id="4", note="Solicitare încheiată test")
        conn = pms.connect()
        conn.execute("UPDATE housekeeping_requests SET status='done', completed_at='10:00' WHERE note='Solicitare încheiată test'")
        conn.close()
        html = self.client.get("/").get_data(as_text=True)
        panel = html.split('id="hkPanel"', 1)[1].split("</section>", 1)[0]
        visible, hidden = panel.split('<details class="hk-details"', 1)
        self.assertIn("Solicitare deschisă test", visible)
        self.assertNotIn("Solicitare încheiată test", visible)
        self.assertIn("Solicitare încheiată test", hidden)
        self.assertIn('data-persist="hk-history"', hidden)
        self.assertNotIn("housekeepingLiveNotice", html)
        self.assertIn('id="pmsNotify"', html)

    def test_alert_script_is_served_and_escapes_user_text(self):
        js = self.client.get("/static/notify.js").get_data(as_text=True)
        self.assertIn("textContent", js)
        self.assertNotIn("innerHTML = item", js)


    # ---- v15 ----
    def at(self, hhmm):
        from datetime import datetime as dt, date as d
        pms.room_state.now_fn = lambda: dt.combine(d.today(), dt.strptime(hhmm, "%H:%M").time())

    def tearDown(self):
        pms.room_state.now_fn = __import__("datetime").datetime.now
        pms.night.now_fn = __import__("datetime").datetime.now
        pms.integration_api._failures.clear()
        pms.app.config["SESSION_COOKIE_SECURE"] = False
        pms.settings.invalidate()
        pms.clock.configure("")
        os.environ.pop("MOTEL_CHECKOUT_TIME", None)

    def day(self, n):
        from datetime import date, timedelta
        return (date.today() + timedelta(days=n)).isoformat()

    def state_of(self, room_id, hhmm):
        conn = pms.connect()
        from datetime import datetime as dt, date as d
        item = pms.room_state.compute_room_states(conn, room_id=room_id, now=dt.combine(d.today(), dt.strptime(hhmm, "%H:%M").time()))[0]
        conn.close()
        return item

    # 2. stare automată după ora de check-out / check-in
    def test_room_becomes_available_after_checkout_time(self):
        self.insert_booking(4, self.day(-2), self.day(0), "checked_in")
        self.assertEqual(self.state_of(4, "10:00")["state"], "departing")
        self.assertEqual(self.state_of(4, "12:59")["state"], "departing")
        after = self.state_of(4, "13:00")
        self.assertEqual(after["state"], "vacant_to_check")
        self.assertTrue(after["auto_released"])
        self.assertTrue(after["departure_today"])

    def test_incoming_booking_takes_the_room_after_checkout_time(self):
        self.insert_booking(4, self.day(-2), self.day(0), "checked_in")
        self.insert_booking(4, self.day(0), self.day(2))
        before = self.state_of(4, "12:30")
        self.assertEqual(before["state"], "departing")
        self.assertTrue(before["arrival_today"])
        after = self.state_of(4, "13:05")
        self.assertEqual((after["state"], after["auto_released"]), ("arriving", True))

    def test_arriving_booking_stays_reserved_without_manual_checkin(self):
        self.insert_booking(3, self.day(0), self.day(2))
        self.assertEqual(self.state_of(3, "09:00")["state"], "arriving")
        self.assertEqual(self.state_of(3, "18:00")["state"], "arriving")      # nu devine „ocupată” fără check-in la recepție

    def test_overdue_checked_in_booking_is_released_and_times_are_configurable(self):
        self.insert_booking(6, self.day(-3), self.day(-1), "checked_in")
        self.assertTrue(self.state_of(6, "08:00")["auto_released"])
        self.insert_booking(7, self.day(-1), self.day(0), "checked_in")
        os.environ["MOTEL_CHECKOUT_TIME"] = "11:00"
        self.assertEqual(self.state_of(7, "11:00")["state"], "vacant_to_check")
        self.assertEqual(self.state_of(7, "11:00")["checkout_time"], "11:00")

    def test_auto_release_emits_one_event_and_alerts_both_sides(self):
        from datetime import datetime as dt, date as d
        self.insert_booking(4, self.day(-2), self.day(0), "checked_in")
        conn = pms.connect()
        before = dt.combine(d.today(), dt.strptime("12:00", "%H:%M").time())
        after = dt.combine(d.today(), dt.strptime("13:10", "%H:%M").time())
        self.assertEqual(pms.room_state.emit_time_events(conn, now=before), 0)
        self.assertEqual(pms.room_state.emit_time_events(conn, now=after), 1)
        self.assertEqual(pms.room_state.emit_time_events(conn, now=after), 0)  # o singură dată pe rezervare
        conn.close()
        maid = self.make_housekeeper()
        conn = pms.connect()
        feed_h = pms.notifications.feed(conn, "housekeeping", None, 0)
        feed_r = pms.notifications.feed(conn, "reception", None, 0)
        conn.close()
        self.assertEqual([i["kind"] for i in feed_h["items"]], ["auto_release"])
        self.assertIn("poate fi curățată", feed_h["items"][0]["text"])
        self.assertIn("Finalizați check-out", feed_r["items"][0]["text"])

    def test_housekeeper_cannot_mark_clean_before_checkout_time_but_can_after(self):
        self.insert_booking(4, self.day(-2), self.day(0), "checked_in")
        maid = self.make_housekeeper()
        def mark():
            token = re.search(r'name="csrf_token" value="([^"]+)"', maid.get("/housekeeping").get_data(as_text=True)).group(1)
            maid.post("/housekeeping", data={"csrf_token": token, "action": "mark_clean", "room_id": "4", "is_clean": "1"}, follow_redirects=True)
            conn = pms.connect()
            row = conn.execute("SELECT is_clean FROM room_cleaning WHERE room_id=4").fetchone()
            conn.close()
            return bool(row and row["is_clean"])
        self.at("10:00")
        self.assertFalse(mark())
        self.at("13:30")
        self.assertTrue(mark())

    # 5. pagina cameristei arată starea și ora de check-out
    def test_housekeeper_page_shows_state_and_checkout_time(self):
        self.insert_booking(1, self.day(-1), self.day(2), "checked_in")
        self.insert_booking(4, self.day(-2), self.day(0), "checked_in")
        self.insert_booking(9, self.day(3), self.day(5))
        maid = self.make_housekeeper()
        self.at("10:00")
        html = maid.get("/housekeeping").get_data(as_text=True)
        self.assertNotIn("nu se marchează ca pregătită", html)
        self.assertIn("Cazat · check-out", html)
        self.assertIn("Check-out azi până la 13:00", html)
        self.assertIn("Următoarea sosire:", html)
        self.at("13:30")
        html = maid.get("/housekeeping").get_data(as_text=True)
        self.assertNotIn("Check-out azi până la 13:00", html)
        self.assertIn("ELIBERATĂ", html)

    # 4. doar sarcinile active sunt vizibile pe pagina cameristei
    def test_housekeeper_page_collapses_finished_tasks(self):
        self.reception_request(room_id="3", note="Sarcină activă test")
        self.reception_request(room_id="4", note="Sarcină încheiată test")
        conn = pms.connect()
        conn.execute("UPDATE housekeeping_requests SET status='done' WHERE note='Sarcină încheiată test'")
        conn.close()
        maid = self.make_housekeeper()
        html = maid.get("/housekeeping").get_data(as_text=True)
        visible, hidden = html.split('<details class="hk-details" data-persist="hk-page-done">', 1)
        self.assertIn("Sarcină activă test", visible)
        self.assertNotIn("Sarcină încheiată test", visible)
        self.assertIn("Sarcină încheiată test", hidden.split("</details>", 1)[0])

    # 3. hârtie igienică
    def test_toilet_paper_and_combined_services(self):
        token = self.csrf("/")
        self.client.post("/housekeeping/request", data={"csrf_token": token, "room_id": "3", "services": ["cleaning", "toilet_paper"], "note": ""}, follow_redirects=True)
        self.client.post("/housekeeping/request", data={"csrf_token": token, "room_id": "4", "services": ["toilet_paper"], "note": ""}, follow_redirects=True)
        self.client.post("/housekeeping/request", data={"csrf_token": token, "room_id": "5", "request_type": "both", "note": ""}, follow_redirects=True)
        self.assertEqual(self.client.post("/housekeeping/request", data={"csrf_token": token, "room_id": "6", "services": ["nu-exista"]}).status_code, 400)
        conn = pms.connect()
        types = [r["request_type"] for r in conn.execute("SELECT request_type FROM housekeeping_requests ORDER BY id").fetchall()]
        conn.close()
        self.assertEqual(types, ["cleaning,toilet_paper", "toilet_paper", "cleaning,towels"])
        maid = self.make_housekeeper()
        html = maid.get("/housekeeping").get_data(as_text=True)
        self.assertIn("Curățenie + Hârtie igienică", html)
        self.assertIn("Hârtie igienică", html)
        self.assertIn("Curățenie + Schimb prosoape", html)
        self.assertIn('value="toilet_paper"', self.client.get("/").get_data(as_text=True))

    def test_request_type_migration_keeps_existing_requests(self):
        import sqlite3, deep_clean
        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.executescript("""CREATE TABLE rooms(id INTEGER PRIMARY KEY);
            CREATE TABLE housekeeping_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL REFERENCES rooms(id),
              service_date TEXT NOT NULL, request_type TEXT NOT NULL CHECK(request_type IN ('cleaning','towels','both')),
              note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done','cancelled')));
            INSERT INTO rooms VALUES (1); INSERT INTO housekeeping_requests(room_id, service_date, request_type, note) VALUES (1,'2026-01-01','both','vechi');""")
        self.assertTrue(deep_clean.migrate_request_types(conn))
        self.assertFalse(deep_clean.migrate_request_types(conn))
        conn.execute("INSERT INTO housekeeping_requests(room_id, service_date, request_type) VALUES (1,'2026-01-01','toilet_paper')")
        self.assertEqual([r["request_type"] for r in conn.execute("SELECT request_type FROM housekeeping_requests ORDER BY id")], ["both", "toilet_paper"])

    # 6. formular săptămânal de curățenie extinsă
    def test_deep_clean_prompt_at_login_on_low_occupancy_and_roundtrip(self):
        import deep_clean
        conn = pms.connect()
        states = pms.room_state.compute_room_states(conn)
        info = deep_clean.due_info(conn, states)
        conn.close()
        self.assertTrue(info["due"] and info["low_occupancy"])
        self.assertEqual(deep_clean.max_occupied(), 4)
        maid = self.make_housekeeper()      # autentificarea cameristei duce direct la formular
        page = maid.get("/housekeeping/deep-clean").get_data(as_text=True)
        self.assertIn("Păianjeni și pânze", page)
        self.assertIn("Paturi trase și aspirat dedesubt", page)
        self.assertIn("Calorifere curățate", page)
        self.assertIn("Cabină de duș, curățare extinsă", page)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        base = self.feed(self.client)["last_id"]
        maid.post("/housekeeping/deep-clean/7", data={"csrf_token": token, "action": "save", "items": ["spiders", "beds"], "note": "ciornă"}, follow_redirects=True)
        self.assertEqual(self.feed(self.client, base)["items"], [])                  # ciorna nu alertează recepția
        maid.post("/housekeeping/deep-clean/7", data={"csrf_token": token, "action": "send", "items": ["spiders", "beds", "dust", "radiators"], "note": "Perdea de spălat"}, follow_redirects=True)
        items = self.feed(self.client, base)["items"]
        self.assertEqual([i["kind"] for i in items], ["deep_clean"])
        self.assertIn("Camera 203", items[0]["text"])
        self.assertIn("4/8 puncte", items[0]["text"])
        self.assertIn("Perdea de spălat", items[0]["text"])
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM deep_clean_reports").fetchone()[0], 1)  # o singură înregistrare pe cameră și săptămână
        conn.close()
        reports = self.client.get("/deep-clean/reports").get_data(as_text=True)
        self.assertIn("Perdea de spălat", reports)
        self.assertIn("Trimis", reports)
        self.assertEqual(maid.get("/deep-clean/reports").status_code, 302)

    def test_deep_clean_not_due_on_busy_days_and_blocked_for_occupied_rooms(self):
        import deep_clean
        for room in range(1, 7):
            self.insert_booking(room, self.day(-1), self.day(2), "checked_in")
        conn = pms.connect()
        info = deep_clean.due_info(conn, pms.room_state.compute_room_states(conn))
        conn.close()
        self.assertEqual((info["occupied"], info["low_occupancy"], info["due"]), (6, False, False))
        maid = self.make_housekeeper()
        self.assertNotIn("Curățenie extinsă săptămânală</b>", maid.get("/housekeeping").get_data(as_text=True))
        token = re.search(r'name="csrf_token" value="([^"]+)"', maid.get("/housekeeping/deep-clean").get_data(as_text=True)).group(1)
        maid.post("/housekeeping/deep-clean/1", data={"csrf_token": token, "action": "send", "items": ["dust"]}, follow_redirects=True)
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM deep_clean_reports").fetchone()[0], 0)
        conn.close()

    # 1. ultimele 3 interacțiuni
    def test_bookings_panel_shows_only_last_three_interactions(self):
        for i in range(1, 6):
            self.insert_booking(i, self.day(10 + i), self.day(12 + i))
        conn = pms.connect()
        for i, row in enumerate(conn.execute("SELECT id FROM bookings ORDER BY id").fetchall()):
            conn.execute("UPDATE bookings SET guest_name=?, updated_at=? WHERE id=?", (f"Client nr{i + 1}", f"2026-10-0{i + 1} 10:00:00", row["id"]))
        conn.close()
        panel = self.client.get("/").get_data(as_text=True).split('id="bookingsPanel"', 1)[1]
        visible, hidden = panel.split('<details class="hk-details"', 1)
        for n in (5, 4, 3):
            self.assertIn(f"Client nr{n}", visible)
        for n in (1, 2):
            self.assertNotIn(f"Client nr{n}", visible)
        self.assertIn("Client nr1", hidden)
        self.assertLess(visible.index("Client nr5"), visible.index("Client nr3"))
        searching = self.client.get("/?q=nr2").get_data(as_text=True)
        self.assertIn('data-force-open="1"', searching)

    def test_calendar_room_labels_have_no_state_tags(self):
        """Etichetele camerelor din calendar nu conțin pictograme de stare (decalau rândurile și coloanele)."""
        self.insert_booking(4, self.day(-2), self.day(0), "checked_in")
        self.at("14:00")
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("rs-tag", html)
        self.assertNotIn("· auto", html)
        label = re.search(r'<div class="room-label.*?</div>', html, re.S).group(0)
        self.assertEqual(label.count("<small>"), 2)          # doar paturile și baia, ca în V13

    # optimizare pentru telefon
    def test_gzip_and_static_caching(self):
        plain = self.client.get("/")
        zipped = self.client.get("/", headers={"Accept-Encoding": "gzip"})
        import gzip
        self.assertEqual(zipped.headers.get("Content-Encoding"), "gzip")
        strip = lambda raw: re.sub(rb'nonce="[^"]+"', b'nonce="N"', raw)           # nonce-ul CSP diferă la fiecare răspuns
        self.assertEqual(strip(gzip.decompress(zipped.data)), strip(plain.data))
        self.assertLess(len(zipped.data), len(plain.data) / 3)
        self.assertNotIn("Content-Encoding", plain.headers)
        css = self.client.get("/static/style.css?v=15", headers={"Accept-Encoding": "gzip"})
        self.assertIn("max-age=604800", css.headers["Cache-Control"])
        self.assertEqual(css.headers.get("Content-Encoding"), "gzip")

    def test_mobile_assets_are_served(self):
        for path in ("/static/manifest.webmanifest", "/static/icon-192.png", "/static/icon-512.png", "/static/apple-touch-icon.png",
                     "/static/alert-urgent.wav", "/static/alert-info.wav", "/static/notify.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("viewport-fit=cover", html)
        self.assertIn('rel="manifest"', html)
        self.assertIn("data-sound-urgent", html)
        js = self.client.get("/static/notify.js").get_data(as_text=True)
        for needle in ("AbortController", "TimeoutError", "wakeLock", "visibilitychange", "pageshow", "touchend", "needsAttention"):
            self.assertIn(needle, js)


    # ---- v15 r2: versiune, pontaj, șef de tură, raport ocupare ----
    def make_user(self, username, pin, staff_type="reception", role="reception", name=None):
        conn = pms.connect()
        conn.execute("DELETE FROM users WHERE username=?", (username,))
        conn.execute("INSERT INTO users(username, display_name, pin_hash, role, staff_type) VALUES (?,?,?,?,?)",
                     (username, name or username.title(), pms.generate_password_hash(pin), role, staff_type))
        conn.close()
        client = pms.app.test_client()
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
        response = client.post("/login", data={"csrf_token": token, "username": username, "pin": pin}, follow_redirects=True)
        return client, response

    def test_version_is_shown_discreetly_everywhere(self):
        import version
        self.assertRegex(version.label(), r"^v17 · r\d+ · \d\d\.\d\d\.\d{4}$")
        self.assertIn(f'<span class="app-version" title="Versiunea aplicației">{version.label()}</span>', self.client.get("/").get_data(as_text=True))
        self.assertIn(version.label(), pms.app.test_client().get("/login").get_data(as_text=True))
        os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
        self.assertEqual(self.api("/api/v1/health").get_json()["app_version"], version.label())

    def test_timesheet_tracks_periods_gaps_and_logout(self):
        from datetime import datetime as dt, date as d, time as t
        import timesheet
        clock = [dt.combine(d.today(), t(8, 0))]
        timesheet.now_fn = lambda: clock[0]
        try:
            maid, _ = self.make_user("pontaj1", "654321", "housekeeping", name="Ioana")
            def at(hh, mm, path="/api/notifications"):
                clock[0] = dt.combine(d.today(), t(hh, mm))
                with maid.session_transaction() as sess:
                    sess["ts_touch"] = 0                      # ocolește limita de 30 s din timp real
                maid.get(path)
            at(8, 5)                                          # activitate în aceeași perioadă
            at(8, 30)                                         # pauză de 25 min -> perioadă nouă
            at(8, 40)
            clock[0] = dt.combine(d.today(), t(8, 45))
            token = re.search(r'name="csrf_token" value="([^"]+)"', maid.get("/housekeeping").get_data(as_text=True)).group(1)
            maid.post("/logout", data={"csrf_token": token})
            conn = pms.connect()
            row = timesheet.summarize_day(conn, d.today().isoformat())[0]
            conn.close()
        finally:
            timesheet.now_fn = __import__("datetime").datetime.now
        self.assertEqual((row["name"], row["first"], row["last"]), ("Ioana", "08:00", "08:45"))
        self.assertEqual(row["span"], "45 min")
        self.assertEqual(row["connected"], "20 min")          # 5 + 15; pauza de 25 min nu se numără
        self.assertEqual(row["periods"], 2)

    def test_timesheet_overlapping_devices_are_not_double_counted(self):
        import timesheet
        conn = pms.connect()
        day = self.day(0)
        for start, end in (("08:00:00", "09:00:00"), ("08:30:00", "09:30:00")):
            conn.execute("INSERT INTO staff_sessions(user_id, user_name, day, login_at, last_seen_at) VALUES (1,'Ana',?,?,?)", (day, f"{day} {start}", f"{day} {end}"))
        row = timesheet.summarize_day(conn, day)[0]
        conn.close()
        self.assertEqual((row["connected"], row["span"]), ("1 h 30 min", "1 h 30 min"))

    def test_only_housekeepers_are_timed(self):
        client, _ = self.make_user("recep1", "654321", "reception")
        client.get("/")
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM staff_sessions").fetchone()[0], 0)
        conn.close()

    def test_timesheet_page_csv_and_access(self):
        conn = pms.connect()
        day = self.day(0)
        conn.execute("INSERT INTO staff_sessions(user_id, user_name, day, login_at, last_seen_at, logout_at) VALUES (9,'Maria Test',?,?,?,?)",
                     (day, f"{day} 07:30:00", f"{day} 15:10:00", f"{day} 15:10:00"))
        conn.close()
        page = self.client.get(f"/admin/timesheet?date={day}").get_data(as_text=True)
        self.assertIn("Maria Test", page)
        self.assertIn("07:30", page)
        self.assertIn("15:10", page)
        self.assertIn("7 h 40 min", page)
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn("Setări", home)
        self.assertNotIn("Raport ieri", home)                     # meniul rămâne curat; raportul se deschide din Rapoarte
        self.assertIn("/report/yesterday", self.client.get("/admin/reports").get_data(as_text=True))
        month = self.client.get(f"/admin/timesheet.csv?year={day[:4]}&month={int(day[5:7])}")
        self.assertEqual(month.status_code, 200)
        self.assertIn("text/csv", month.headers["Content-Type"])
        body = month.get_data(as_text=True)
        self.assertIn("Cameristă;Prima autentificare", body)
        self.assertIn(f"{day};Maria Test;07:30;15:10;7 h 40 min;7 h 40 min;1", body)
        self.assertEqual(self.client.get("/admin/timesheet.csv?month=13").status_code, 400)
        recep, _ = self.make_user("recep2", "654321", "reception")
        self.assertEqual(recep.get("/admin/timesheet").status_code, 403)
        maid, _ = self.make_user("pontaj2", "654321", "housekeeping")
        self.assertEqual(maid.get("/admin/timesheet").status_code, 302)

    def test_admin_creates_shift_lead_who_only_sees_the_report(self):
        token = self.csrf("/admin/users")
        self.client.post("/admin/users", data={"csrf_token": token, "username": "sef1", "display_name": "Sef Tura", "pin": "482915", "role": "shift_lead"}, follow_redirects=True)
        conn = pms.connect()
        row = conn.execute("SELECT role, staff_type FROM users WHERE username='sef1'").fetchone()
        conn.close()
        self.assertEqual((row["role"], row["staff_type"]), ("reception", "shift_lead"))
        self.assertIn("Șef de tură", self.client.get("/admin/users").get_data(as_text=True))
        lead = pms.app.test_client()
        tok = re.search(r'name="csrf_token" value="([^"]+)"', lead.get("/login").get_data(as_text=True)).group(1)
        response = lead.post("/login", data={"csrf_token": tok, "username": "sef1", "pin": "482915"}, follow_redirects=True)
        self.assertEqual(response.request.path, "/report/yesterday")
        page = response.get_data(as_text=True)
        self.assertIn("Șef de tură", page)
        self.assertNotIn('id="pmsNotify"', page)                  # fără alerte de recepție
        for path in ("/", "/booking/new", "/housekeeping", "/admin/users", "/reports", "/api/notifications"):
            reply = lead.get(path)
            self.assertEqual(reply.status_code, 302, path)
            self.assertIn("/report/yesterday", reply.headers["Location"], path)

    def test_yesterday_report_counts_only_nights_that_were_occupied(self):
        for room, a, b, status in ((1, -3, 1, "confirmed"), (2, -2, 0, "checked_out"), (3, -1, 2, "checked_in"),
                                   (4, -2, 1, "cancelled"), (5, -2, 1, "unconfirmed"), (6, 0, 2, "confirmed"),
                                   (7, -4, -1, "confirmed"), (8, -1, 1, "provisional")):
            self.insert_booking(room, self.day(a), self.day(b), status)
        page = self.client.get("/report/yesterday").get_data(as_text=True)
        self.assertRegex(page, r'<span class="yr-number">3</span>')
        self.assertIn("camere ocupate din 25", page)
        self.assertIn("12%", page)
        occupied = re.findall(r'<span class="yr-room">([^<]+)</span>', page)
        self.assertEqual(sorted(occupied), ["101", "102", "103"])
        self.assertNotIn("Client test", page)                      # fără date personale
        lead, _ = self.make_user("sef2", "654321", "shift_lead", name="Sef Doi")
        mine = lead.get("/report/yesterday?date=2020-01-01").get_data(as_text=True)
        self.assertIn(f"Noaptea de {self.day(-1)[8:]}.{self.day(-1)[5:7]}.{self.day(-1)[:4]}", mine)   # data nu se poate schimba
        old = self.client.get("/report/yesterday?date=2020-01-01").get_data(as_text=True)
        self.assertIn("01.01.2020", old)
        recep, _ = self.make_user("recep3", "654321", "reception")
        self.assertEqual(recep.get("/report/yesterday").status_code, 200)
        maid, _ = self.make_user("pontaj3", "654321", "housekeeping")
        self.assertEqual(maid.get("/report/yesterday").status_code, 302)

    def test_schema_has_timesheet_table(self):
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='staff_sessions'").fetchone()[0], 1)
        conn.close()


    # ---- v16 · 1. anulare grup: individual sau tot grupul, cu confirmare ----
    def make_group(self, name="Grup v16", rooms=("1", "2", "3")):
        token = self.csrf("/booking/group/new")
        self.client.post("/booking/group/new", data={"csrf_token": token, "guest_name": name, "phone": "0712345678", "email": "",
            "check_in": "2026-11-10", "check_out": "2026-11-12", "room_ids": list(rooms), "guests": "2", "rate": "180",
            "deposit": "0", "source": "Direct", "notes": ""}, follow_redirects=True)
        conn = pms.connect()
        rows = conn.execute("SELECT id, group_id FROM bookings WHERE guest_name=? ORDER BY id", (name,)).fetchall()
        conn.close()
        return rows[0]["group_id"], [r["id"] for r in rows]

    def group_statuses(self, group_id):
        conn = pms.connect()
        rows = [r["status"] for r in conn.execute("SELECT status FROM bookings WHERE group_id=? ORDER BY id", (group_id,)).fetchall()]
        conn.close()
        return rows

    def cancel_group(self, group_id, **fields):
        token = self.csrf("/")
        return self.client.post(f"/booking/group/{group_id}/cancel", data={"csrf_token": token, **fields}, follow_redirects=True)

    def test_group_cancel_one_room_leaves_the_rest_active(self):
        gid, ids = self.make_group()
        reply = self.cancel_group(gid, scope="selected", confirmed="1", booking_ids=[str(ids[1])])
        self.assertEqual(self.group_statuses(gid), ["provisional", "cancelled", "provisional"])
        self.assertIn("Rămân active 2 camere", reply.get_data(as_text=True))

    def test_group_cancel_several_selected_rooms(self):
        gid, ids = self.make_group()
        self.cancel_group(gid, scope="selected", confirmed="1", booking_ids=[str(ids[0]), str(ids[2])])
        self.assertEqual(self.group_statuses(gid), ["cancelled", "provisional", "cancelled"])

    def test_group_cancel_all_requires_explicit_scope_all(self):
        gid, ids = self.make_group()
        reply = self.cancel_group(gid, scope="all", confirmed="1")
        self.assertEqual(self.group_statuses(gid), ["cancelled"] * 3)
        self.assertIn("Întregul grup a fost anulat", reply.get_data(as_text=True))

    def test_group_cancel_without_confirmation_or_scope_changes_nothing(self):
        gid, ids = self.make_group()
        self.cancel_group(gid, scope="all")                                   # fără confirmare
        self.cancel_group(gid, confirmed="1", booking_ids=[str(ids[0])])       # fără scope: nu se presupune „tot grupul"
        self.cancel_group(gid)
        self.cancel_group(gid, scope="selected", confirmed="1")                # selectat, dar nimic bifat
        self.assertEqual(self.group_statuses(gid), ["provisional"] * 3)

    def test_group_cancel_rejects_foreign_or_malformed_ids(self):
        gid, ids = self.make_group()
        other, other_ids = self.make_group("Alt grup", ("4", "5"))
        self.cancel_group(gid, scope="selected", confirmed="1", booking_ids=[str(ids[0]), str(other_ids[0])])
        self.cancel_group(gid, scope="selected", confirmed="1", booking_ids=["abc"])
        self.assertEqual(self.group_statuses(gid), ["provisional"] * 3)
        self.assertEqual(self.group_statuses(other), ["provisional"] * 2)

    def test_group_panel_has_two_explicit_actions_and_no_preselected_scope(self):
        gid, ids = self.make_group()
        html = self.client.get(f"/booking/{ids[0]}/edit").get_data(as_text=True)
        panel = html.split('id="groupPanel"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn('type="radio"', panel)                       # nu mai există „tot grupul" bifat implicit
        self.assertNotRegex(panel, r'name="booking_ids"[^>]*\bchecked\b')
        self.assertIn('data-group-action="selected"', panel)
        self.assertIn('data-group-action="all"', panel)
        self.assertIn("Anulează tot grupul", panel)
        self.assertIn('<dialog id="groupConfirm"', panel)
        self.assertIn('Anulează doar această rezervare', html)


    # ---- v16 · 2. număr de persoane obligatoriu ----
    def booking_count(self):
        conn = pms.connect()
        n = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        conn.close()
        return n

    def test_guests_is_mandatory_for_single_booking(self):
        for bad in ("", "0", "3", "-1", "abc"):
            token = self.csrf()
            data = {"csrf_token": token, "guest_name": "Fara persoane", "phone": "", "email": "", "room_id": "1", "check_in": "2026-11-01",
                    "check_out": "2026-11-03", "rate": "200", "deposit": "0", "source": "Direct", "status": "confirmed", "notes": ""}
            if bad != "":
                data["guests"] = bad
            self.client.post("/booking/new", data=data, follow_redirects=True)
            self.assertEqual(self.booking_count(), 0, f"guests={bad!r} nu trebuia acceptat")
        response = self.client.post("/booking/new", data={**data, "csrf_token": self.csrf()}, follow_redirects=True)   # câmp lipsă complet
        self.assertIn("obligatoriu", response.get_data(as_text=True))
        self.assertEqual(self.booking_count(), 0)

    def test_guests_accepts_one_or_two(self):
        for n, g in enumerate(("1", "2")):
            self.post_booking(f"Cu persoane {g}", room_id=str(n + 1), guests=g)
        self.assertEqual(self.booking_count(), 2)

    def test_guests_is_mandatory_for_group_and_edit(self):
        token = self.csrf("/booking/group/new")
        base = {"csrf_token": token, "guest_name": "Grup fara persoane", "phone": "0712345678", "email": "", "check_in": "2026-11-10",
                "check_out": "2026-11-12", "room_ids": ["1", "2"], "rate": "180", "deposit": "0", "source": "Direct", "notes": ""}
        self.client.post("/booking/group/new", data=base, follow_redirects=True)
        self.client.post("/booking/group/new", data={**base, "guests": ""}, follow_redirects=True)
        self.assertEqual(self.booking_count(), 0)
        self.post_booking("Editabil", room_id="3")
        conn = pms.connect()
        bid = conn.execute("SELECT id FROM bookings").fetchone()["id"]
        conn.close()
        token = self.csrf(f"/booking/{bid}/edit")
        self.client.post(f"/booking/{bid}/edit", data={"csrf_token": token, "guest_name": "Editabil", "phone": "", "email": "", "room_id": "3",
            "check_in": "2026-11-01", "check_out": "2026-11-03", "guests": "", "rate": "200", "deposit": "0", "source": "Direct", "status": "confirmed", "notes": ""}, follow_redirects=True)
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT guests FROM bookings WHERE id=?", (bid,)).fetchone()["guests"], 2)   # nu s-a modificat
        conn.close()

    def test_guests_field_is_required_select_without_default(self):
        html = self.client.get("/booking/new?room_id=1&check_in=2026-11-01").get_data(as_text=True)
        field = re.search(r'<select name="guests".*?</select>', html, re.S).group(0)
        self.assertIn("required", field)
        self.assertNotRegex(field, r'<option value="[12]"[^>]*selected')       # nimic preselectat
        group = self.client.get("/booking/group/new?check_in=2026-11-10&check_out=2026-11-12").get_data(as_text=True)
        self.assertIn("required", re.search(r'<select name="guests".*?</select>', group, re.S).group(0))
        self.post_booking("Edit prefill", room_id="4", guests="1")
        conn = pms.connect()
        bid = conn.execute("SELECT id FROM bookings").fetchone()["id"]
        conn.close()
        edit = re.search(r'<select name="guests".*?</select>', self.client.get(f"/booking/{bid}/edit").get_data(as_text=True), re.S).group(0)
        self.assertRegex(edit, r'<option value="1"[^>]*selected')


    # ---- v16 · 3. total încasări în raportul șefului de tură ----
    def test_shift_lead_report_shows_total_revenue_for_the_night(self):
        conn = pms.connect()
        def put(room, a, b, status, rate, payment=None):
            conn.execute("""INSERT INTO bookings(guest_name, room_id, check_in, check_out, guests, rate, source, status, night_payment)
                            VALUES ('Nume secret', ?, ?, ?, 2, ?, 'Telefon', ?, ?)""", (room, self.day(a), self.day(b), rate, status, payment))
        put(1, -2, 1, "confirmed", 200)            # ocupată
        put(2, -2, 0, "checked_out", 250.5)        # ocupată (a plecat azi)
        put(3, -1, 0, "checked_in", 180, "cash")                     # cazare de noapte, încasat cash
        put(4, -1, 0, "checked_in", 220, "morning")                  # cazare de noapte, de încasat dimineața
        put(5, -1, 1, "cancelled", 999)            # anulată: nu intră
        put(6, 0, 2, "confirmed", 999)             # sosește azi: nu intră
        put(7, -4, -1, "confirmed", 999)           # a plecat ieri: nu intră
        conn.close()
        lead, _ = self.make_user("sef_bani", "654321", "shift_lead", name="Sef Bani")
        page = lead.get("/report/yesterday").get_data(as_text=True)
        self.assertIn("Total încasări pentru noaptea aceasta", page)
        self.assertIn("Informativ", page)
        self.assertIn("850,50 lei", page)                            # 200 + 250,50 + 180 + 220
        self.assertIn("Încasat cash: <b>180,00 lei</b>", page)
        self.assertIn("De încasat la recepție dimineața: <b>220,00 lei</b>", page)
        self.assertNotIn("Nume secret", page)
        self.assertNotIn("999", page)

    def test_revenue_is_zero_without_stays_and_lei_format(self):
        lead, _ = self.make_user("sef_zero", "654321", "shift_lead")
        page = lead.get("/report/yesterday").get_data(as_text=True)
        self.assertIn("0,00 lei", page)
        self.assertNotIn("Cazări la recepția de noapte", page)
        self.assertEqual(pms.lei_filter(1234567.5), "1.234.567,50 lei")
        self.assertEqual(pms.lei_filter(None), "0,00 lei")


    # ---- v16 · 4. recepția de noapte ----
    def setUpNight(self, hhmm="23:00", rate=200):
        self.at(hhmm)
        import night
        night.now_fn = pms.room_state.now_fn
        conn = pms.connect()
        conn.execute("UPDATE rooms SET default_rate=?", (rate,))
        conn.close()
        client, _ = self.make_user("noapte1", "654321", "night_reception", name="Receptioner Noapte")
        return client

    def night_row(self, **where):
        conn = pms.connect()
        rows = conn.execute("SELECT * FROM bookings ORDER BY id").fetchall()
        conn.close()
        return rows

    def night_post(self, client, path, **fields):
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/night").get_data(as_text=True)).group(1)
        return client.post(path, data={"csrf_token": token, **fields}, follow_redirects=True)

    def test_night_access_control(self):
        night_user = self.setUpNight()
        self.assertEqual(night_user.get("/night").status_code, 200)
        self.assertEqual(self.client.get("/night").status_code, 200)                      # administrator
        recep, _ = self.make_user("recep_n", "654321", "reception")
        self.assertEqual(recep.get("/night").status_code, 403)                            # recepția de zi nu vede secțiunea
        maid, _ = self.make_user("maid_n", "654321", "housekeeping")
        self.assertEqual(maid.get("/night").status_code, 302)
        lead, _ = self.make_user("lead_n", "654321", "shift_lead")
        self.assertEqual(lead.get("/night").status_code, 302)
        self.assertEqual(pms.app.test_client().get("/night").status_code, 302)           # neautentificat
        for path in ("/", "/booking/new", "/housekeeping", "/admin/users", "/report/yesterday", "/api/notifications"):
            reply = night_user.get(path)
            self.assertEqual(reply.status_code, 302, path)
            self.assertIn("/night", reply.headers["Location"], path)
        page = night_user.get("/night").get_data(as_text=True)
        self.assertNotIn('id="pmsNotify"', page)
        self.assertIn("Recepție noapte", page)

    def test_admin_creates_night_reception_user(self):
        token = self.csrf("/admin/users")
        self.client.post("/admin/users", data={"csrf_token": token, "username": "nuser", "display_name": "N User", "pin": "135790", "role": "night_reception"}, follow_redirects=True)
        conn = pms.connect()
        row = conn.execute("SELECT role, staff_type FROM users WHERE username='nuser'").fetchone()
        conn.close()
        self.assertEqual((row["role"], row["staff_type"]), ("reception", "night_reception"))

    def test_night_grid_shows_states_without_personal_details(self):
        night_user = self.setUpNight("23:00")
        today = self.day(0)
        def put(room, a, b, status, late=0, phone=""):
            self.insert_booking(room, self.day(a), self.day(b), status)
            conn = pms.connect()
            conn.execute("UPDATE bookings SET late_arrival=?, phone=?, guest_name='Nume Secret Client' WHERE id=(SELECT MAX(id) FROM bookings)", (late, phone))
            conn.close()
        put(1, -1, 2, "checked_in")                    # ocupată
        put(2, -2, 1, "confirmed")                     # în sejur (nemarcat) -> ocupată
        put(3, 0, 1, "confirmed")                      # rezervată (fără sosire târzie)
        put(4, 0, 1, "unconfirmed", 0, "0711000111")   # așteptat
        put(5, 0, 1, "confirmed", 1, "0722000222")     # sosire târzie declarată
        put(6, 0, 1, "cancelled")                      # anulată -> liberă
        put(7, 1, 2, "confirmed")                      # mâine -> liberă azi-noapte
        conn = pms.connect()
        conn.execute("UPDATE rooms SET out_of_order=1 WHERE id=8")
        grid = {r["room_id"]: r["state"] for r in pms.night.grid(conn, pms.date.fromisoformat(today))}
        conn.close()
        self.assertEqual([grid[i] for i in range(1, 9)], ["occupied", "occupied", "reserved", "late", "late", "free", "free", "out_of_order"])
        page = night_user.get("/night").get_data(as_text=True)
        tiles = page.split('class="nd-grid"', 1)[1]
        self.assertNotIn("Nume Secret Client", tiles)                                       # în grilă nu apar nume
        self.assertEqual(len(re.findall(r'<article class="nd-late-card', page)), 2)         # doar sosirile târzii au detalii
        self.assertIn("0711000111", page)
        self.assertIn("0722000222", page)

    def test_walk_in_occupy_creates_locked_checkin_and_validates_input(self):
        night_user = self.setUpNight("23:30")
        good = {"mode": "occupy", "guest_name": "  Ion   Popescu ", "guests": "2", "payment": "cash"}
        for bad in ({"guest_name": ""}, {"guest_name": "X"}, {"guests": ""}, {"guests": "3"}, {"guests": "abc"}, {"payment": ""}, {"payment": "card"}, {"mode": "altceva"}):
            self.night_post(night_user, "/night/room/9", **{**good, **bad})
            self.assertEqual(self.booking_count(), 0, f"{bad} nu trebuia acceptat")
        reply = self.night_post(night_user, "/night/room/9", **good)
        self.assertIn("a fost cazată pe numele Ion Popescu", reply.get_data(as_text=True))
        b = self.night_row()[0]
        self.assertEqual((b["status"], b["check_in"], b["check_out"], b["guests"], b["rate"], b["night_payment"], b["source"]),
                         ("checked_in", self.day(0), self.day(1), 2, 200.0, "cash", "Recepție noapte"))
        self.assertEqual(b["guest_name"], "Ion Popescu")
        self.assertIsNotNone(b["night_by"])
        # nu se poate caza a doua oară aceeași cameră
        self.night_post(night_user, "/night/room/9", **{**good, "guest_name": "Altcineva"})
        self.assertEqual(self.booking_count(), 1)

    def test_occupied_room_is_locked_for_night_reception(self):
        night_user = self.setUpNight("23:30")
        self.night_post(night_user, "/night/room/10", mode="occupy", guest_name="Maria Ionescu", guests="1", payment="morning")
        bid = self.night_row()[0]["id"]
        self.night_post(night_user, f"/night/booking/{bid}/cancel")
        self.night_post(night_user, f"/night/booking/{bid}/arrived", payment="cash")
        self.night_post(night_user, "/night/room/10", mode="reserve", guest_name="Altcineva", guests="1")
        rows = self.night_row()
        self.assertEqual((len(rows), rows[0]["status"], rows[0]["night_payment"]), (1, "checked_in", "morning"))   # nimic nu s-a schimbat
        for path in (f"/booking/{bid}/edit", f"/booking/{bid}/cancel"):
            self.assertEqual(night_user.get(path).status_code, 302)                     # nu are acces la modificări generale
        # recepția de zi și administratorul pot modifica
        page = self.client.get(f"/booking/{bid}/edit").get_data(as_text=True)
        self.assertRegex(page, r'<option selected>Recepție noapte</option>')

    def test_reserve_free_room_goes_to_late_arrivals_and_can_be_cancelled(self):
        night_user = self.setUpNight("22:00")
        self.night_post(night_user, "/night/room/11", mode="reserve", guest_name="Vine Tarziu", guests="2")
        b = self.night_row()[0]
        self.assertEqual((b["status"], b["late_arrival"], b["night_payment"]), ("confirmed", 1, None))
        self.assertIn("Vine Tarziu", night_user.get("/night").get_data(as_text=True))
        self.night_post(night_user, f"/night/booking/{b['id']}/cancel")
        self.assertEqual(self.night_row()[0]["status"], "cancelled")
        self.night_post(night_user, "/night/room/11", mode="occupy", guest_name="Alt Client", guests="1", payment="cash")   # camera e din nou liberă
        self.assertEqual(self.night_row()[1]["status"], "checked_in")

    def test_late_arrival_flow_arrive_requires_payment_and_cancel_only_for_late(self):
        night_user = self.setUpNight("22:15")
        self.insert_booking(12, self.day(0), self.day(1), "unconfirmed")
        self.insert_booking(13, self.day(0), self.day(1), "confirmed")          # confirmată normal, NU sosire târzie
        conn = pms.connect()
        conn.execute("UPDATE bookings SET phone='0733555666', night_note='Cheia la poarta 2', guest_name='Sosire Tarzie' WHERE room_id=12")
        ids = {r["room_id"]: r["id"] for r in conn.execute("SELECT id, room_id FROM bookings").fetchall()}
        conn.close()
        page = night_user.get("/night").get_data(as_text=True)
        self.assertIn("Sosire Tarzie", page)
        self.assertIn("0733555666", page)
        self.assertIn("Cheia la poarta 2", page)
        self.assertIn("Neconfirmată", page)
        self.night_post(night_user, f"/night/booking/{ids[12]}/arrived")                       # fără plată
        self.assertEqual(self.night_row()[0]["status"], "unconfirmed")
        self.night_post(night_user, f"/night/booking/{ids[13]}/cancel")                        # rezervare normală: nu poate fi anulată de noapte
        self.night_post(night_user, f"/night/booking/{ids[13]}/arrived", payment="cash")
        self.assertEqual([r["status"] for r in self.night_row()], ["unconfirmed", "confirmed"])
        self.night_post(night_user, f"/night/booking/{ids[12]}/arrived", payment="morning")
        row = self.night_row()[0]
        self.assertEqual((row["status"], row["night_payment"]), ("checked_in", "morning"))

    def test_unconfirmed_booking_becomes_late_arrival_at_reception_close(self):
        self.at("20:59")
        self.insert_booking(14, self.day(0), self.day(1), "unconfirmed")
        self.insert_booking(15, self.day(0), self.day(1), "unconfirmed")
        self.insert_booking(15, self.day(0), self.day(1), "confirmed")        # cameră re-vândută: conflict
        self.assertEqual(pms.apply_late_arrival_confirmation(), 0)             # înainte de 21:00 nu se schimbă nimic
        self.at("21:00")
        self.assertEqual(pms.apply_late_arrival_confirmation(), 1)
        conn = pms.connect()
        rows = {r["id"]: r for r in conn.execute("SELECT id, room_id, status, late_arrival FROM bookings ORDER BY id").fetchall()}
        audit = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='automatic_late_confirm'").fetchone()[0]
        conn.close()
        order = sorted(rows)
        self.assertEqual((rows[order[0]]["status"], rows[order[0]]["late_arrival"]), ("confirmed", 1))
        self.assertEqual(rows[order[1]]["status"], "unconfirmed")              # conflict: rămâne neconfirmată
        self.assertEqual(audit, 1)
        self.assertEqual(pms.apply_late_arrival_confirmation(), 0)             # idempotent
        # în listă, rezervarea cu conflict este marcată și nu poate fi cazată
        conn = pms.connect()
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM rooms").fetchall()}
        late = {a["room_name"]: a for a in pms.night.late_arrivals(conn, pms.date.today())}
        conn.close()
        self.assertTrue(late[names[15]]["blocked"])
        self.assertFalse(late[names[14]]["blocked"])

    def test_night_actions_only_inside_night_window_but_admin_always(self):
        night_user = self.setUpNight("14:00")
        page = night_user.get("/night").get_data(as_text=True)
        self.assertIn("Acum puteți doar vizualiza", page)
        self.assertNotIn("data-night-room", page)
        reply = self.night_post(night_user, "/night/room/16", mode="occupy", guest_name="Ziua Client", guests="1", payment="cash")
        self.assertIn("Recepția de noapte este activă între 21:00 și 06:00", reply.get_data(as_text=True))
        self.assertEqual(self.booking_count(), 0)
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.client.get("/night").get_data(as_text=True)).group(1)
        self.client.post("/night/room/16", data={"csrf_token": token, "mode": "occupy", "guest_name": "Test Admin", "guests": "1", "payment": "cash"}, follow_redirects=True)
        self.assertEqual(self.booking_count(), 1)

    def test_after_midnight_the_night_belongs_to_the_previous_date(self):
        night_user = self.setUpNight("02:30")
        self.night_post(night_user, "/night/room/17", mode="occupy", guest_name="Dupa Miezul Noptii", guests="1", payment="cash")
        b = self.night_row()[0]
        self.assertEqual((b["check_in"], b["check_out"]), (self.day(-1), self.day(0)))
        self.assertIn(f"Noaptea de {self.day(-1)[8:]}.{self.day(-1)[5:7]}", night_user.get("/night").get_data(as_text=True))
        self.at("05:59")
        self.assertNotIn("Acum puteți doar vizualiza", night_user.get("/night").get_data(as_text=True))   # 05:59: încă program de noapte
        self.at("06:00")                                                         # la 06:00 programul de noapte s-a încheiat
        self.assertIn("Acum puteți doar vizualiza", night_user.get("/night").get_data(as_text=True))

    def test_walk_in_blocked_when_rate_unset_and_env_default_works(self):
        night_user = self.setUpNight("23:00", rate=0)
        reply = self.night_post(night_user, "/night/room/18", mode="occupy", guest_name="Fara Tarif", guests="1", payment="cash")
        self.assertIn("Tariful camerei", reply.get_data(as_text=True))
        self.assertEqual(self.booking_count(), 0)
        os.environ["MOTEL_NIGHT_DEFAULT_RATE"] = "150"
        try:
            self.night_post(night_user, "/night/room/18", mode="occupy", guest_name="Cu Tarif", guests="1", payment="cash")
        finally:
            os.environ.pop("MOTEL_NIGHT_DEFAULT_RATE", None)
        self.assertEqual(self.night_row()[0]["rate"], 150.0)

    def test_unconfirmed_late_booking_blocks_walk_in_on_same_room(self):
        night_user = self.setUpNight("22:00")
        self.insert_booking(19, self.day(0), self.day(1), "unconfirmed")
        self.night_post(night_user, "/night/room/19", mode="occupy", guest_name="Walk In", guests="1", payment="cash")
        self.assertEqual(self.booking_count(), 1)

    def test_day_reception_night_notes_only_for_late_arrivals(self):
        base = {"guest_name": "Client Observatie", "phone": "0744000111", "email": "", "room_id": "20", "check_in": self.day(1), "check_out": self.day(2),
                "guests": "2", "rate": "200", "deposit": "0", "source": "Telefon", "status": "confirmed", "notes": "", "night_note": "Cheia la receptie"}
        self.client.post("/booking/new", data={**base, "csrf_token": self.csrf()}, follow_redirects=True)
        self.assertEqual(self.booking_count(), 0)                                # fără „sosește după 21:00” nu se acceptă observații
        reply = self.client.post("/booking/new", data={**base, "csrf_token": self.csrf()}, follow_redirects=True)
        self.assertIn("doar pentru sosiri după ora 21:00", reply.get_data(as_text=True))
        self.client.post("/booking/new", data={**base, "late_arrival": "1", "csrf_token": self.csrf()}, follow_redirects=True)
        row = self.night_row()[0]
        self.assertEqual((row["late_arrival"], row["night_note"]), (1, "Cheia la receptie"))
        edit = self.client.get(f"/booking/{row['id']}/edit").get_data(as_text=True)
        self.assertIn("checked", re.search(r'name="late_arrival"[^>]*>', edit).group(0))
        self.assertIn("Cheia la receptie", edit)

    def test_night_note_is_escaped_for_night_reception(self):
        night_user = self.setUpNight("22:00")
        self.insert_booking(21, self.day(0), self.day(1), "unconfirmed")
        conn = pms.connect()
        conn.execute("UPDATE bookings SET night_note='<script>alert(1)</script>', guest_name='<img src=x onerror=alert(2)>' ")
        conn.close()
        page = night_user.get("/night").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)

    def test_morning_payment_panel_for_day_reception(self):
        night_user = self.setUpNight("23:00")
        self.night_post(night_user, "/night/room/22", mode="occupy", guest_name="Plata Dimineata", guests="2", payment="morning")
        bid = self.night_row()[0]["id"]
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn("De încasat dimineața", home)
        self.assertIn("Plata Dimineata", home)
        self.assertIn("200,00 lei", home)
        self.client.post(f"/booking/{bid}/night-payment-collected", data={"csrf_token": self.csrf()}, follow_redirects=True)
        self.assertEqual(self.night_row()[0]["night_payment"], "collected")
        self.assertNotIn("De încasat dimineața", self.client.get("/").get_data(as_text=True))
        self.assertEqual(self.client.post(f"/booking/{bid}/night-payment-collected", data={"csrf_token": self.csrf()}).status_code, 404)

    def test_admin_sets_room_rate_and_input_is_validated(self):
        self.client.post("/admin/rooms/rate", data={"csrf_token": self.csrf("/admin/rooms"), "room_id": "1", "default_rate": "180.5"}, follow_redirects=True)
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT default_rate FROM rooms WHERE id=1").fetchone()[0], 180.5)
        conn.close()
        self.client.post("/admin/rooms/rate", data={"csrf_token": self.csrf("/admin/rooms"), "room_id": "1", "default_rate": "-5"}, follow_redirects=True)
        self.client.post("/admin/rooms/rate", data={"csrf_token": self.csrf("/admin/rooms"), "room_id": "1", "default_rate": "99999"}, follow_redirects=True)
        self.assertEqual(self.client.post("/admin/rooms/rate", data={"csrf_token": self.csrf("/admin/rooms"), "room_id": "1", "default_rate": "abc"}).status_code, 400)
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT default_rate FROM rooms WHERE id=1").fetchone()[0], 180.5)
        conn.close()
        recep, _ = self.make_user("recep_r", "654321", "reception")
        self.assertEqual(recep.post("/admin/rooms/rate", data={"room_id": "1", "default_rate": "1"}).status_code in (400, 403), True)

    def test_night_actions_require_csrf_and_are_audited(self):
        night_user = self.setUpNight("23:00")
        self.assertEqual(night_user.post("/night/room/1", data={"mode": "occupy", "guest_name": "Fara Token", "guests": "1", "payment": "cash"}).status_code, 400)
        self.assertEqual(self.booking_count(), 0)
        self.night_post(night_user, "/night/room/1", mode="occupy", guest_name="Cu Token", guests="1", payment="cash")
        conn = pms.connect()
        audit = conn.execute("SELECT username, action FROM audit_log WHERE action='night_checkin'").fetchone()
        event = conn.execute("SELECT room_code FROM room_events WHERE event_type='booking_created' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertEqual((audit["username"], event["room_code"]), ("noapte1", "camera_101"))


    # ======== v16 · 5. verificări de securitate ========
    def concrete_path(self, rule):
        path = re.sub(r"<int:[^>]+>", "1", rule.rule)
        return re.sub(r"<[^>]+>", "x", path)

    def app_rules(self, include_api=False):
        for rule in pms.app.url_map.iter_rules():
            if rule.endpoint == "static" or (rule.rule.startswith("/api/v1/") and not include_api):
                continue
            yield rule

    def role_clients(self):
        clients = {}
        for key, staff in (("reception", "reception"), ("housekeeping", "housekeeping"), ("shift_lead", "shift_lead"), ("night", "night_reception")):
            clients[key], _ = self.make_user(f"sec_{key}", "482915", staff)
        return clients

    def csrf_from(self, client, path):
        return re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).get_data(as_text=True)).group(1)

    def test_every_route_requires_authentication_by_default(self):
        anon = pms.app.test_client()
        tested = 0
        for rule in self.app_rules():
            if rule.endpoint in ("login", "setup", "login_2fa", "login_2fa_setup"):   # publice prin construcție; testate separat
                continue
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                reply = anon.open(self.concrete_path(rule), method=method)
                self.assertEqual(reply.status_code, 302, f"{method} {rule.rule} accesibil fără autentificare")
                self.assertIn("/login", reply.headers["Location"], f"{method} {rule.rule}")
                tested += 1
        self.assertGreater(tested, 40)

    def test_integration_api_requires_token_on_every_route(self):
        os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
        anon = pms.app.test_client()
        count = 0
        for rule in self.app_rules(include_api=True):
            if not rule.rule.startswith("/api/v1/"):
                continue
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                self.assertEqual(anon.open(self.concrete_path(rule), method=method).status_code, 401, rule.rule)
                count += 1
        self.assertGreaterEqual(count, 5)

    def test_admin_routes_are_closed_to_every_other_role(self):
        clients = self.role_clients()
        admin_endpoints = [ep for ep, fn in pms.app.view_functions.items() if getattr(fn, "admin_only", False)]
        self.assertGreater(len(admin_endpoints), 8)
        checked = 0
        for rule in self.app_rules():
            if rule.endpoint not in admin_endpoints:
                continue
            path = self.concrete_path(rule)
            method = "GET" if "GET" in rule.methods else "POST"
            for role, client in clients.items():
                landing = {"reception": "/", "housekeeping": "/housekeeping", "shift_lead": "/report/yesterday", "night": "/night"}[role]
                data = {"csrf_token": self.csrf_from(client, landing)} if method == "POST" else None
                reply = client.open(path, method=method, data=data)
                self.assertIn(reply.status_code, (302, 403), f"{role} a ajuns la {method} {rule.rule}: {reply.status_code}")
                if reply.status_code == 302:
                    self.assertNotIn(path, reply.headers["Location"])
                checked += 1
        self.assertGreater(checked, 30)

    def test_csrf_is_enforced_on_every_post_route(self):
        count = 0
        for rule in self.app_rules():
            if "POST" not in rule.methods:
                continue
            reply = self.client.post(self.concrete_path(rule), data={"x": "1"})
            self.assertEqual(reply.status_code, 400, f"POST {rule.rule} fără token CSRF: {reply.status_code}")
            count += 1
        self.assertGreater(count, 15)
        anon = pms.app.test_client()
        self.assertEqual(anon.post("/login", data={"username": "admin", "pin": "123456"}).status_code, 400)

    def test_security_headers_everywhere(self):
        for path, anon in (("/", False), ("/login", True), ("/static/style.css", False), ("/nu-exista", False)):
            client = pms.app.test_client() if anon else self.client
            reply = client.get(path)
            h = reply.headers
            csp = h["Content-Security-Policy"]
            self.assertRegex(csp, r"script-src 'self' 'nonce-[A-Za-z0-9_\-]+'")
            self.assertNotIn("unsafe-inline'", csp.split("script-src", 1)[1].split(";", 1)[0])
            for needle in ("object-src 'none'", "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'", "default-src 'self'"):
                self.assertIn(needle, csp, path)
            self.assertEqual(h["X-Frame-Options"], "DENY")
            self.assertEqual(h["X-Content-Type-Options"], "nosniff")
            self.assertEqual(h["Referrer-Policy"], "same-origin")
            self.assertIn("geolocation=()", h["Permissions-Policy"])
            self.assertEqual(h["Server"], "PMS")
            self.assertNotIn("Strict-Transport-Security", h)          # HTTP simplu: fără HSTS
        self.assertEqual(self.client.get("/").headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/api/notifications").headers["Cache-Control"], "no-store")
        self.assertNotEqual(self.client.get("/static/style.css").headers.get("Cache-Control"), "no-store")
        pms.app.config["SESSION_COOKIE_SECURE"] = True
        secure = self.client.get("/").headers
        self.assertIn("max-age=31536000", secure["Strict-Transport-Security"])
        self.assertIn("upgrade-insecure-requests", secure["Content-Security-Policy"])

    def test_no_inline_handlers_and_every_inline_script_has_the_csp_nonce(self):
        self.make_group("Grup csp")
        conn = pms.connect()
        gb = conn.execute("SELECT id FROM bookings WHERE guest_name='Grup csp' LIMIT 1").fetchone()["id"]
        conn.close()
        pages = ["/", "/booking/new", "/booking/group/new", f"/booking/{gb}/edit", "/housekeeping", "/housekeeping/deep-clean", "/deep-clean/reports",
                 "/admin/users", "/admin/rooms", "/admin/reports", "/admin/audit", "/admin/timesheet", "/report/yesterday", "/night", "/nu-exista"]
        for path in pages:
            reply = self.client.get(path)
            html, nonce = reply.get_data(as_text=True), re.search(r"nonce-([A-Za-z0-9_\-]+)", reply.headers["Content-Security-Policy"]).group(1)
            self.assertIsNone(re.search(r"<[^>]+\s(?!data-)on[a-z]+\s*=", html), f"handler inline în {path}")
            self.assertNotIn("javascript:", html.lower(), path)
            for tag in re.findall(r"<script\b[^>]*>", html):
                if "src=" not in tag:
                    self.assertIn(f'nonce="{nonce}"', tag, f"script fără nonce în {path}")

    def test_session_cookie_flags_and_secret_key_management(self):
        client = pms.app.test_client()
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
        cookie = client.post("/login", data={"csrf_token": token, "username": "admin", "pin": "123456"}).headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        pms.app.config["SESSION_COOKIE_SECURE"] = True
        client2 = pms.app.test_client()
        token = re.search(r'name="csrf_token" value="([^"]+)"', client2.get("/login").get_data(as_text=True)).group(1)
        self.assertIn("Secure", client2.post("/login", data={"csrf_token": token, "username": "admin", "pin": "123456"}).headers.get("Set-Cookie", ""))
        pms.app.config["SESSION_COOKIE_SECURE"] = False
        self.assertGreaterEqual(len(pms.app.secret_key), 32)
        self.assertNotIn("local-development", pms.app.secret_key)
        import tempfile as tf
        previous_path, previous_env = pms.DB_PATH, os.environ.pop("MOTEL_SECRET_KEY", None)
        with tf.TemporaryDirectory() as folder:
            pms.DB_PATH = os.path.join(folder, "x.db")
            first = pms.load_secret_key()
            self.assertEqual((len(first), pms.load_secret_key()), (64, first))     # generată aleatoriu și persistată
            if os.name == "posix":
                self.assertEqual(os.stat(os.path.join(folder, "secret.key")).st_mode & 0o077, 0)
            os.environ["MOTEL_SECRET_KEY"] = "prea-scurta"
            self.assertEqual(pms.load_secret_key(), first)                         # cheia scurtă din mediu este ignorată
            os.environ["MOTEL_SECRET_KEY"] = "din-mediu-" + "x" * 30
            self.assertTrue(pms.load_secret_key().startswith("din-mediu-"))
        pms.DB_PATH = previous_path
        if previous_env is None:
            os.environ.pop("MOTEL_SECRET_KEY", None)
        else:
            os.environ["MOTEL_SECRET_KEY"] = previous_env

    def test_idle_timeout_and_passive_polling_does_not_extend_session(self):
        import time as tm
        def set_last(client, seconds_ago):
            with client.session_transaction() as sess:
                sess["last_active"] = tm.time() - seconds_ago
        set_last(self.client, 31 * 60)                                            # administrator inactiv 31 min
        reply = self.client.get("/admin/users")
        self.assertEqual(reply.status_code, 302)
        self.assertIn("/login", reply.headers["Location"])
        recep, _ = self.make_user("idle_rec", "482915", "reception")
        set_last(recep, 31 * 60)
        self.assertEqual(recep.get("/").status_code, 200)                           # personalul rămâne 12 h
        set_last(recep, 13 * 3600)
        self.assertEqual(recep.get("/").status_code, 302)
        admin2, _ = self.make_user("idle_admin", "482915", "reception", role="admin")
        set_last(admin2, 29 * 60)
        admin2.get("/api/notifications")                                            # interogare automată: nu prelungește
        with admin2.session_transaction() as sess:
            self.assertLess(tm.time() - sess["last_active"], 29 * 60 + 60)
            self.assertGreater(tm.time() - sess["last_active"], 29 * 60 - 5)
        admin2.get("/admin/users")                                                  # acțiune reală: prelungește
        with admin2.session_transaction() as sess:
            self.assertLess(tm.time() - sess["last_active"], 5)

    def test_login_lockouts_and_generic_errors(self):
        def attempt(username, pin, ip):
            client = pms.app.test_client()
            token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
            return client.post("/login", data={"csrf_token": token, "username": username, "pin": pin}, environ_overrides={"REMOTE_ADDR": ip}, follow_redirects=True)
        wrong_user = attempt("nu-exista", "999999", "10.9.0.1").get_data(as_text=True)
        wrong_pin = attempt("admin", "999999", "10.9.0.2").get_data(as_text=True)
        msg = lambda html: re.search(r'class="flash error">([^<]+)<', html).group(1)
        self.assertEqual(msg(wrong_user), msg(wrong_pin))                           # nu se poate afla ce utilizatori există
        for i in range(9):                                                          # 10 eșecuri total pe utilizator, de pe IP-uri diferite
            attempt("admin", "999999", f"10.9.1.{i}")
        locked = attempt("admin", "123456", "10.9.2.1").get_data(as_text=True)      # PIN corect, dar contul este blocat temporar
        self.assertIn("Prea multe încercări", locked)
        self.assertNotIn("Calendar rezervări", locked)
        for i in range(5):
            attempt("altcineva", "999999", "10.9.3.1")
        self.assertIn("Prea multe încercări", attempt("admin2x", "999999", "10.9.3.1").get_data(as_text=True))   # blocare pe IP
        self.assertTrue(pms.DUMMY_PIN_HASH)

    def test_open_redirect_variants_are_rejected(self):
        import safety
        for bad in ("//evil.com", "/\\evil.com", "http://evil.com", "https://evil.com/x", "javascript:alert(1)", "evil.com", "/ok\r\nSet-Cookie: x=1", "///evil.com", ""):
            self.assertEqual(safety.safe_next(bad, "/home"), "/home", repr(bad))
        self.assertEqual(safety.safe_next("/admin/users?x=1", "/home"), "/admin/users?x=1")
        for bad in ("//evil.com", "/\\evil.com", "http://evil.com"):
            client = pms.app.test_client()
            token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
            reply = client.post("/login?next=" + bad, data={"csrf_token": token, "username": "admin", "pin": "123456"})
            self.assertEqual(reply.status_code, 302)
            self.assertNotIn("evil.com", reply.headers["Location"])

    def test_pin_policy_rejects_guessable_pins(self):
        import safety
        for weak in ("123456", "654321", "111111", "000000", "123123", "121212", "12345678", "87654321", "98765432", "456789", "11223344"):
            self.assertTrue(safety.pin_is_weak(weak), weak)
        for strong in ("482915", "135790", "907316", "20481357"):
            self.assertFalse(safety.pin_is_weak(strong), strong)
        for bad, expected in (("12345", "6–8 cifre"), ("123456789", "6–8 cifre"), ("abc123x", "6–8 cifre"), ("123456", "ușor de ghicit"), ("777777", "ușor de ghicit")):
            token = self.csrf("/admin/users")
            reply = self.client.post("/admin/users", data={"csrf_token": token, "username": "pinx", "display_name": "Pin X", "pin": bad, "role": "reception"}, follow_redirects=True)
            self.assertIn(expected, reply.get_data(as_text=True), bad)
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE username='pinx'").fetchone()[0], 0)
        conn.close()

    def test_sql_injection_probes_do_not_break_or_leak(self):
        self.insert_booking(1, self.day(5), self.day(6), "confirmed")
        conn = pms.connect()
        conn.execute("UPDATE bookings SET guest_name='Client Secret Unic'")
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("bookings", "users", "rooms", "audit_log")}
        conn.close()
        payloads = ["' OR '1'='1", "'; DROP TABLE bookings;--", "\" OR 1=1 --", "' UNION SELECT username, pin_hash, 1,2,3,4,5,6 FROM users--", "1; DELETE FROM users", "%27%20OR%20%271%27%3D%271"]
        urls = ["/?q={p}", "/?start={p}", "/admin/timesheet?date={p}", "/admin/reports?start={p}&end={p}", "/deep-clean/reports?week={p}", "/report/yesterday?date={p}",
                "/api/available-rooms?start={p}&end={p}", "/api/availability?start={p}&end={p}", "/booking/new?room_id={p}&check_in={p}"]
        for payload in payloads:
            for template in urls:
                reply = self.client.get(template.format(p=urllib.parse.quote(payload)))
                self.assertLess(reply.status_code, 500, f"{template} cu {payload!r}")
                body = reply.get_data(as_text=True)
                self.assertNotIn("pbkdf2", body); self.assertNotIn("scrypt:", body)
        conn = pms.connect()
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("bookings", "users", "rooms", "audit_log")}
        conn.close()
        self.assertEqual({k: v for k, v in after.items() if k != "audit_log"}, {k: v for k, v in before.items() if k != "audit_log"})
        anon = pms.app.test_client()
        token = re.search(r'name="csrf_token" value="([^"]+)"', anon.get("/login").get_data(as_text=True)).group(1)
        reply = anon.post("/login", data={"csrf_token": token, "username": "admin' --", "pin": "x' OR '1'='1"}, follow_redirects=True)
        self.assertIn("incorect", reply.get_data(as_text=True))
        self.assertEqual(anon.get("/admin/users").status_code, 302)

    def test_stored_xss_payloads_are_escaped_on_every_page(self):
        payloads = ['<img src=x onerror=alert(1)>', '"><script>alert(2)</script>', "'-alert(3)-'", "<svg/onload=alert(4)>"]
        for i, payload in enumerate(payloads):
            self.insert_booking(i + 1, self.day(0), self.day(1), "confirmed")
        conn = pms.connect()
        for i, row in enumerate(conn.execute("SELECT id FROM bookings ORDER BY id").fetchall()):
            conn.execute("UPDATE bookings SET guest_name=?, notes=?, night_note=?, late_arrival=1, phone='0700000000' WHERE id=?", (payloads[i], payloads[i], payloads[i], row["id"]))
        conn.execute("UPDATE rooms SET maintenance_note=? WHERE id=9", (payloads[0],))
        conn.execute("UPDATE rooms SET out_of_order=1 WHERE id=9")
        conn.execute("INSERT INTO housekeeping_requests(room_id, service_date, request_type, note, status, requested_by_name) VALUES (6, ?, 'cleaning', ?, 'open', ?)", (self.day(0), payloads[1], payloads[2]))
        conn.execute("UPDATE users SET display_name=? WHERE username='admin'", (payloads[3],))
        conn.execute("INSERT INTO deep_clean_reports(week_start, room_id, items, note, status, updated_by_name) VALUES (?, 7, '{}', ?, 'sent', ?)", (pms.deep_clean.week_start(pms.date.today()), payloads[0], payloads[1]))
        conn.close()
        night = self.setUpNight("22:00")
        pages = ["/", "/housekeeping", "/housekeeping/deep-clean", "/deep-clean/reports", "/admin/users", "/admin/rooms", "/admin/reports", "/admin/audit", "/admin/timesheet",
                 "/report/yesterday", "/night", "/booking/1/edit"]
        bodies = {path: self.client.get(path).get_data(as_text=True) for path in pages}
        bodies["night-user"] = night.get("/night").get_data(as_text=True)
        for path, body in bodies.items():
            for payload in payloads:
                self.assertNotIn(payload, body, f"payload neescapat în {path}")
            self.assertNotRegex(body, r"<img src=x|<svg/onload|<script>alert", path)
        self.assertTrue(any("&lt;img src=x" in b or "&lt;script&gt;alert" in b for b in bodies.values()))

    def test_http_method_tampering_and_sensitive_paths(self):
        for path in ("/logout", "/housekeeping/request", "/booking/1/cancel", "/admin/rooms/rate", "/night/room/1", "/booking/group/x/cancel"):
            self.assertEqual(self.client.get(path).status_code, 405, path)
        for path in ("/static/../app.py", "/static/%2e%2e/app.py", "/static/..%2fapp.py", "/static/..%5capp.py", "/app.py", "/motel.db", "/secret.key", "/.env",
                     "/tests/test_app.py", "/static/../motel.db", "/static/../secret.key", "/templates/base.html", "/logs/audit.log"):
            reply = self.client.get(path)
            self.assertEqual(reply.status_code, 404, path)
            self.assertNotIn("secret_key", reply.get_data(as_text=True))
        self.assertEqual(self.client.get("/static/").status_code, 404)

    def test_request_size_limit_and_error_pages_do_not_leak(self):
        token = self.csrf()
        self.assertEqual(self.client.post("/housekeeping/request", data={"csrf_token": token, "note": "a" * 300000}).status_code, 413)
        missing = self.client.get("/nu-exista-aceasta-pagina")
        body = missing.get_data(as_text=True)
        self.assertEqual(missing.status_code, 404)
        self.assertNotRegex(body, r"Traceback|Werkzeug|Flask|File \"")
        original = pms.app.view_functions["reports"]
        pms.app.view_functions["reports"] = lambda: (_ for _ in ()).throw(RuntimeError("detaliu-intern-secret"))
        try:
            reply = self.client.get("/admin/reports")
        finally:
            pms.app.view_functions["reports"] = original
        self.assertEqual(reply.status_code, 500)
        self.assertNotIn("detaliu-intern-secret", reply.get_data(as_text=True))
        self.assertNotIn("Traceback", reply.get_data(as_text=True))
        os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
        api = self.api("/api/v1/nu-exista")
        self.assertEqual(api.status_code, 404)
        self.assertEqual(api.get_json(), {"error": "Not Found"})

    def test_api_token_guessing_is_rate_limited(self):
        os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
        for _ in range(10):
            self.assertEqual(self.api("/api/v1/rooms", token="gresit" * 6).status_code, 401)
        self.assertEqual(self.api("/api/v1/rooms", token="gresit" * 6).status_code, 429)
        self.assertEqual(self.api("/api/v1/rooms").status_code, 429)                 # blocat chiar și cu tokenul corect, temporar

    def test_exports_neutralize_spreadsheet_formulas(self):
        import io, openpyxl
        self.insert_booking(1, self.day(-1), self.day(1), "confirmed")
        conn = pms.connect()
        conn.execute("UPDATE bookings SET guest_name='=HYPERLINK(\"http://evil.test\",\"x\")', phone='+40 700', source='@SUM(1)'")
        conn.execute("INSERT INTO staff_sessions(user_id, user_name, day, login_at, last_seen_at) VALUES (9, '=1+1', ?, ?, ?)", (self.day(0), f"{self.day(0)} 08:00:00", f"{self.day(0)} 09:00:00"))
        conn.close()
        with pms.app.test_request_context():
            csv_url = pms.url_for("reports_export_csv", start=self.day(-3), end=self.day(3))
            xlsx_url = pms.url_for("reports_export", start=self.day(-3), end=self.day(3))
        csv_body = self.client.get(csv_url).get_data(as_text=True)
        self.assertIn("'=HYPERLINK", csv_body)
        self.assertNotRegex(csv_body, r"(^|[;,\n])=HYPERLINK")
        workbook = openpyxl.load_workbook(io.BytesIO(self.client.get(xlsx_url).data))
        values = [str(c.value) for ws in workbook for row in ws.iter_rows() for c in row if c.value is not None]
        self.assertTrue(any(v.startswith("'=HYPERLINK") for v in values))
        self.assertFalse(any(v.startswith("=HYPERLINK") or v.startswith("@SUM") for v in values))
        sheet_csv = self.client.get(f"/admin/timesheet.csv?year={self.day(0)[:4]}&month={int(self.day(0)[5:7])}").get_data(as_text=True)
        self.assertIn("'=1+1", sheet_csv)

    def test_input_validation_limits(self):
        def attempt(**over):
            data = {"csrf_token": self.csrf(), "guest_name": "Client Valid", "phone": "0712345678", "email": "", "room_id": "1", "check_in": "2026-11-01", "check_out": "2026-11-03",
                    "guests": "2", "rate": "200", "deposit": "0", "source": "Direct", "status": "confirmed", "notes": ""}
            data.update(over)
            self.client.post("/booking/new", data=data, follow_redirects=True)
            return self.booking_count()
        for bad in ({"guest_name": "N" * 121}, {"phone": "abc-telefon"}, {"phone": "<script>"}, {"email": "nu-este-email"}, {"rate": "nan"}, {"rate": "inf"}, {"rate": "1e9"}, {"rate": "10001"},
                    {"rate": "-5"}, {"deposit": "nan"}, {"deposit": "100001"}, {"deposit": "-1"}, {"check_out": "2027-03-03"}, {"source": "Sursa-inventata"}, {"notes": "n" * 1001}, {"status": "cancelled"}):
            self.assertEqual(attempt(**bad), 0, f"{bad} nu trebuia acceptat")
        self.assertEqual(attempt(email="client@example.com", phone="+40 712 345 678"), 1)
        token = self.csrf("/admin/users")
        self.client.post("/admin/users", data={"csrf_token": token, "username": "u" * 33, "display_name": "Prea Lung", "pin": "482915", "role": "reception"}, follow_redirects=True)
        self.client.post("/admin/users", data={"csrf_token": token, "username": "okuser", "display_name": "N" * 61, "pin": "482915", "role": "reception"}, follow_redirects=True)
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE username IN ('okuser', ?)", ("u" * 33,)).fetchone()[0], 0)
        conn.close()

    def test_database_file_is_private(self):
        if os.name != "posix":
            self.skipTest("permisiunile de fișier se verifică doar pe POSIX")
        self.assertEqual(os.stat(pms.DB_PATH).st_mode & 0o077, 0)


    def test_setup_is_closed_once_an_account_exists(self):
        anon = pms.app.test_client()
        page = anon.get("/setup")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/login", page.headers["Location"])
        token = re.search(r'name="csrf_token" value="([^"]+)"', anon.get("/login").get_data(as_text=True)).group(1)
        before = pms.connect().execute("SELECT COUNT(*) FROM users").fetchone()[0]
        reply = anon.post("/setup", data={"csrf_token": token, "username": "intrus", "display_name": "Intrus", "pin": "482915", "pin2": "482915"})
        self.assertIn(reply.status_code, (302, 400, 403))
        self.assertEqual(pms.connect().execute("SELECT COUNT(*) FROM users").fetchone()[0], before)
        self.assertEqual(pms.connect().execute("SELECT COUNT(*) FROM users WHERE username='intrus'").fetchone()[0], 0)


    # ======== V17 ========
    def fresh_admin(self):
        client = pms.app.test_client()
        tok = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
        client.post("/login", data={"csrf_token": tok, "username": "admin", "pin": "123456"})
        return client

    def set_modules(self, **values):
        conn = pms.connect()
        for key, value in values.items():
            conn.execute("INSERT INTO app_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value if isinstance(value, str) else ("1" if value else "0")))
        conn.close()
        pms.settings.invalidate()

    # --- setări: pagină, salvare, audit, validare
    def test_settings_page_saves_modules_and_times_with_audit(self):
        page = self.client.get("/admin/settings").get_data(as_text=True)
        for key, *_ in pms.settings.MODULES:
            self.assertIn(f'name="{key}"', page)
        token = self.csrf("/admin/settings")
        form = {"csrf_token": token, **{k: "1" for k, *_ in pms.settings.MODULES}, "reconfirm_time": "19:45", "reception_close": "21:00",
                "night_start": "21:00", "night_end": "06:00", "backup_time": "03:00", "backup_keep_days": "30"}
        form.pop("mod_room_board")
        self.client.post("/admin/settings", data=form, follow_redirects=True)
        self.assertFalse(pms.settings.enabled("mod_room_board"))
        self.assertEqual(pms.settings.time_text("reconfirm_time"), "19:45")
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='settings_update'").fetchone()[0], 1)
        conn.close()
        bad = self.client.post("/admin/settings", data={**form, "csrf_token": self.csrf("/admin/settings"), "night_end": "25:99"}, follow_redirects=True)
        self.assertIn("HH:MM", bad.get_data(as_text=True))
        self.assertEqual(pms.settings.time_text("night_end"), "06:00")
        recep, _ = self.make_user("rec_set", "482915", "reception")
        self.assertEqual(recep.get("/admin/settings").status_code, 403)

    def test_dashboard_modules_hide_their_sections(self):
        home = self.client.get("/").get_data(as_text=True)
        for text in ("Reconfirmări · procedura", "Starea camerelor acum", "COMUNICARE CU CAMERISTELE", "Rezervări viitoare și căutare rapidă", 'id="pmsNotify"'):
            self.assertIn(text, home)
        self.set_modules(mod_reconfirm=False, mod_room_board=False, mod_housekeeping_comm=False, mod_upcoming=False, mod_alerts=False)
        home = self.client.get("/").get_data(as_text=True)
        for text in ("Reconfirmări · procedura", "Starea camerelor acum", "COMUNICARE CU CAMERISTELE", "Rezervări viitoare și căutare rapidă", 'id="pmsNotify"', "housekeepingRequestDialog"):
            self.assertNotIn(text, home)
        self.assertIn("Disponibilitate", home)                                   # calendarul rămâne

    def test_disabled_modules_stop_working_not_only_hide(self):
        self.set_modules(mod_housekeeping_comm=False, mod_alerts=False, mod_deep_clean=False, mod_night_pending=False, mod_timesheet=False, mod_reconfirm=False)
        token = self.csrf()
        self.assertEqual(self.client.post("/housekeeping/request", data={"csrf_token": token, "room_id": "3", "services": ["cleaning"]}).status_code, 404)
        self.assertEqual(self.client.get("/api/notifications").status_code, 404)
        self.assertEqual(self.client.get("/housekeeping/deep-clean").status_code, 404)
        self.assertEqual(self.client.get("/deep-clean/reports").status_code, 404)
        self.assertEqual(self.client.get("/admin/timesheet").status_code, 404)
        self.assertEqual(self.client.post("/booking/1/reconfirm", data={"csrf_token": token}).status_code, 404)
        maid, _ = self.make_user("maid_off", "482915", "housekeeping")
        maid.get("/housekeeping"); maid.get("/housekeeping")
        conn = pms.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM staff_sessions").fetchone()[0], 0)    # pontaj oprit: nu se înregistrează
        conn.close()

    def test_reconfirm_time_is_configurable_and_module_switch_stops_it(self):
        from datetime import datetime as dt
        def direct_today():
            conn = pms.connect()
            conn.execute("DELETE FROM bookings")
            conn.execute("INSERT INTO bookings(guest_name, room_id, check_in, check_out, guests, rate, source, status) VALUES ('Direct Azi', 1, ?, ?, 2, 200, 'Direct', 'confirmed')", (self.day(0), self.day(1)))
            conn.close()
        def status():
            conn = pms.connect(); s = conn.execute("SELECT status FROM bookings").fetchone()[0]; conn.close(); return s
        self.set_modules(reconfirm_time="19:00")
        direct_today()
        self.assertEqual(pms.apply_direct_booking_cutoff(dt.combine(pms.date.today(), dt.strptime("18:59", "%H:%M").time()).astimezone()), 0)
        self.assertEqual(status(), "confirmed")
        self.assertEqual(pms.apply_direct_booking_cutoff(dt.combine(pms.date.today(), dt.strptime("19:01", "%H:%M").time()).astimezone()), 1)
        self.assertEqual(status(), "unconfirmed")
        direct_today()
        self.set_modules(mod_reconfirm=False)
        self.assertEqual(pms.apply_direct_booking_cutoff(dt.combine(pms.date.today(), dt.strptime("22:00", "%H:%M").time()).astimezone()), 0)
        self.assertEqual(status(), "confirmed")
        self.assertIn("procedura 19:00", (self.set_modules(mod_reconfirm=True), self.client.get("/").get_data(as_text=True))[1])

    def test_late_confirm_module_switch(self):
        self.at("21:30")
        self.insert_booking(14, self.day(0), self.day(1), "unconfirmed")
        self.set_modules(mod_late_confirm=False)
        self.assertEqual(pms.apply_late_arrival_confirmation(), 0)
        self.set_modules(mod_late_confirm=True)
        self.assertEqual(pms.apply_late_arrival_confirmation(), 1)

    def test_night_module_and_time_restriction_switches(self):
        night_user = self.setUpNight("14:00")
        self.night_post(night_user, "/night/room/16", mode="occupy", guest_name="Zi Restrictie", guests="1", payment="cash")
        self.assertEqual(self.booking_count(), 0)                                  # restricție activă
        self.set_modules(night_time_restriction=False)
        self.assertNotIn("Acum puteți doar vizualiza", night_user.get("/night").get_data(as_text=True))
        self.night_post(night_user, "/night/room/16", mode="occupy", guest_name="Zi Fara Restrictie", guests="1", payment="cash")
        self.assertEqual(self.booking_count(), 1)                                  # restricția oprită de administrator
        self.set_modules(night_start="13:00", night_time_restriction=True)
        self.assertNotIn("Acum puteți doar vizualiza", night_user.get("/night").get_data(as_text=True))   # programul setat din panou
        self.set_modules(mod_night_desk=False)
        off = night_user.get("/night")
        self.assertEqual(off.status_code, 403)
        self.assertIn("dezactivat de administrator", off.get_data(as_text=True))
        self.assertEqual(night_user.post("/night/room/17", data={"csrf_token": "x"}).status_code, 400)
        token = self.csrf()
        self.assertEqual(self.client.post("/night/room/17", data={"csrf_token": token, "mode": "occupy", "guest_name": "Admin", "guests": "1", "payment": "cash"}).status_code, 404)

    def test_shift_report_and_night_pending_switches(self):
        lead, _ = self.make_user("lead_off", "482915", "shift_lead")
        self.set_modules(mod_shift_report=False, mod_night_pending=False)
        reply = lead.get("/report/yesterday")
        self.assertEqual(reply.status_code, 403)
        self.assertIn("dezactivat de administrator", reply.get_data(as_text=True))
        self.assertEqual(self.client.post("/booking/1/night-payment-collected", data={"csrf_token": self.csrf()}).status_code, 404)

    # --- recepția de noapte: cazarea apare a doua zi în calendar și la șeful de tură
    def test_night_checkin_shows_next_day_in_calendar_and_shift_report(self):
        night_user = self.setUpNight("23:10", rate=180)
        reply = self.night_post(night_user, "/night/room/12", mode="occupy", guest_name="Oaspete Noaptea", guests="2", payment="cash")
        self.assertIn("a fost cazată", reply.get_data(as_text=True))
        self.assertIn("nd-occupied", night_user.get("/night").get_data(as_text=True))
        from datetime import datetime as dt, timedelta as td
        tomorrow = pms.date.today() + td(days=1)
        pms.room_state.now_fn = lambda: dt.combine(tomorrow, dt.strptime("08:00", "%H:%M").time())
        pms.clock.configure(f"{tomorrow.isoformat()} 08:00")
        try:
            self.assertIn("/login", self.client.get("/").headers.get("Location", ""))   # schimbarea datei încheie sesiunile
            calendar = self.fresh_admin().get(f"/?start={self.day(-1)}").get_data(as_text=True)
            self.assertIn("Oaspete Noaptea", calendar)
            lead, _ = self.make_user("lead_next", "482915", "shift_lead")
            report = lead.get("/report/yesterday").get_data(as_text=True)
        finally:
            pms.clock.configure("")
        conn = pms.connect()
        name = conn.execute("SELECT name FROM rooms WHERE id=12").fetchone()[0]
        conn.close()
        self.assertIn(f'<span class="yr-room">{name}</span>', report)
        self.assertIn("Încasat cash: <b>180,00 lei</b>", report)
        self.assertIn("Cazări la recepția de noapte: <b>1</b>", report)

    def test_fresh_and_upgraded_databases_get_default_night_rates_once(self):
        import tempfile as tf, sqlite3 as sq
        previous = pms.DB_PATH
        with tf.TemporaryDirectory() as folder:
            pms.DB_PATH = os.path.join(folder, "fresh.db")
            try:
                pms.init_db()
                conn = pms.connect()
                rates = {r["building"]: r["rate"] for r in conn.execute("SELECT building, MIN(default_rate) AS rate FROM rooms GROUP BY building").fetchall()}
                conn.execute("UPDATE rooms SET default_rate=0 WHERE name='101'")       # setare intenționată a administratorului
                conn.close()
                pms.init_db()                                                           # la o nouă pornire NU se suprascrie
                conn = pms.connect()
                kept = conn.execute("SELECT default_rate FROM rooms WHERE name='101'").fetchone()[0]
                conn.close()
            finally:
                pms.DB_PATH = previous
        self.assertEqual(rates, {"Corp A": 150.0, "Corp B": 180.0, "Corp C": 180.0})
        self.assertEqual(kept, 0)

    # --- calendar
    def test_calendar_has_previous_next_today_and_swipe(self):
        html = self.client.get("/?start=2026-11-10&days=7").get_data(as_text=True)
        self.assertIn('data-cal-prev href="/?start=2026-11-03&amp;days=7"', html)
        self.assertIn('data-cal-next href="/?start=2026-11-17&amp;days=7"', html)
        self.assertIn(">Azi</a>", html)
        js = self.client.get("/static/ui.js").get_data(as_text=True)
        self.assertIn("touchend", js)
        self.assertIn("data-cal-next", js)

    # --- editare utilizatori
    def edit_user_post(self, user_id, **fields):
        token = self.csrf(f"/admin/users/{user_id}/edit")
        return self.client.post(f"/admin/users/{user_id}/edit", data={"csrf_token": token, **fields}, follow_redirects=True)

    def user_row(self, username):
        conn = pms.connect(); row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone(); conn.close(); return row

    def test_admin_edits_user_and_changes_invalidate_sessions(self):
        client, _ = self.make_user("edit1", "482915", "reception", name="Nume Vechi")
        uid = self.user_row("edit1")["id"]
        self.assertIn("Editează", self.client.get("/admin/users").get_data(as_text=True))
        self.edit_user_post(uid, username="edit1", display_name="Nume Nou", role="reception", active="1")
        self.assertEqual(self.user_row("edit1")["display_name"], "Nume Nou")
        self.assertEqual(client.get("/").status_code, 200)                            # doar numele: rămâne conectat
        self.edit_user_post(uid, username="edit1", display_name="Nume Nou", role="night_reception", active="1")
        row = self.user_row("edit1")
        self.assertEqual((row["role"], row["staff_type"]), ("reception", "night_reception"))
        self.assertIn("/login", client.get("/").headers.get("Location", ""))          # rol schimbat: deconectat peste tot
        client2 = pms.app.test_client()
        tok = re.search(r'name="csrf_token" value="([^"]+)"', client2.get("/login").get_data(as_text=True)).group(1)
        client2.post("/login", data={"csrf_token": tok, "username": "edit1", "pin": "482915"})
        self.edit_user_post(uid, username="edit1", display_name="Nume Nou", role="night_reception", active="1", pin="907316")
        self.assertIn("/login", client2.get("/night").headers.get("Location", ""))     # PIN schimbat: deconectat
        self.assertTrue(pms.check_password_hash(self.user_row("edit1")["pin_hash"], "907316"))
        reply = self.edit_user_post(uid, username="edit1", display_name="Nume Nou", role="night_reception", active="1", pin="123456")
        self.assertIn("ușor de ghicit", reply.get_data(as_text=True))
        self.make_user("edit2", "482915", "reception")
        reply = self.edit_user_post(uid, username="edit2", display_name="X", role="reception", active="1")
        self.assertIn("există deja", reply.get_data(as_text=True))
        self.edit_user_post(uid, username="edit1", display_name="Nume Nou", role="reception", active="1", logout_all="1")
        self.assertEqual(self.user_row("edit1")["session_epoch"], 3)

    def test_admin_cannot_lock_out_the_last_admin_or_demote_self(self):
        me = self.user_row("admin")["id"]
        reply = self.edit_user_post(me, username="admin", display_name="Admin", role="reception", active="1")
        self.assertIn("Nu vă puteți retrage", reply.get_data(as_text=True))
        reply = self.edit_user_post(me, username="admin", display_name="Admin", role="admin")      # fără „activ”
        self.assertIn("Nu vă puteți retrage", reply.get_data(as_text=True))
        self.assertEqual((self.user_row("admin")["role"], self.user_row("admin")["active"]), ("admin", 1))
        self.edit_user_post(me, username="admin", display_name="Admin Redenumit", role="admin", active="1", pin="907316")
        self.assertEqual(self.client.get("/admin/users").status_code, 200)            # propriul PIN schimbat: rămâne conectat
        self.edit_user_post(me, username="admin", display_name="Admin", role="admin", active="1", pin="123456")
        self.assertTrue(pms.check_password_hash(self.user_row("admin")["pin_hash"], "907316"))
        conn = pms.connect()
        conn.execute("UPDATE users SET pin_hash=? WHERE username='admin'", (pms.generate_password_hash("123456"),))
        conn.close()

    # --- autentificare în 2 pași
    def login_steps(self, username="admin", pin="123456", code=None):
        client = pms.app.test_client()
        tok = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
        first = client.post("/login", data={"csrf_token": tok, "username": username, "pin": pin})
        return client, first

    def post_code(self, client, path, code):
        tok = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).get_data(as_text=True)).group(1)
        return client.post(path, data={"csrf_token": tok, "code": code})

    def test_totp_matches_rfc6238_vectors(self):
        import base64, totp
        secret = base64.b32encode(b"12345678901234567890").decode()
        for unix, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
            self.assertEqual(totp.code_at(secret, unix // 30), code)
        self.assertEqual(totp.verify(secret, "287082", 59), 1)
        self.assertIsNone(totp.verify(secret, "287082", 59, last_step=1))             # același cod nu se poate refolosi
        self.assertIsNone(totp.verify(secret, "12345", 59))

    def test_admin_two_step_enrollment_login_replay_and_recovery(self):
        import time as tm, totp
        self.set_modules(admin_2fa_required=True)
        client, first = self.login_steps()
        self.assertIn("/login/2fa/setup", first.headers["Location"])
        self.assertIn("/login", client.get("/").headers["Location"])                # PIN corect, dar încă neautentificat
        page = client.get("/login/2fa/setup").get_data(as_text=True)
        self.assertIn("otpauth://totp/", page)
        with client.session_transaction() as sess:
            secret = sess["totp_setup"]
        bad = self.post_code(client, "/login/2fa/setup", "000000")
        self.assertEqual(bad.status_code, 200)
        good = self.post_code(client, "/login/2fa/setup", totp.code_at(secret, int(tm.time() // 30)))
        self.assertIn("/account/recovery-codes", good.headers["Location"])
        codes_page = client.get("/account/recovery-codes").get_data(as_text=True)
        codes = re.findall(r"<code>(\d{4}-\d{4})</code>", codes_page)
        self.assertEqual(len(codes), 8)
        self.assertEqual(client.get("/account/recovery-codes").status_code, 302)       # afișate o singură dată
        self.assertEqual(client.get("/admin/users").status_code, 200)
        row = self.user_row("admin")
        self.assertEqual((row["totp_enabled"], row["totp_secret"]), (1, secret))
        self.assertNotIn(codes[0], row["totp_recovery"])                               # coduri de rezervă doar ca hash
        # autentificare nouă: cod obligatoriu; codul deja folosit nu mai merge (fereastra de 30 s)
        client2, first2 = self.login_steps()
        self.assertIn("/login/2fa", first2.headers["Location"])
        reused = self.post_code(client2, "/login/2fa", totp.code_at(secret, int(tm.time() // 30)))
        self.assertEqual(reused.status_code, 200)
        conn = pms.connect(); conn.execute("UPDATE users SET totp_last_step=0 WHERE username='admin'"); conn.close()
        ok = self.post_code(client2, "/login/2fa", totp.code_at(secret, int(tm.time() // 30)))
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(client2.get("/admin/users").status_code, 200)
        # cod de rezervă: o singură dată
        client3, _ = self.login_steps()
        self.assertEqual(self.post_code(client3, "/login/2fa", codes[0]).status_code, 302)
        client4, _ = self.login_steps()
        self.assertEqual(self.post_code(client4, "/login/2fa", codes[0]).status_code, 200)
        # utilizatorii care nu sunt administratori nu sunt întrebați
        recep_client, recep_first = self.make_user("rec_2fa", "482915", "reception")
        self.assertEqual(recep_first.request.path, "/")
        conn = pms.connect(); conn.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE username='admin'"); conn.close()

    def test_two_step_lockout_expiry_and_admin_reset(self):
        import time as tm, totp
        secret = totp.new_secret()
        conn = pms.connect(); conn.execute("UPDATE users SET totp_enabled=1, totp_secret=? WHERE username='admin'", (secret,)); conn.close()
        client, first = self.login_steps()
        for _ in range(5):
            self.post_code(client, "/login/2fa", "111111")
        locked = self.post_code(client, "/login/2fa", totp.code_at(secret, int(tm.time() // 30)))
        self.assertIn("Prea multe coduri greșite", locked.get_data(as_text=True))
        conn = pms.connect(); conn.execute("DELETE FROM auth_attempts"); conn.close()
        client2, _ = self.login_steps()
        with client2.session_transaction() as sess:
            sess["pending_at"] = tm.time() - 301                                       # pasul 2 expiră după 5 minute
        expired = client2.get("/login/2fa")
        self.assertEqual(expired.status_code, 302)
        self.assertTrue(expired.headers["Location"].endswith("/login"))
        with client2.session_transaction() as sess:
            self.assertNotIn("pending_user", sess)                                      # starea intermediară a fost ștearsă
        self.assertEqual(client2.get("/admin/users").status_code, 302)
        other, _ = self.make_user("admin_b", "482915", "reception", role="admin")
        uid = self.user_row("admin")["id"]
        edit_page = other.get(f"/admin/users/{uid}/edit")
        self.assertEqual(edit_page.status_code, 200, edit_page.headers.get("Location"))
        token = re.search(r'name="csrf_token" value="([^"]+)"', edit_page.get_data(as_text=True)).group(1)
        other.post(f"/admin/users/{uid}/edit", data={"csrf_token": token, "username": "admin", "display_name": "Admin", "role": "admin", "active": "1", "reset_2fa": "1"})
        self.assertEqual(self.user_row("admin")["totp_enabled"], 0)
        self.set_modules(admin_2fa_required=True)
        _, again = self.login_steps()
        self.assertIn("/login/2fa/setup", again.headers["Location"])                 # resetat: configurare din nou

    def test_two_step_pages_without_pending_login_redirect(self):
        anon = pms.app.test_client()
        self.assertIn("/login", anon.get("/login/2fa").headers["Location"])
        self.assertIn("/login", anon.get("/login/2fa/setup").headers["Location"])
        self.assertEqual(anon.post("/login/2fa", data={"code": "123456"}).status_code, 400)          # fără CSRF
        self.assertEqual(anon.get("/account/recovery-codes").status_code, 302)

    def test_manage_cli_resets_two_step(self):
        import subprocess, sys as _sys
        conn = pms.connect(); conn.execute("UPDATE users SET totp_enabled=1, totp_secret='ABC' WHERE username='admin'"); conn.close()
        out = subprocess.run([_sys.executable, "manage.py", "reset-2fa", "admin"], capture_output=True, text=True, env=os.environ.copy(), cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("resetată", out.stdout)
        self.assertEqual(self.user_row("admin")["totp_enabled"], 0)

    # --- copii de siguranță
    def test_backups_run_verify_rotate_and_schedule(self):
        import tempfile as tf, backup
        from datetime import datetime as dt, timedelta as td, time as tt
        with tf.TemporaryDirectory() as folder:
            old = os.path.join(folder, "motel_2020-01-01_0300.db")
            open(old, "w").close()
            other = os.path.join(folder, "nu-se-sterge.txt")
            open(other, "w").close()
            now = dt(2026, 10, 26, 3, 5)
            result = backup.run(pms.DB_PATH, folder, 30, now)
            self.assertTrue(os.path.exists(result["path"]))
            self.assertFalse(os.path.exists(old))                                     # rotație: doar copiile automate vechi
            self.assertTrue(os.path.exists(other))
            import sqlite3 as sq
            self.assertEqual(sq.connect(result["path"]).execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertFalse(backup.needed(folder, now + td(hours=2), tt(3, 0)))       # azi există deja
            self.assertFalse(backup.needed(folder, dt(2026, 10, 27, 2, 59), tt(3, 0)))  # mâine, înainte de oră
            self.assertTrue(backup.needed(folder, dt(2026, 10, 27, 3, 1), tt(3, 0)))
            self.assertTrue(backup.needed(folder, dt(2026, 10, 28, 9, 0), tt(23, 0)))   # PC oprit la ora setată: după 26 h
        os.environ["MOTEL_BACKUP_DIR"] = tf.mkdtemp()
        try:
            self.assertIsNotNone(pms.maybe_auto_backup(dt(2026, 10, 26, 3, 30)))
            self.assertIsNone(pms.maybe_auto_backup(dt(2026, 10, 26, 4, 0)))
            page = self.client.get("/admin/backups").get_data(as_text=True)
            self.assertIn("motel_2026-10-26_0330.db", page)
            reply = self.client.post("/admin/backups", data={"csrf_token": self.csrf("/admin/backups")}, follow_redirects=True)
            self.assertIn("Copie salvată și verificată", reply.get_data(as_text=True))
            conn = pms.connect()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_log WHERE action IN ('backup_auto','backup_manual')").fetchone()[0], 2)
            conn.close()
            self.assertEqual(self.client.get("/backups/auto/motel_2026-10-26_0330.db").status_code, 404)   # copiile nu se servesc prin web
        finally:
            os.environ.pop("MOTEL_BACKUP_DIR", None)

    # --- ceas de test
    def test_test_clock_moves_time_and_shows_banner(self):
        pms.clock.configure("2026-12-24 21:30")
        try:
            self.assertEqual(pms.clock.now().strftime("%Y-%m-%d %H"), "2026-12-24 21")
            page = self.fresh_admin().get("/").get_data(as_text=True)
            self.assertIn("CEAS DE TEST · 24.12.2026 21:3", page)
            os.environ["MOTEL_API_TOKEN"] = self.API_TOKEN
            self.assertTrue(self.api("/api/v1/health").get_json()["test_clock"])
        finally:
            pms.clock.configure("")
        self.assertNotIn("CEAS DE TEST", self.fresh_admin().get("/").get_data(as_text=True))
        with self.assertRaises(SystemExit):
            pms.clock.configure("24.12.2026")

    # --- server de producție (cu un înlocuitor al pachetului cheroot: verifică integrarea, nu cheroot însuși)
    def test_production_server_integration_with_stub(self):
        import subprocess, sys as _sys, tempfile as tf
        stub = tf.mkdtemp()
        os.makedirs(os.path.join(stub, "cheroot", "ssl"))
        open(os.path.join(stub, "cheroot", "__init__.py"), "w").close()
        open(os.path.join(stub, "cheroot", "ssl", "__init__.py"), "w").close()
        with open(os.path.join(stub, "cheroot", "wsgi.py"), "w") as handle:
            handle.write("import json, os\nclass Server:\n    def __init__(self, bind, app, numthreads=10, server_name=None):\n        self.info = {'bind': list(bind), 'threads': numthreads, 'name': server_name}\n        self.app = app\n        self.ssl_adapter = None\n    def start(self):\n        status = []\n        body = b''.join(self.app({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/login', 'SERVER_NAME': 'x', 'SERVER_PORT': '1', 'wsgi.url_scheme': 'http', 'wsgi.input': __import__('io').BytesIO(), 'wsgi.errors': __import__('sys').stderr, 'SERVER_PROTOCOL': 'HTTP/1.1'}, lambda s, h, *a: status.append(s)))\n        self.info.update(version=self.version, ssl=type(self.ssl_adapter).__name__ if self.ssl_adapter else None, status=status[0], has_login=b'PIN' in body)\n        print('STUB', json.dumps(self.info))\n    def stop(self):\n        pass\n")
        with open(os.path.join(stub, "cheroot", "ssl", "builtin.py"), "w") as handle:
            handle.write("class BuiltinSSLAdapter:\n    def __init__(self, cert, key):\n        self.cert, self.key = cert, key\n")
        env = {**os.environ, "PYTHONPATH": stub, "MOTEL_HOST": "0.0.0.0", "MOTEL_PORT": "5099", "MOTEL_SSL_CERT": "c.pem", "MOTEL_SSL_KEY": "k.pem"}
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([_sys.executable, "app.py"], capture_output=True, text=True, env=env, cwd=root, timeout=60)
        self.assertIn("serverul de producție: https://0.0.0.0:5099", out.stdout)
        info = json.loads(out.stdout.split("STUB ", 1)[1].splitlines()[0])
        self.assertEqual((info["bind"], info["version"], info["ssl"], info["status"][:3], info["has_login"]), (["0.0.0.0", 5099], "PMS", "BuiltinSSLAdapter", "200", True))


if __name__ == "__main__":
    unittest.main()
