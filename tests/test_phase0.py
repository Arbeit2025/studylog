"""Phase 0 acceptance: backups, lossless imports, failures, and HTTP boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import hashlib
import os
import sqlite3
import tempfile
import unittest

from test_studylog import StudylogFixture
import studylog_db as database


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="studylog-migration-")
        self.root = Path(self.directory.name)
        self.target = self.root / "studylog.db"

    def tearDown(self):
        self.directory.cleanup()

    def legacy(self, path=None):
        path = path or self.target
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("""CREATE TABLE study_logs (
                id INTEGER PRIMARY KEY, study_date TEXT, goal TEXT, task TEXT,
                minutes INTEGER, focus_score INTEGER, understanding_score INTEGER,
                reflection TEXT, next_action TEXT, created_at TEXT, extra TEXT)""")
            conn.execute("INSERT INTO study_logs VALUES (1, '2026-10-20', '目標', '課題', 30, 4, 2, '振り返り', '復習', '2026-10-20 12:00:00', '独自列も保持')")
        return path

    def rows(self):
        with closing(database.connect(self.target)) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM logs ORDER BY id")]

    def test_migrations_repeat_and_leave_original_tables_untouched(self):
        self.legacy()
        for _ in range(3):
            database.migrate(self.target)
        with closing(database.connect(self.target)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM studylog_schema_migrations").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT extra FROM study_logs").fetchone()[0], "独自列も保持")
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite3"))), 1)

    def test_backup_precedes_schema_changes(self):
        self.legacy()
        backup = database.migrate(self.target)
        with closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_logs").fetchone()[0], 1)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='logs'").fetchone())
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_online_backup_includes_committed_wal(self):
        with closing(sqlite3.connect(self.target)) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE keep (value TEXT)")
            conn.execute("INSERT INTO keep VALUES ('WAL内の記録')")
            conn.commit()
            backup = database.backup_database(self.target)
            with closing(sqlite3.connect(backup)) as copied:
                self.assertEqual(copied.execute("SELECT value FROM keep").fetchone()[0], "WAL内の記録")

    def test_import_same_database_is_repeatable(self):
        self.legacy()
        for index in range(3):
            result = database.import_legacy(self.target, self.target)
            self.assertEqual(result["imported"], 1 if index == 0 else 0)
            self.assertEqual(result["skipped"], 0 if index == 0 else 1)
        row = self.rows()[0]
        self.assertEqual((row["id"], row["task"], row["concentration"], row["understanding"], row["memo"]),
                         (1, "課題", 4, 2, "振り返り"))
        self.assertIsNone(row["confidence"])
        self.assertIsNone(row["before_understanding"])
        with closing(sqlite3.connect(self.target)) as conn:
            self.assertEqual(conn.execute("SELECT extra FROM study_logs").fetchone()[0], "独自列も保持")

    def test_external_import_keeps_source_bytes_and_resolves_id_collisions(self):
        source = self.legacy(self.root / "srl_log.db")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        database.migrate(self.target)
        with closing(sqlite3.connect(self.target)) as conn, conn:
            conn.execute("INSERT INTO logs (id, memo) VALUES (1, '現在の記録')")
        result = database.import_legacy(self.target, source)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(self.rows()[0]["memo"], "現在の記録")
        self.assertEqual(self.rows()[1]["memo"], "振り返り")
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(database.import_legacy(self.target, source)["skipped"], 1)

    def test_external_logs_preserve_zero_missing_scores_and_tracking(self):
        source = self.root / "old-logs.sqlite"
        database.migrate(source)
        with closing(database.connect(source)) as conn, conn:
            conn.execute("""INSERT INTO logs (id, study_date, minutes, after_test_score,
                before_confidence, plan_tracking, status) VALUES (37, '2026-10-20', 20, 0, NULL, '保持する文字列', 'completed')""")
            expected = dict(conn.execute("SELECT * FROM logs").fetchone())
        database.import_legacy(self.target, source, "logs")
        self.assertEqual(self.rows(), [expected])

    def test_changed_source_rolls_back_entire_import(self):
        source = self.legacy(self.root / "old.db")
        database.import_legacy(self.target, source)
        before = self.rows()
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("UPDATE study_logs SET reflection='後から編集' WHERE id=1")
            conn.execute("INSERT INTO study_logs (id, study_date, minutes) VALUES (0, '2026-10-19', 5)")
        with self.assertRaisesRegex(ValueError, "上書きせず"):
            database.import_legacy(self.target, source)
        self.assertEqual(self.rows(), before)
        with closing(sqlite3.connect(self.target)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM studylog_legacy_imports").fetchone()[0], 1)

    def test_deleted_imported_record_is_not_resurrected(self):
        source = self.legacy(self.root / "old.db")
        database.import_legacy(self.target, source)
        with closing(sqlite3.connect(self.target)) as conn, conn:
            conn.execute("DELETE FROM logs")
        self.assertEqual(database.import_legacy(self.target, source)["skipped"], 1)
        self.assertEqual(self.rows(), [])

    def test_failed_backup_prevents_schema_mutation(self):
        self.legacy()
        before = self.target.read_bytes()
        with patch.object(database, "backup_database", side_effect=OSError("full disk")):
            with self.assertRaises(OSError):
                database.migrate(self.target)
        self.assertEqual(before, self.target.read_bytes())

    def test_failed_migration_rolls_back_schema_and_data(self):
        self.legacy()
        before = self.target.read_bytes()
        def fail(conn):
            conn.execute("INSERT INTO logs (memo) VALUES ('途中の変更')")
            raise sqlite3.OperationalError("simulated migration failure")
        migrations = ((1, "canonical", database._create_logs), (2, "failure", fail))
        with patch.object(database, "MIGRATIONS", migrations):
            with self.assertRaises(sqlite3.OperationalError):
                database.migrate(self.target)
        self.assertEqual(before, self.target.read_bytes())

    def test_concurrent_startup_applies_each_migration_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: database.migrate(self.target), range(4)))
        with closing(sqlite3.connect(self.target)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM studylog_schema_migrations").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_future_schema_version_is_not_overwritten(self):
        database.migrate(self.target)
        with closing(sqlite3.connect(self.target)) as conn, conn:
            conn.execute("INSERT INTO studylog_schema_migrations VALUES (999, 'future', '2026-10-26')")
        before = self.target.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            database.migrate(self.target)
        self.assertEqual(before, self.target.read_bytes())

    def test_missing_column_is_repaired_with_backup(self):
        database.migrate(self.target)
        with closing(sqlite3.connect(self.target)) as conn, conn:
            conn.execute("INSERT INTO logs (memo) VALUES ('保持')")
            conn.execute("ALTER TABLE logs DROP COLUMN plan_tracking")
        backup = database.migrate(self.target)
        self.assertTrue(backup.exists())
        self.assertEqual(self.rows()[0]["memo"], "保持")
        self.assertIsNone(self.rows()[0]["plan_tracking"])

    def test_unknown_legacy_shape_is_rejected_without_changes(self):
        source = self.root / "unknown.db"
        with closing(sqlite3.connect(source)) as conn:
            conn.execute("CREATE TABLE study_logs (id INTEGER, task TEXT)")
        before = source.read_bytes()
        with self.assertRaises(ValueError):
            database.import_legacy(self.target, source)
        self.assertFalse(self.target.exists())
        self.assertEqual(source.read_bytes(), before)

    def test_source_connection_is_readonly(self):
        self.legacy()
        with closing(database.readonly(self.target)) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM study_logs")

    def test_inventory_finds_sqlite_by_content_and_excludes_backups(self):
        self.legacy(self.root / "database-without-extension")
        database.migrate(self.target)
        database.backup_database(self.target)
        self.assertEqual(database.find_databases(self.root), {self.target, self.root / "database-without-extension"})


class Phase0HttpTest(StudylogFixture):
    def test_backup_requires_unlock_and_preserves_database(self):
        self.client.post("/add", data=self.completed())
        before = self.rows()
        self.assertEqual(self.module.app.test_client().get("/backup").status_code, 303)
        response = self.client.get("/backup")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        path = self.root / "download.sqlite3"
        path.write_bytes(response.data)
        with closing(database.connect(path)) as conn:
            self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM logs")], before)
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.assertEqual(self.rows(), before)

    def test_database_read_failure_is_safe_503(self):
        with patch.object(self.module, "studylog_plus_get_conn", side_effect=sqlite3.OperationalError("PRIVATE /server/path")), patch.object(self.module.app.logger, "error"):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        html = response.get_data(as_text=True)
        for secret in ("PRIVATE", "/server/path", "Traceback", "OperationalError"):
            self.assertNotIn(secret, html)

    def test_failed_write_rolls_back_and_keeps_existing_record(self):
        self.client.post("/add", data=self.completed())
        before = self.rows()
        class FailedConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                result = super().execute(sql, *args)
                if sql.lstrip().upper().startswith("UPDATE LOGS"):
                    raise sqlite3.OperationalError("PRIVATE failure after write")
                return result
        def connect():
            conn = sqlite3.connect(self.root / "studylog.db", factory=FailedConnection)
            conn.row_factory = sqlite3.Row
            return conn
        data = self.completed()
        data["memo"] = "部分更新されてはいけない"
        with patch.object(self.module, "studylog_plus_get_conn", side_effect=connect), patch.object(self.module.app.logger, "error"):
            self.assertEqual(self.client.post("/update/1", data=data).status_code, 503)
        self.assertEqual(self.rows(), before)

    def test_custom_date_validation_and_reversed_ranges(self):
        for query in ("range=unknown", "range=custom&start_date=2026-02-30", "range=custom&end_date=20261026", "range=custom&start_date=2026-10-26&end_date=2026-10-01"):
            self.assertEqual(self.client.get("/?" + query).status_code, 400, query)
        self.assertEqual(self.client.get("/?range=custom&start_date=2026-10-01&end_date=2026-10-26").status_code, 200)
        self.assertEqual(self.rows(), [])

    def test_long_text_is_rejected_and_existing_values_remain(self):
        self.client.post("/add", data=self.completed())
        before = self.rows()
        for name, length in (("category", 101), ("goal", 2001), ("memo", 10001)):
            data = self.completed()
            data[name] = "あ" * length
            self.assertEqual(self.client.post("/update/1", data=data).status_code, 400)
            self.assertEqual(self.rows(), before)

    def test_large_request_is_rejected_without_writing(self):
        self.assertEqual(self.client.post("/add", data={**self.csrf(), "memo": "x" * (300 * 1024)}).status_code, 413)
        self.assertEqual(self.rows(), [])

    def test_invalid_legacy_numbers_do_not_crash_list_or_rewrite_records(self):
        self.client.post("/add", data=self.completed())
        with closing(sqlite3.connect(self.root / "studylog.db")) as conn, conn:
            conn.execute("UPDATE logs SET before_understanding='old-invalid', planned_minutes='old-invalid', after_test_score=1000")
        before = self.rows()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.rows(), before)

    def test_internal_failure_does_not_expose_debug_information(self):
        with patch.dict(self.module.app.config, {"PROPAGATE_EXCEPTIONS": False}), patch.object(self.module, "studylog_analyze_logs", side_effect=RuntimeError("PRIVATE internal")), patch.object(self.module.app.logger, "error"):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("PRIVATE", response.get_data(as_text=True))
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_public_assets_and_content_security_policy(self):
        client = self.module.app.test_client()
        for asset in ("theme.js", "theme.css", "app.css", "login.css", "session.js"):
            with client.get("/static/" + asset) as response:
                self.assertEqual(response.status_code, 200)
        response = client.get("/login")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", response.headers["Content-Security-Policy"])
        self.assertFalse(self.module.app.debug)

    def test_missing_delete_is_404_and_does_not_affect_other_logs(self):
        self.client.post("/add", data=self.completed())
        before = self.rows()
        self.assertEqual(self.client.post("/delete/9999", data=self.csrf()).status_code, 404)
        self.assertEqual(self.rows(), before)

    def test_environment_database_path_uses_only_configured_file(self):
        alternate = self.root / "data" / "private.sqlite3"
        before = self.rows()
        with patch.dict(os.environ, {"STUDYLOG_DB_PATH": str(alternate)}):
            self.load_app()
            self.assertEqual(self.module.DB_PATH, alternate)
            self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.rows(), before)
        self.assertTrue(alternate.exists())

    def test_cli_backup_and_import_are_available(self):
        source = self.root / "legacy.sqlite3"
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("CREATE TABLE study_logs (id INTEGER PRIMARY KEY, study_date TEXT, minutes INTEGER, focus_score INTEGER, understanding_score INTEGER)")
            conn.execute("INSERT INTO study_logs VALUES (9, '2026-10-20', 15, 2, 3)")
        runner = self.module.app.test_cli_runner()
        imported = runner.invoke(args=["import-legacy", str(source)])
        self.assertEqual(imported.exit_code, 0, imported.output)
        self.assertIn('"imported": 1', imported.output)
        self.assertEqual(len(self.rows()), 1)
        result = runner.invoke(args=["backup-databases"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertGreaterEqual(len(result.output.splitlines()), 2)
