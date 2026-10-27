"""実HTTPサーバーと一時DBで入口・保存・再起動を3回確認する。

実行: python tests/http_auth_smoke.py
"""
import http.cookiejar
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from test_studylog import FormParser, copy_runtime


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def browser():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())


def request(client, base, path, data=None):
    encoded = None if data is None else urllib.parse.urlencode(data).encode()
    try:
        response = client.open(base + path, data=encoded, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, response.headers, response.read().decode()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_once(index):
    with tempfile.TemporaryDirectory(prefix="studylog-http-auth-") as directory:
        root = Path(directory)
        copy_runtime(root)
        environment = os.environ.copy()
        environment.update(STUDYLOG_PIN="4826", STUDYLOG_SECRET_KEY=secrets.token_hex(32),
                           STUDYLOG_ADMIN_PASSCODE="R7t2Qa9z",
                           STUDYLOG_COOKIE_SECURE="0")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        process = None

        def start():
            nonlocal process
            code = ("from werkzeug.serving import make_server; from soapp import app; "
                    f"make_server('127.0.0.1', {port}, app).serve_forever()")
            process = subprocess.Popen([sys.executable, "-c", code], cwd=root, env=environment,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                check(process.poll() is None, "HTTP server exited before becoming ready")
                try:
                    if request(browser(), base, "/login")[0] == 200:
                        return
                except (OSError, urllib.error.URLError):
                    time.sleep(.05)
            raise AssertionError("HTTP server did not become ready")

        def stop():
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

        def login(client):
            status, _, html = request(client, base, "/login")
            check(status == 200, "login page missing")
            data = FormParser(html).fields
            data["pin"] = "4826"
            check(request(client, base, "/login", data)[0] == 303, "correct PIN rejected")

        try:
            start()
            client = browser()
            check(request(client, base, "/")[0] == 303, "index leaked before unlock")
            status, headers, html = request(client, base, "/login")
            check(status == 200 and 'inputmode="numeric"' in html, "numeric PIN form missing")
            check("no-store" in headers["Cache-Control"], "login is cacheable")
            data = FormParser(html).fields
            data["pin"] = "1111"
            check(request(client, base, "/login", data)[0] == 401, "wrong PIN accepted")
            check(request(client, base, "/login", {"pin": "4826"})[0] == 400, "login skipped CSRF")
            login(client)
            _, _, html = request(client, base, "/")
            form = FormParser(html).fields
            form.update(study_date="2026-10-26", category="HTTP確認", task="学習前後を確認",
                        before_understanding="2", save_stage="before")
            check(request(client, base, "/add", form)[0] == 302, "before-save failed")
            check("学習前後を確認" in request(client, base, "/")[2], "saved task missing")
            stop()
            start()
            check(request(client, base, "/")[0] == 200, "session lost across server restart")
            _, _, html = request(client, base, "/edit/1")
            form = FormParser(html).fields
            check(form["before_understanding"] == "2", "before value lost across restart")
            form.update(minutes="25", concentration="4", understanding="4", confidence="4", save_stage="after")
            check(request(client, base, "/update/1", form)[0] == 302, "after-save failed")
            for minutes in (30, 35, 40):
                form = FormParser(request(client, base, "/edit/1")[2]).fields
                form.update(minutes=str(minutes), save_stage="after")
                check(request(client, base, "/update/1", form)[0] == 302, "repeated edit failed")
            html = request(client, base, "/")[2]
            check("変化 +2" in html, "analysis or before/after display missing")
            check(request(client, base, "/backup")[0] == 403, "regular PIN granted admin backup")
            data = FormParser(request(client, base, "/admin/login")[2]).fields
            data["passcode"] = "R7t2Qa9z"
            check(request(client, base, "/admin/login", data)[0] == 303, "admin login failed")
            check("管理者としてログイン中" in request(client, base, "/admin")[2], "admin grant missing")
            stop()
            start()
            check(request(client, base, "/admin")[0] == 200, "admin session lost across restart")
            with client.open(base + "/backup", timeout=5) as response:
                check(response.code == 200, "backup download failed")
                check("attachment" in response.headers["Content-Disposition"], "backup is not an attachment")
                backup = root / "download.sqlite3"
                backup.write_bytes(response.read())
            with sqlite3.connect(backup) as copied, sqlite3.connect(root / "studylog.db") as original:
                check(copied.execute("PRAGMA quick_check").fetchone()[0] == "ok", "backup is corrupt")
                check(copied.execute("SELECT * FROM logs").fetchall() == original.execute("SELECT * FROM logs").fetchall(), "backup lost saved values")
            check(request(browser(), base, "/delete/1", {})[0] == 303, "anonymous delete accepted")
            check(request(client, base, "/edit/1")[0] == 200, "anonymous delete changed the DB")
            check(request(client, base, "/delete/1", {})[0] == 400, "delete skipped CSRF")
            token = FormParser(request(client, base, "/")[2]).fields["csrf_token"]
            check(request(client, base, "/logout", {"csrf_token": token})[0] == 303, "lock failed")
            for path in ("/", "/edit/1"):
                check(request(client, base, path)[0] == 303, "page accessible after locking")
            login(client)
            html = request(client, base, "/")[2]
            token = FormParser(html).fields["csrf_token"]
            check("学習前後を確認" in html, "locking changed a saved log")
            check(request(client, base, "/delete/1", {"csrf_token": token})[0] == 302, "authenticated delete failed")
            check("まだログがありません" in request(client, base, "/")[2], "delete did not persist")
            print(f"HTTP auth smoke {index}/3: PASS", flush=True)
        finally:
            stop()


if __name__ == "__main__":
    for run in range(1, 4):
        run_once(run)
