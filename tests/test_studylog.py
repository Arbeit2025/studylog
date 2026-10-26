"""実際のFlaskルートと、一時コピー内のSQLiteを使う回帰テスト。"""
import importlib.util
import os
import shutil
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "soapp.py"


class FormParser(HTMLParser):
    """ブラウザが送信する空欄・選択値も含めて、最初のPOSTフォームを読む。"""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.fields = {}
        self.active = False
        self.finished = False
        self.textarea = None
        self.select = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("method") == "post" and not self.finished:
            self.active = True
        if not self.active:
            return
        name = attrs.get("name")
        if tag == "input" and name:
            self.fields[name] = attrs.get("value", "")
        elif tag == "textarea":
            self.textarea = name
            self.fields[name] = ""
        elif tag == "select":
            self.select = name
            self.fields[name] = ""
        elif tag == "option" and self.select and "selected" in attrs:
            self.fields[self.select] = attrs.get("value", "")

    def handle_data(self, data):
        if self.active and self.textarea:
            self.fields[self.textarea] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.textarea = None
        elif tag == "select":
            self.select = None
        elif tag == "form" and self.active:
            self.active = False
            self.finished = True


class StudylogFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="studylog-test-")
        self.root = Path(self.directory.name)
        shutil.copy2(SOURCE, self.root / "soapp.py")
        self.load_app()

    def tearDown(self):
        self.directory.cleanup()

    def load_app(self):
        spec = importlib.util.spec_from_file_location("isolated_studylog", self.root / "soapp.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.app.config["TESTING"] = True
        self.client = self.module.app.test_client()

    def rows(self):
        with sqlite3.connect(self.root / "studylog.db") as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM logs ORDER BY id")]

    def form(self, path="/"):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return FormParser(response.get_data(as_text=True)).fields

    def before(self):
        data = self.form()
        data.update(study_date="2026-10-26", category="Python", task="例題を解く",
                    goal="3問", planned_minutes="30", strategy="小さく区切る",
                    before_concentration="3", before_understanding="2", before_confidence="2",
                    before_test_score="0", save_stage="before")
        return data

    def completed(self):
        data = self.before()
        data.update(minutes="45", concentration="4", understanding="5", confidence="4",
                    after_test_score="87.5", success_reason="例を試した", fail_reason="用語が難しい",
                    next_action="復習する", stumble_reason="難しすぎた", memo="続けたい",
                    save_stage="after")
        return data

class StudylogTest(StudylogFixture):
    def test_before_then_after_using_rendered_form(self):
        self.assertEqual(self.client.post("/add", data=self.before()).status_code, 302)
        before = self.rows()[0]
        self.assertEqual(before["status"], "in_progress")
        self.assertIsNotNone(before["before_saved_at"])
        for field in ("minutes", "concentration", "understanding", "confidence", "after_test_score", "after_saved_at"):
            self.assertIsNone(before[field], field)
        self.assertEqual(self.module.studylog_plus_get_summary()["total_minutes"], 0)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("学習後を記録", html)
        self.assertIn('<span class="pill">学習中</span>', html)
        self.assertNotIn("None", html)
        self.assertNotIn("自信 3</span>", html)

        data = self.form(f"/edit/{before['id']}")
        self.assertEqual(data["before_test_score"], "0.0")
        data.update({key: self.completed()[key] for key in (
            "minutes", "concentration", "understanding", "confidence", "after_test_score",
            "success_reason", "fail_reason", "next_action", "stumble_reason", "memo", "save_stage")})
        self.assertEqual(self.client.post(f"/update/{before['id']}", data=data).status_code, 302)
        after = self.rows()[0]
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(after["status"], "completed")
        for key in ("task", "goal", "planned_minutes", "strategy", "before_concentration",
                    "before_understanding", "before_confidence", "before_test_score", "before_saved_at", "created_at"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["after_test_score"], 87.5)
        self.assertIsNotNone(after["after_saved_at"])
        html = self.client.get("/").get_data(as_text=True)
        for text in ("理解度: 2 → 5（変化 +3", "自信度: 2 → 4（変化 +2", "変化 +87.5点", "予定との差 +15分"):
            self.assertIn(text, html)
        self.assertEqual(self.module.studylog_plus_get_summary()["total_minutes"], 45)

    def test_completed_at_once_and_multiple_edits(self):
        self.client.post("/add", data=self.completed())
        original = self.rows()[0]
        for minutes in (25, 35, 50):
            data = self.form(f"/edit/{original['id']}")
            data.update(minutes=str(minutes), memo=f"編集{minutes}", save_stage="after")
            self.assertEqual(self.client.post(f"/update/{original['id']}", data=data).status_code, 302)
            current = self.rows()[0]
            self.assertEqual(current["minutes"], minutes)
            self.assertEqual(current["memo"], f"編集{minutes}")
            for key in ("before_saved_at", "after_saved_at", "created_at", "before_understanding"):
                self.assertEqual(current[key], original[key])

    def test_restart_and_different_working_directory(self):
        self.client.post("/add", data=self.before())
        original = self.rows()
        with tempfile.TemporaryDirectory(prefix="studylog-cwd-") as other:
            # 実際にcwdを変更し、新しいモジュールとしてアプリを読み直す。
            actual = Path.cwd()
            try:
                os.chdir(other)
                self.load_app()
                self.assertEqual(self.rows(), original)
                self.assertEqual(self.client.get("/").status_code, 200)
                self.assertFalse((Path(other) / "studylog.db").exists())
            finally:
                os.chdir(actual)

    def test_old_schema_migration_is_repeatable_and_preserves_data(self):
        (self.root / "studylog.db").unlink()
        with sqlite3.connect(self.root / "studylog.db") as conn:
            conn.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, study_date TEXT, minutes INTEGER, concentration INTEGER, understanding INTEGER, memo TEXT, created_at TEXT)")
            conn.execute("INSERT INTO logs VALUES (1, '2025-05-06', 20, 4, 3, '以前のログ', '2025-05-06 12:00:00')")
        for _ in range(3):
            self.load_app()
            self.module.studylog_plus_add_missing_columns()
            old = self.rows()[0]
            self.assertEqual((old["minutes"], old["memo"], old["created_at"]), (20, "以前のログ", "2025-05-06 12:00:00"))
            self.assertEqual(old["status"], "completed")
            for key in ("before_understanding", "before_confidence", "before_test_score", "before_saved_at", "after_saved_at"):
                self.assertIsNone(old[key])
            self.assertEqual(self.client.get("/").status_code, 200)
            self.assertEqual(self.client.get("/edit/1").status_code, 200)
        self.assertEqual(self.module.studylog_plus_get_summary()["total_minutes"], 20)

    def test_legacy_updates_preserve_new_fields(self):
        self.client.post("/add", data=self.completed())
        before = self.rows()[0]
        # 新しい項目を送らない旧クライアントでも前データを消さない。
        response = self.client.post("/update/1", data={"study_date": "2026-10-26", "minutes": "22", "memo": "旧画面から更新"})
        self.assertEqual(response.status_code, 302)
        after = self.rows()[0]
        self.assertEqual(after["minutes"], 22)
        for key in ("task", "planned_minutes", "strategy", "before_test_score", "before_confidence", "after_test_score"):
            self.assertEqual(after[key], before[key])

    def test_full_legacy_schema_and_other_table_are_preserved(self):
        (self.root / "studylog.db").unlink()
        with sqlite3.connect(self.root / "studylog.db") as conn:
            conn.execute("""CREATE TABLE logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, study_date TEXT, minutes INTEGER,
                concentration INTEGER, understanding INTEGER, memo TEXT, created_at TEXT,
                category TEXT, goal TEXT, confidence INTEGER DEFAULT 3, success_reason TEXT,
                fail_reason TEXT, next_action TEXT, stumble_reason TEXT)""")
            conn.execute("""INSERT INTO logs VALUES (
                37, '2026-10-20', 25, 4, 3, '以前のメモ', '2026-10-20 13:00:00',
                '卒論', '読む', 4, '進んだ', '用語', '調べる', '時間不足')""")
            conn.execute("CREATE TABLE study_logs (id INTEGER PRIMARY KEY, task TEXT)")
            conn.execute("INSERT INTO study_logs VALUES (9, '旧テーブルの内容')")
            expected = conn.execute("SELECT * FROM logs").fetchone()
        for _ in range(3):
            self.load_app()
            migrated = self.rows()[0]
            old_fields = ("id", "study_date", "minutes", "concentration", "understanding", "memo", "created_at",
                          "category", "goal", "confidence", "success_reason", "fail_reason", "next_action", "stumble_reason")
            self.assertEqual(tuple(migrated[key] for key in old_fields), expected)
            self.assertEqual(migrated["status"], "completed")
            self.assertIsNone(migrated["before_understanding"])
            with sqlite3.connect(self.root / "studylog.db") as conn:
                self.assertEqual(conn.execute("SELECT * FROM study_logs").fetchall(), [(9, "旧テーブルの内容")])
        self.client.post("/add", data=self.before())
        self.assertEqual(self.rows()[1]["id"], 38)

    def test_invalid_new_values_do_not_create_rows_and_keep_input(self):
        cases = {"study_date": ["", "2026-02-30", "20261026"], "minutes": ["", "0", "-1", "1.5", "bad", "9" * 100],
                 "planned_minutes": ["0", "bad"], "before_understanding": ["0", "6", "2.5"],
                 "confidence": ["-1", "6", "bad"], "before_test_score": ["-1", "101", "nan", "inf"],
                 "after_test_score": ["oops", "-inf", "100.1"], "save_stage": ["bogus"]}
        for name, invalids in cases.items():
            for value in invalids:
                with self.subTest(name=name, value=value):
                    data = self.completed()
                    data[name] = value
                    response = self.client.post("/add", data=data)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn('role="alert"', response.get_data(as_text=True))
                    self.assertIn("例題を解く", response.get_data(as_text=True))
                    self.assertEqual(self.rows(), [])

    def test_invalid_update_is_atomic_and_retains_form(self):
        self.client.post("/add", data=self.completed())
        before = self.rows()
        data = self.form("/edit/1")
        data.update(before_understanding="9", task="入力途中の内容", save_stage="after")
        response = self.client.post("/update/1", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows(), before)
        self.assertIn("入力途中の内容", response.get_data(as_text=True))
        self.assertIn('value="after"', response.get_data(as_text=True))

    def test_blank_ratings_and_test_scores_remain_null(self):
        data = self.form()
        data.update(study_date="2026-10-26", minutes="10", save_stage="after")
        self.assertEqual(self.client.post("/add", data=data).status_code, 302)
        row = self.rows()[0]
        for key in ("planned_minutes", "concentration", "understanding", "confidence", "before_concentration",
                    "before_understanding", "before_confidence", "before_test_score", "after_test_score", "before_saved_at"):
            self.assertIsNone(row[key], key)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("理解度: 未記録 → 未記録", html)
        self.assertIn("自信 未記録</span>", html)
        self.assertNotIn("None", html)
        self.assertNotIn("変化 +", html)

    def test_zero_scores_and_declines_are_displayed(self):
        data = self.completed()
        data.update(before_test_score="100", after_test_score="0", before_understanding="5", understanding="1", minutes="20")
        self.assertEqual(self.client.post("/add", data=data).status_code, 302)
        self.assertEqual(self.rows()[0]["after_test_score"], 0)
        self.assertEqual(self.form("/edit/1")["after_test_score"], "0.0")
        html = self.client.get("/").get_data(as_text=True)
        for text in ("変化 -100点", "変化 -4", "予定との差 -10分"):
            self.assertIn(text, html)

    def test_draft_results_are_excluded_from_totals_and_averages(self):
        draft = self.completed()
        draft.update(save_stage="before", minutes="100", concentration="1", understanding="1")
        self.client.post("/add", data=draft)
        self.client.post("/add", data=self.completed())
        summary = self.module.studylog_plus_get_summary()
        self.assertEqual(summary, {"count": 2, "completed_count": 1, "in_progress_count": 1,
                                  "total_minutes": 45, "avg_concentration": 4.0, "avg_understanding": 5.0})

    def test_filtering_and_deleting_new_logs(self):
        self.client.post("/add", data=self.completed())
        second = self.completed()
        second.update(category="卒論", study_date="2026-10-20")
        self.client.post("/add", data=second)
        response = self.client.get("/?category=Python&range=custom&start_date=2026-10-25&end_date=2026-10-26")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/edit/1"', html)
        self.assertNotIn('href="/edit/2"', html)
        self.assertEqual(self.client.post("/delete/1").status_code, 302)
        self.assertEqual([row["id"] for row in self.rows()], [2])

    def test_completed_log_cannot_be_accidentally_reopened(self):
        self.client.post("/add", data=self.completed())
        before = self.rows()
        self.assertEqual(self.client.post("/update/1", data={"save_stage": "before"}).status_code, 400)
        self.assertEqual(self.rows(), before)

    def test_missing_log_and_text_escaping(self):
        self.assertEqual(self.client.get("/edit/999").status_code, 404)
        self.assertEqual(self.client.post("/update/999", data=self.completed()).status_code, 404)
        data = self.completed()
        data.update(task='<script>alert("x")</script>', strategy='" onfocus="alert(1)')
        self.client.post("/add", data=data)
        for path in ("/", "/edit/1"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotIn('<script>alert("x")</script>', html)
            self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
