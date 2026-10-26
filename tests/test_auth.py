"""PINの入口、保存処理の保護、Cookie、試行制限を一時DBで検証する。"""
import secrets
import sqlite3
from html.parser import HTMLParser
from unittest.mock import patch

from test_studylog import FormParser, StudylogFixture


class PostForms(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"action": attrs.get("action"), "method": attrs.get("method"), "fields": {}}
        elif tag == "input" and self.current is not None and attrs.get("name"):
            self.current["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self.current is not None:
            if self.current["method"] == "post":
                self.forms.append(self.current)
            self.current = None


class AuthTest(StudylogFixture):
    # この番号はテスト専用。本番の暗証番号・秘密鍵はソースに保存しない。
    PIN = "4826"

    def anon(self):
        return self.module.app.test_client()

    def login(self, client, pin=None, **extra):
        response = client.get("/login")
        self.assertEqual(response.status_code, 200)
        data = FormParser(response.get_data(as_text=True)).fields
        data.update(pin=self.PIN if pin is None else pin, **extra)
        return client.post("/login", data=data)

    def reset_attempts(self):
        with sqlite3.connect(self.root / "studylog.db") as conn:
            conn.execute("DELETE FROM studylog_auth_attempts")

    def test_anonymous_cannot_read_or_mutate_even_by_direct_url(self):
        self.client.post("/add", data=self.completed())
        original = self.rows()
        client = self.anon()
        for path in ("/", "/?category=Python", "/edit/1", "/edit/999", "/studylog.db", "/unknown"):
            for method in ("get", "head"):
                with self.subTest(path=path, method=method):
                    response = getattr(client, method)(path)
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(response.location, "/login")
                    self.assertNotIn("例題を解く", response.get_data(as_text=True))
        for path in ("/add", "/update/1", "/delete/1"):
            response = client.post(path, data={"study_date": "2026-10-26", "minutes": "10"})
            self.assertEqual(response.status_code, 303)
        self.assertEqual(self.rows(), original)

    def test_login_form_is_masked_and_uses_numeric_keyboard(self):
        response = self.anon().get("/login")
        html = response.get_data(as_text=True)
        for attr in ('type="password"', 'inputmode="numeric"', 'pattern="[0-9]{4}"', 'maxlength="4"'):
            self.assertIn(attr, html)
        self.assertNotIn(self.PIN, html)
        self.assertNotIn(self.module.app.secret_key, html)
        self.assertNotIn("学習ログを追加", html)

    def test_correct_login_preserves_data_and_rotates_csrf(self):
        self.client.post("/add", data=self.completed())
        original = self.rows()
        client = self.anon()
        old_token = FormParser(client.get("/login").get_data(as_text=True)).fields["csrf_token"]
        response = client.post("/login", data={"pin": self.PIN, "csrf_token": old_token})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, "/")
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("例題を解く", page.get_data(as_text=True))
        new_token = FormParser(page.get_data(as_text=True)).fields["csrf_token"]
        self.assertNotEqual(old_token, new_token)
        self.assertEqual(client.post("/delete/1", data={"csrf_token": old_token}).status_code, 400)
        self.assertEqual(self.rows(), original)

    def test_wrong_and_malformed_pins_stay_locked_without_echo(self):
        for pin in ("1111", "", "482", "48260", "４８２６", "٤٨٢٦", "4826 ", " 4826", "abcd"):
            with self.subTest(pin=pin):
                self.reset_attempts()
                client = self.anon()
                response = self.login(client, pin)
                self.assertEqual(response.status_code, 401)
                self.assertIn("暗証番号が違います", response.get_data(as_text=True))
                self.assertEqual(client.get("/").status_code, 303)
                self.assertNotIn('value="4826"', response.get_data(as_text=True))

    def test_leading_zero_pin_is_supported(self):
        self.module.app.config["STUDYLOG_PIN"] = "0123"
        client = self.anon()
        self.assertEqual(self.login(client, "0123").status_code, 303)
        self.assertEqual(client.get("/").status_code, 200)

    def test_attempt_limit_is_shared_survives_new_app_and_recovers(self):
        with patch.object(self.module.time, "time", return_value=1000):
            for _ in range(4):
                self.assertEqual(self.login(self.anon(), "1111").status_code, 401)
            fifth = self.login(self.anon(), "1111")
            self.assertEqual(fifth.status_code, 429)
            self.assertEqual(fifth.headers["Retry-After"], "30")
        # 同じDBを別のアプリとして読み直しても、正解を含めロック中は拒否する。
        with patch("time.time", return_value=1010):
            self.load_app_without_login()
            response = self.login(self.anon())
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "20")
        with patch.object(self.module.time, "time", return_value=1030):
            client = self.anon()
            self.assertEqual(self.login(client).status_code, 303)
            self.assertEqual(client.get("/").status_code, 200)

    def load_app_without_login(self):
        import importlib.util
        key = self.module.app.secret_key
        spec = importlib.util.spec_from_file_location("auth_restart", self.root / "soapp.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.app.config.update(TESTING=True, SECRET_KEY=key, STUDYLOG_PIN=self.PIN,
                                      SESSION_COOKIE_SECURE=False)

    def test_success_resets_failures_and_old_failures_expire(self):
        with patch.object(self.module.time, "time", return_value=1000):
            for _ in range(4):
                self.assertEqual(self.login(self.anon(), "1111").status_code, 401)
            self.assertEqual(self.login(self.anon()).status_code, 303)
            for _ in range(4):
                self.assertEqual(self.login(self.anon(), "1111").status_code, 401)
        with patch.object(self.module.time, "time", return_value=1301):
            self.assertEqual(self.login(self.anon(), "1111").status_code, 401)

    def test_missing_or_invalid_configuration_fails_closed(self):
        app = self.module.app
        original = dict(app.config)
        for name, value in (("STUDYLOG_PIN", ""), ("STUDYLOG_PIN", "123"),
                            ("STUDYLOG_PIN", "abcd"), ("SECRET_KEY", None), ("SECRET_KEY", "short")):
            with self.subTest(name=name, value=value):
                app.config.update(original)
                app.config[name] = value
                for path in ("/", "/login", "/edit/1"):
                    response = self.anon().get(path)
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn("学習ログを追加", response.get_data(as_text=True))
                self.assertEqual(self.client.post("/add", data={}).status_code, 503)
        app.config.update(original)
        self.assertEqual(self.rows(), [])

    def test_csrf_required_for_login_and_all_writes(self):
        self.client.post("/add", data=self.completed())
        original = self.rows()
        for token in ({}, {"csrf_token": "wrong"}, {"csrf_token": "日本語"}):
            for path in ("/add", "/update/1", "/delete/1", "/logout"):
                self.assertEqual(self.client.post(path, data=token).status_code, 400)
            client = self.anon()
            client.get("/login")
            self.assertEqual(client.post("/login", data={"pin": self.PIN, **token}).status_code, 400)
            self.assertEqual(client.get("/").status_code, 303)
        self.assertEqual(self.rows(), original)

    def test_every_rendered_post_form_has_current_csrf(self):
        self.client.post("/add", data=self.completed())
        for path in ("/", "/edit/1"):
            forms = PostForms(self.client.get(path).get_data(as_text=True)).forms
            self.assertIn("/logout", [form["action"] for form in forms])
            with self.client.session_transaction() as state:
                expected = state["studylog_csrf"]
            for form in forms:
                self.assertEqual(form["fields"].get("csrf_token"), expected, form["action"])
        self.assertEqual(len(PostForms(self.client.get("/").get_data(as_text=True)).forms), 3)

    def test_lock_and_repeat_unlock_work_without_changing_logs(self):
        self.client.post("/add", data=self.completed())
        original = self.rows()
        for _ in range(3):
            data = self.csrf()
            self.assertEqual(self.client.post("/logout", data=data).status_code, 303)
            self.assertEqual(self.client.get("/").status_code, 303)
            self.assertEqual(self.client.get("/edit/1").status_code, 303)
            self.assertEqual(self.login(self.client).status_code, 303)
            self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.rows(), original)
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_expiry_pin_change_and_key_change_invalidate_unlock(self):
        app = self.module.app
        client = self.anon()
        with patch.object(self.module.time, "time", return_value=1000):
            self.assertEqual(self.login(client).status_code, 303)
        with patch.object(self.module.time, "time", return_value=44199):
            self.assertEqual(client.get("/").status_code, 200)
        with patch.object(self.module.time, "time", return_value=44200):
            self.assertEqual(client.get("/").status_code, 303)
        client = self.anon()
        self.login(client)
        app.config["STUDYLOG_PIN"] = "7912"
        self.assertEqual(client.get("/").status_code, 303)
        app.config["STUDYLOG_PIN"] = self.PIN
        self.login(client)
        app.secret_key = secrets.token_hex(32)
        self.assertEqual(client.get("/").status_code, 303)

    def test_secure_cookie_and_no_cache_headers(self):
        self.module.app.config["SESSION_COOKIE_SECURE"] = True
        client = self.anon()
        page = client.get("/login", base_url="https://localhost")
        cookie = page.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Expires=", cookie)
        self.assertNotIn(self.PIN, cookie)
        for response in (page, self.client.get("/"), self.anon().get("/edit/1")):
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_tampered_cookie_and_other_browser_stay_locked(self):
        client = self.anon()
        self.login(client)
        cookie = client.get_cookie("studylog_session")
        tampered = self.anon()
        tampered.set_cookie("studylog_session", cookie.value + "tampered")
        self.assertEqual(tampered.get("/").status_code, 303)
        self.assertEqual(self.anon().get("/").status_code, 303)
        self.assertEqual(client.get("/").status_code, 200)

    def test_unrelated_anonymous_requests_do_not_break_login_form(self):
        client = self.anon()
        data = FormParser(client.get("/login").get_data(as_text=True)).fields
        for path in ("/favicon.ico", "/unknown", "/"):
            self.assertEqual(client.get(path).status_code, 303)
        data["pin"] = self.PIN
        self.assertEqual(client.post("/login", data=data).status_code, 303)

    def test_external_next_parameter_never_redirects_outside_app(self):
        client = self.anon()
        page = client.get("/login?next=https://example.com")
        data = FormParser(page.get_data(as_text=True)).fields
        response = client.post("/login?next=//example.com", data={**data, "pin": self.PIN})
        self.assertEqual(response.location, "/")
