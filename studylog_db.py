"""One SQLite store, online backups, and non-destructive versioned migrations."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import hashlib
import hmac
import json
import math
import os
import sqlite3
import uuid


SCHEMA_VERSION = 2
LOG_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "study_date": "TEXT", "minutes": "INTEGER", "concentration": "INTEGER",
    "understanding": "INTEGER", "memo": "TEXT", "created_at": "TEXT",
    "category": "TEXT", "goal": "TEXT", "confidence": "INTEGER DEFAULT 3",
    "success_reason": "TEXT", "fail_reason": "TEXT", "next_action": "TEXT",
    "stumble_reason": "TEXT", "task": "TEXT", "planned_minutes": "INTEGER",
    "strategy": "TEXT", "before_concentration": "INTEGER",
    "before_understanding": "INTEGER", "before_confidence": "INTEGER",
    "before_test_score": "REAL", "after_test_score": "REAL",
    "status": "TEXT NOT NULL DEFAULT 'completed'", "before_saved_at": "TEXT",
    "after_saved_at": "TEXT", "updated_at": "TEXT", "plan_tracking": "TEXT",
}


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def readonly(path):
    return sqlite3.connect(f"file:{quote(str(Path(path).resolve()))}?mode=ro", uri=True, timeout=10)


def backup_database(path, directory=None):
    """Use SQLite's online backup API so committed WAL pages are included."""
    path = Path(path).resolve()
    directory = Path(directory) if directory is not None else path.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = directory / f"{path.stem}-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3"
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(readonly(path)) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("バックアップの整合性を確認できませんでした。")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def find_databases(root):
    paths = set()
    for path in Path(root).rglob("*"):
        if not path.is_file() or {".git", "backups", "__pycache__", ".venv", "venv"} & set(path.parts):
            continue
        with path.open("rb") as stream:
            if stream.read(16) == b"SQLite format 3\x00":
                paths.add(path.resolve())
    return paths


def _create_logs(conn):
    fields = ", ".join(f'"{name}" {definition}' for name, definition in LOG_COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS logs ({fields})")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(logs)")}
    if "id" not in columns:
        raise sqlite3.DatabaseError("既存のlogsテーブルにidがありません。元DBを確認してください。")
    for name, definition in LOG_COLUMNS.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE logs ADD COLUMN "{name}" {definition}')


