"""Basic regression tests for FairShift's demo workflows.

Run with: python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

from app import create_app, seed_demo, pay_summary


class FairShiftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.tmp.name, "test.db")
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "DATABASE_URL": "sqlite:///" + db_path,
            "SESSION_COOKIE_SECURE": False,
        })
        seed_demo(self.app)
        self.client = self.app.test_client()
        self.client.get("/")  # creates the anonymous session CSRF token
        self.csrf = self._csrf_from_session()

    def tearDown(self):
        self.tmp.cleanup()

    def _csrf_from_session(self):
        with self.client.session_transaction() as session:
            return session["csrf"]

    def login(self, username="worker.site", password="FairShift-demo-2026!"):
        response = self.client.post("/", data={
            "username": username,
            "password": password,
            "csrf": self.csrf,
        }, follow_redirects=True)
        self.csrf = self._csrf_from_session()  # login rotates the token
        return response

    def test_health_and_login_page(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertIn(b"FairShift", self.client.get("/").data)

    def test_demo_worker_can_sign_in_and_load_state(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        state = self.client.get("/api/state")
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json["user"]["name"], "Arun Kumar")
        self.assertIn("pay", state.json)

    def test_wrong_password_is_rejected(self):
        response = self.client.post("/", data={
            "username": "worker.site", "password": "wrong", "csrf": self.csrf
        })
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Incorrect username or password", response.data)

    def test_csrf_is_required(self):
        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 403)

    def test_worker_shift_check_in_and_check_out(self):
        self.login()
        headers = {"X-CSRF-Token": self.csrf}
        response = self.client.post("/api/shift", json={"action": "in"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        state = self.client.get("/api/state").json
        self.assertIsNotNone(state["active"])
        duplicate = self.client.post("/api/shift", json={"action": "in"}, headers=headers)
        self.assertEqual(duplicate.status_code, 409)
        out = self.client.post("/api/shift", json={"action": "out"}, headers=headers)
        self.assertEqual(out.status_code, 200)
        self.assertIsNone(self.client.get("/api/state").json["active"])

    def test_report_returns_private_receipt_and_can_be_tracked(self):
        self.login()
        headers = {"X-CSRF-Token": self.csrf}
        created = self.client.post("/api/reports", json={
            "kind": "feedback", "severity": "low", "message": "Please improve drinking water access."
        }, headers=headers)
        self.assertEqual(created.status_code, 201)
        receipt = created.json["receipt"]
        tracked = self.client.get("/api/receipt/" + receipt)
        self.assertEqual(tracked.status_code, 200)
        self.assertEqual(tracked.json["status"], "Open")
        self.assertNotIn("message", tracked.json)

    def test_report_validation(self):
        self.login()
        response = self.client.post("/api/reports", json={
            "kind": "invalid", "severity": "high", "message": "bad"
        }, headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(response.status_code, 400)

    def test_worker_cannot_use_admin_endpoint(self):
        self.login()
        response = self.client.post("/api/reports/1/status", json={"status": "Resolved"},
                                    headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_report_status(self):
        self.login("admin.site")
        response = self.client.post("/api/reports/1/status", json={"status": "Resolved"},
                                    headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(response.status_code, 200)
        state = self.client.get("/api/state").json
        self.assertTrue(any(r["status"] == "Resolved" for r in state["reports"]))

    def test_pay_summary_applies_one_and_half_overtime_rate(self):
        shifts = [{"start": "2026-01-01T08:00:00+00:00", "end": "2026-01-01T18:00:00+00:00"}]
        result = pay_summary(shifts, 10000)  # ₹100/hour, represented in paise
        self.assertEqual(result["regular_minutes"], 480)
        self.assertEqual(result["overtime_minutes"], 120)
        self.assertEqual(result["base_paise"], 80000)
        self.assertEqual(result["overtime_paise"], 30000)
        self.assertEqual(result["total_paise"], 110000)


if __name__ == "__main__":
    unittest.main()
