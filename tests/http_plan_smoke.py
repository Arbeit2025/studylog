"""実HTTPと独立した一時DBで、6機能から次回計画への流れを3回検証する。"""
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
from pathlib import Path

from http_auth_smoke import browser, request, check
from test_planning import PlanSections
from test_studylog import FormParser


def run_once(index):
    with tempfile.TemporaryDirectory(prefix="studylog-http-plan-") as directory:
        root = Path(directory)
        shutil.copy2(Path(__file__).resolve().parents[1] / "soapp.py", root / "soapp.py")
        environment = os.environ.copy()
        environment.update(STUDYLOG_PIN="4826", STUDYLOG_SECRET_KEY=secrets.token_hex(32),
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
                check(process.poll() is None, "HTTP server exited early")
                try:
                    if request(browser(), base, "/login")[0] == 200:
                        return
                except (OSError, urllib.error.URLError):
                    time.sleep(.05)
            raise AssertionError("HTTP server not ready")

        def stop():
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

        def form(path="/"):
            status, _, html = request(client, base, path)
            check(status == 200, f"form request failed: {path}")
            return FormParser(html).fields

        def rows():
            with sqlite3.connect(root / "studylog.db") as conn:
                conn.row_factory = sqlite3.Row
                return [dict(row) for row in conn.execute("SELECT * FROM logs ORDER BY id")]

        try:
            start()
            client = browser()
            check(request(client, base, "/?plan_from=1")[0] == 303, "anonymous preview allowed")
            login = form("/login")
            login["pin"] = "4826"
            check(request(client, base, "/login", login)[0] == 303, "login failed")

            for day in range(10, 15):
                data = form()
                data.update(study_date=f"2026-10-{day}", category="HTTP確認", task="過去の例題",
                            planned_minutes="40", minutes="40", concentration="4", understanding="4",
                            confidence="4", after_test_score="75", save_stage="after")
                check(request(client, base, "/add", data)[0] == 302, "history save failed")
            data = form()
            data.update(study_date="2026-10-26", category="HTTP確認", task="対象の例題",
                        goal="3問", planned_minutes="40", strategy="例題を解く", before_understanding="2",
                        before_test_score="0", next_action="次は1問を確実に解く", save_stage="before")
            check(request(client, base, "/add", data)[0] == 302, "before save failed")
            stop()
            start()
            data = form("/edit/6")
            check(data["before_understanding"] == "2" and data["before_test_score"] == "0.0", "before data lost")
            data.update(minutes="35", concentration="3", understanding="2", confidence="2",
                        after_test_score="25", save_stage="after")
            check(request(client, base, "/update/6", data)[0] == 302, "after save failed")
            source = rows()[5]
            html = request(client, base, "/")[2]
            for fragment in ("個人別の判定基準", "理解の停滞候補", "+25点", "次回の予定時間: 30分"):
                check(fragment in html, f"expected display missing: {fragment}")
            filtered = request(client, base, "/?category=HTTP%E7%A2%BA%E8%AA%8D&range=custom&start_date=2026-10-26&end_date=2026-10-26")[2]
            check(PlanSections(html).sections[6] == PlanSections(filtered).sections[6], "filter changed plan")
            original = rows()
            for _ in range(3):
                data = form("/?plan_from=6")
                check(data["planned_minutes"] == "30", "personal correction not carried forward")
                check(data["goal"] == source["next_action"], "own next action lost")
                check(data["before_test_score"] == "" and data["minutes"] == "", "results copied into next session")
                check(rows() == original, "preview wrote to DB")
            data.update(study_date="2026-10-27", save_stage="before", planned_minutes="0")
            check(request(client, base, "/add", data)[0] == 400, "invalid plan saved")
            check(rows() == original, "invalid plan changed data")
            data["planned_minutes"] = "28"
            check(request(client, base, "/add", data)[0] == 302, "edited next plan did not save")
            saved = rows()[6]
            check(saved["planned_minutes"] == 28 and saved["status"] == "in_progress", "next draft incorrect")
            check(rows()[5] == source, "source log changed")
            stop()
            start()
            check(form("/edit/7")["planned_minutes"] == "28", "next plan lost across restart")
            check(request(client, base, "/?plan_from=7")[0] == 400, "draft generated a plan")
            check(request(client, base, "/?plan_from=999")[0] == 404, "missing source accepted")
            check(request(client, base, "/add", {"save_stage": "before"})[0] == 400, "write skipped CSRF")
            for log_id in range(1, 8):
                check(request(client, base, f"/delete/{log_id}", {"csrf_token": form()["csrf_token"]})[0] == 302, "cleanup failed")
            check(rows() == [], "deleted logs remained")
            print(f"HTTP six-feature smoke {index}/3: PASS", flush=True)
        finally:
            stop()


if __name__ == "__main__":
    for run in range(1, 4):
        run_once(run)
