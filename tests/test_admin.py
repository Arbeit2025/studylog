"""Admin authentication and server-enforced roles, using disposable databases."""
import secrets
import sqlite3
from unittest.mock import patch

from test_studylog import FormParser, StudylogFixture
from test_auth import PostForms


class AdminTest(StudylogFixture):
    # Fixtures only; never put a deployment's credentials here.
    PASSCODE = "R7t2Qa9z"

    def setUp(self):
        super().setUp()
        self.module.app.config["STUDYLOG_ADMIN_PASSCODE"] = self.PASSCODE

    def login_admin(self, client=None, code=None):
        client = client or self.client
        page = client.get("/admin/login")
        self.assertEqual(page.status_code, 200)
        data = FormParser(page.get_data(as_text=True)).fields
        data["passcode"] = self.PASSCODE if code is None else code
        return client.post("/admin/login", data=data)

    def reset_admin_attempts(self):
        with sqlite3.connect(self.root / "studylog.db") as conn:
            conn.execute("DELETE FROM studylog_admin_auth_attempts")

    def test_selector_and_separate_masked_alphanumeric_form(self):
        client = self.module.app.test_client()
        html = client.get("/login").get_data(as_text=True)
        self.assertIn('type="checkbox"', html)
        self.assertIn('data-admin-login-url="/admin/login"', html)
        self.assertIn('/static/login.js', html)
        page = client.get("/admin/login")
        html = page.get_data(as_text=True)
        for attr in ('type="password"', 'maxlength="8"', 'pattern="[A-Za-z0-9]{8}"',
                     'autocapitalize="none"', 'spellcheck="false"'):
            self.assertIn(attr, html)
        self.assertNotIn('inputmode="numeric"', html)
        self.assertNotIn(self.PASSCODE, html)
        self.assertNotIn(self.module.app.secret_key, html)
        self.assertIn("no-store", page.headers["Cache-Control"])
        self.assertEqual(client.get("/admin").status_code, 303)

    def test_direct_admin_login_grants_access_and_rotates_session(self):
        client = self.module.app.test_client()
        old_csrf = FormParser(client.get("/admin/login").get_data(as_text=True)).fields["csrf_token"]
        response = client.post("/admin/login", data={"passcode": self.PASSCODE, "csrf_token": old_csrf})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, "/admin")
        self.assertIn("管理者としてログイン中", client.get("/admin").get_data(as_text=True))
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/backup").status_code, 200)
        with client.session_transaction() as state:
            self.assertNotEqual(old_csrf, state["studylog_csrf"])
            self.assertNotIn(self.PASSCODE, str(dict(state)))
        self.assertEqual(client.post("/admin/logout", data={"csrf_token": old_csrf}).status_code, 400)

    def test_regular_login_and_forged_role_fields_cannot_grant_admin(self):
        client = self.module.app.test_client()
        data = FormParser(client.get("/login").get_data(as_text=True)).fields
        data.update(pin="4826", admin="1", role="admin", studylog_admin=True)
        self.assertEqual(client.post("/login", data=data).status_code, 303)
        for path in ("/admin", "/backup", "/backup?role=admin"):
            self.assertEqual(client.get(path).status_code, 403)
        self.assertIn("管理者ログインへ", client.get("/backup").get_data(as_text=True))
        self.assertNotIn('href="/backup"', client.get("/").get_data(as_text=True))
        token = FormParser(client.get("/").get_data(as_text=True)).fields["csrf_token"]
        self.assertEqual(client.post("/admin/logout", data={"csrf_token": token}).status_code, 403)

    def test_wrong_code_case_length_and_unicode_never_grant_admin(self):
        for code in (self.PASSCODE.lower(), self.PASSCODE.upper(), "4826", "", self.PASSCODE + "0",
                     self.PASSCODE[:-1], "R7t2Qa9!", "Ｒ7t2Qa9z", "あいうえおかきく", " " + self.PASSCODE):
            with self.subTest(code=code):
                client = self.module.app.test_client()
                response = self.login_admin(client, code)
                self.assertEqual(response.status_code, 401)
                if code:
                    self.assertNotIn(code, response.get_data(as_text=True))
                self.assertEqual(client.get("/admin").status_code, 303)
                self.reset_admin_attempts()

    def test_admin_form_requires_csrf_and_does_not_accept_normal_pin(self):
        client = self.module.app.test_client()
        client.get("/admin/login")
        for csrf in (None, "incorrect", "日本語"):
            data = {"passcode": self.PASSCODE}
            if csrf is not None:
                data["csrf_token"] = csrf
            self.assertEqual(client.post("/admin/login", data=data).status_code, 400)
        self.assertEqual(self.login_admin(client, "4826").status_code, 401)
        self.assertEqual(client.get("/backup").status_code, 303)

    def test_invalid_admin_configuration_keeps_regular_access(self):
        for value in ("", None, "short", "R7t2Qa9!", "Ａ7t2Qa9z", "R7t2Qa9zz"):
            with self.subTest(value=value):
                self.module.app.config["STUDYLOG_ADMIN_PASSCODE"] = value
                self.assertEqual(self.module.app.test_client().get("/admin/login").status_code, 503)
                self.assertEqual(self.client.get("/").status_code, 200)
                self.assertEqual(self.client.get("/backup").status_code, 403)

    def test_admin_login_does_not_bypass_missing_base_configuration(self):
        for key in ("STUDYLOG_PIN", "SECRET_KEY"):
            old = self.module.app.config[key]
            self.module.app.config[key] = ""
            self.assertEqual(self.module.app.test_client().get("/admin/login").status_code, 503)
            self.module.app.config[key] = old

    def test_attempt_limit_survives_new_browser_and_resets_after_wait(self):
        with patch.object(self.module.time, "time", return_value=1000):
            for _ in range(4):
                self.assertEqual(self.login_admin(self.module.app.test_client(), "wrong123").status_code, 401)
            blocked = self.login_admin(self.module.app.test_client(), "wrong123")
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.headers["Retry-After"], "30")
        with patch.object(self.module.time, "time", return_value=1010):
            self.assertEqual(self.login_admin(self.module.app.test_client()).status_code, 429)
        with patch.object(self.module.time, "time", return_value=1030):
            self.assertEqual(self.login_admin().status_code, 303)
            self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_regular_login_success_does_not_reset_admin_failures(self):
        with patch.object(self.module.time, "time", return_value=1000):
            for _ in range(4):
                self.assertEqual(self.login_admin(self.module.app.test_client(), "wrong123").status_code, 401)
            regular = self.module.app.test_client()
            data = FormParser(regular.get("/login").get_data(as_text=True)).fields
            self.assertEqual(regular.post("/login", data={**data, "pin": "4826"}).status_code, 303)
            self.assertEqual(self.login_admin(regular, "wrong123").status_code, 429)
            # Admin lockout has not locked the ordinary PIN.
            regular = self.module.app.test_client()
            data = FormParser(regular.get("/login").get_data(as_text=True)).fields
            self.assertEqual(regular.post("/login", data={**data, "pin": "4826"}).status_code, 303)

    def test_admin_lockout_persists_after_application_reload(self):
        import importlib.util
        with patch.object(self.module.time, "time", return_value=1000):
            for _ in range(5):
                self.login_admin(self.module.app.test_client(), "wrong123")
        key = self.module.app.secret_key
        spec = importlib.util.spec_from_file_location("admin_restart", self.root / "soapp.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.app.config.update(TESTING=True, SECRET_KEY=key, STUDYLOG_PIN="4826",
                                      STUDYLOG_ADMIN_PASSCODE=self.PASSCODE, SESSION_COOKIE_SECURE=False)
        with patch.object(self.module.time, "time", return_value=1010):
            blocked = self.login_admin(self.module.app.test_client())
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.headers["Retry-After"], "20")

    def test_regular_lockout_does_not_grant_or_lock_admin(self):
        with patch.object(self.module.time, "time", return_value=1000):
            for _ in range(5):
                client = self.module.app.test_client()
                data = FormParser(client.get("/login").get_data(as_text=True)).fields
                client.post("/login", data={**data, "pin": "1111"})
            self.assertEqual(self.login_admin().status_code, 303)
            self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_admin_expiry_and_passcode_rotation_remove_only_admin(self):
        with patch.object(self.module.time, "time", return_value=1000):
            self.login_admin()
        with patch.object(self.module.time, "time", return_value=44199):
            self.assertEqual(self.client.get("/admin").status_code, 200)
        with patch.object(self.module.time, "time", return_value=44200):
            self.assertEqual(self.client.get("/admin").status_code, 303)
        self.login_admin()
        self.module.app.config["STUDYLOG_ADMIN_PASSCODE"] = "F1x4Pq7a"
        self.assertEqual(self.client.get("/admin").status_code, 403)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.module.app.config["STUDYLOG_ADMIN_PASSCODE"] = self.PASSCODE
        self.assertEqual(self.client.get("/admin").status_code, 403)

    def test_pin_and_key_rotation_also_invalidate_admin(self):
        self.login_admin()
        self.module.app.config["STUDYLOG_PIN"] = "7912"
        self.assertEqual(self.client.get("/admin").status_code, 303)
        self.login_admin()
        self.module.app.secret_key = secrets.token_hex(32)
        self.assertEqual(self.client.get("/admin").status_code, 303)

    def test_downgrade_rotates_csrf_and_preserves_logs(self):
        self.client.post("/add", data=self.completed())
        original = self.rows()
        self.login_admin()
        token = FormParser(self.client.get("/admin").get_data(as_text=True)).fields["csrf_token"]
        self.assertEqual(self.client.post("/admin/logout", data={}).status_code, 400)
        self.assertEqual(self.client.post("/admin/logout", data={"csrf_token": token}).status_code, 303)
        self.assertEqual(self.client.get("/admin").status_code, 403)
        self.assertEqual(self.client.get("/backup").status_code, 403)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/delete/1", data={"csrf_token": token}).status_code, 400)
        self.assertEqual(self.rows(), original)
        self.assertEqual(self.client.get("/admin/logout").status_code, 405)

    def test_lock_removes_both_roles_and_repeated_admin_logins_work(self):
        self.client.post("/add", data=self.completed())
        original = self.rows()
        for _ in range(3):
            self.assertEqual(self.login_admin().status_code, 303)
            forms = PostForms(self.client.get("/admin").get_data(as_text=True)).forms
            self.assertEqual(len(forms), 2)
            for form in forms:
                self.assertTrue(form["fields"].get("csrf_token"))
            self.assertEqual(self.client.post("/logout", data=self.csrf()).status_code, 303)
            self.assertEqual(self.client.get("/").status_code, 303)
            self.assertEqual(self.client.get("/backup").status_code, 303)
        self.assertEqual(self.rows(), original)

    def test_tampered_cookie_and_other_browser_cannot_inherit_admin(self):
        self.login_admin()
        cookie = self.client.get_cookie("studylog_session")
        attacker = self.module.app.test_client()
        attacker.set_cookie("studylog_session", cookie.value + "forged")
        self.assertEqual(attacker.get("/admin").status_code, 303)
        self.assertEqual(self.module.app.test_client().get("/admin").status_code, 303)
        self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_external_next_is_ignored_and_existing_admin_is_redirected(self):
        client = self.module.app.test_client()
        data = FormParser(client.get("/admin/login?next=https://example.com").get_data(as_text=True)).fields
        response = client.post("/admin/login?next=//example.com", data={**data, "passcode": self.PASSCODE})
        self.assertEqual(response.location, "/admin")
        self.assertEqual(client.get("/admin/login").location, "/admin")
        self.assertEqual(client.get("/login").location, "/")

    def test_old_failures_expire_and_success_resets_count(self):
        with patch.object(self.module.time, "time", return_value=1000):
            for _ in range(4):
                self.assertEqual(self.login_admin(self.module.app.test_client(), "wrong123").status_code, 401)
            self.assertEqual(self.login_admin().status_code, 303)
            for _ in range(4):
                self.assertEqual(self.login_admin(self.module.app.test_client(), "wrong123").status_code, 401)
        with patch.object(self.module.time, "time", return_value=1301):
            self.assertEqual(self.login_admin(self.module.app.test_client(), "wrong123").status_code, 401)