def _add_import_tracking(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS studylog_legacy_imports (
        source_key TEXT NOT NULL, source_table TEXT NOT NULL, source_id TEXT NOT NULL,
        target_id INTEGER NOT NULL, fingerprint TEXT NOT NULL, imported_at TEXT NOT NULL,
        PRIMARY KEY (source_key, source_table, source_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS studylog_logs_date ON logs(study_date, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS studylog_logs_category ON logs(category, study_date, id)")


MIGRATIONS = ((1, "canonical_logs", _create_logs), (2, "legacy_import_tracking", _add_import_tracking))


def migrate(path):
    """Serialize workers; back up existing bytes before any schema mutation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.exists() and path.stat().st_size > 0
    with closing(connect(path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        has_versions = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studylog_schema_migrations'").fetchone()
        applied = {row[0] for row in conn.execute("SELECT version FROM studylog_schema_migrations")} if has_versions else set()
        if applied - {version for version, _, _ in MIGRATIONS}:
            raise sqlite3.DatabaseError("このアプリより新しいDBです。対応するバージョンで起動してください。")
        pending = [(version, name, action) for version, name, action in MIGRATIONS if version not in applied]
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(logs)")}
        repair_columns = not set(LOG_COLUMNS) <= columns
        if not pending and not repair_columns:
            return None
        backup = backup_database(path) if existing else None
        conn.execute("""CREATE TABLE IF NOT EXISTS studylog_schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
        )""")
        for version, name, action in pending:
            action(conn)
            conn.execute("INSERT INTO studylog_schema_migrations VALUES (?, ?, ?)",
                         (version, name, datetime.now(timezone.utc).isoformat()))
        if repair_columns and not any(version == 1 for version, _, _ in pending):
            _create_logs(conn)
    return backup


def import_legacy(destination, source, table="study_logs"):
    """Explicitly merge legacy rows. Keep sources and colliding target IDs intact."""
    if table not in ("logs", "study_logs"):
        raise ValueError("移行元のテーブルを確認してください。")
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination and table == "logs":
        raise ValueError("現在使用中のlogsテーブルは移行する必要がありません。")
    with closing(readonly(source)) as original:
        original.row_factory = sqlite3.Row
        columns = {row["name"] for row in original.execute(f'PRAGMA table_info("{table}")')}
        required = {"id", "study_date", "minutes"}
        if table == "study_logs":
            required |= {"focus_score", "understanding_score"}
        if not required <= columns:
            raise ValueError("移行元テーブルの構造が一致しません。元データは変更していません。")
        rows = [dict(row) for row in original.execute(f'SELECT * FROM "{table}" ORDER BY id')]
    migrate(destination)
    backups = [str(backup_database(path)) for path in sorted({source, destination})]
    imported = skipped = 0
    with closing(connect(destination)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            source_id = str(row["id"])
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True,
                                 default=lambda value: {"bytes": value.hex()} if isinstance(value, bytes) else str(value))
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            previous = conn.execute("""SELECT fingerprint FROM studylog_legacy_imports
                WHERE source_key=? AND source_table=? AND source_id=?""", (str(source), table, source_id)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError("移行済みの元データに変更があります。上書きせず移行を中止しました。")
                skipped += 1
                continue
            if table == "study_logs":
                mapping = {"study_date": "study_date", "goal": "goal", "task": "task",
                           "minutes": "minutes", "concentration": "focus_score",
                           "understanding": "understanding_score", "memo": "reflection",
                           "next_action": "next_action", "created_at": "created_at"}
                values = {name: row.get(old_name) for name, old_name in mapping.items()}
                values["confidence"] = None
            else:
                values = {name: row[name] for name in LOG_COLUMNS if name != "id" and name in row}
                if "confidence" not in values:
                    values["confidence"] = None
            values.setdefault("status", "completed")
            if not conn.execute("SELECT 1 FROM logs WHERE id=?", (row["id"],)).fetchone():
                values["id"] = row["id"]
            fields = ", ".join(f'"{name}"' for name in values)
            placeholders = ", ".join("?" for _ in values)
            cursor = conn.execute(f"INSERT INTO logs ({fields}) VALUES ({placeholders})", tuple(values.values()))
            conn.execute("INSERT INTO studylog_legacy_imports VALUES (?, ?, ?, ?, ?, ?)",
                         (str(source), table, source_id, cursor.lastrowid, fingerprint,
                          datetime.now(timezone.utc).isoformat()))
            imported += 1
    return {"imported": imported, "skipped": skipped, "backups": backups}


def try_pin(path, candidate, pin, now):
    with closing(connect(path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS studylog_auth_attempts (
            id INTEGER PRIMARY KEY CHECK (id = 1), failures INTEGER NOT NULL,
            last_failure REAL NOT NULL, blocked_until REAL NOT NULL
        )""")
        conn.execute("INSERT OR IGNORE INTO studylog_auth_attempts VALUES (1, 0, 0, 0)")
        failures, last_failure, blocked_until = conn.execute(
            "SELECT failures, last_failure, blocked_until FROM studylog_auth_attempts WHERE id=1").fetchone()
        if blocked_until > now:
            return False, math.ceil(blocked_until - now)
        if blocked_until or now - last_failure >= 300:
            failures = 0
        valid = isinstance(candidate, str) and len(candidate) == 4 and candidate.isascii() and candidate.isdigit()
        accepted = valid and hmac.compare_digest(candidate, pin)
        failures = 0 if accepted else failures + 1
        blocked_until = now + 30 if failures >= 5 else 0
        conn.execute("UPDATE studylog_auth_attempts SET failures=?, last_failure=?, blocked_until=? WHERE id=1",
                     (failures, now, blocked_until))
    return accepted, 30 if blocked_until else 0
