"""Studylog v0.9: HTTP entry point. Run with gunicorn soapp:app."""
from contextlib import closing
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import tempfile
import time

import click
from flask import Flask, request, redirect, url_for, render_template, session, send_file
from itsdangerous import BadData, URLSafeSerializer

import studylog_db as database
from studylog_analysis import (
    studylog_analysis_number, studylog_analyze_log, studylog_analyze_logs,
    studylog_build_next_plan, studylog_valid_tracking, studylog_evaluate_plan,
    studylog_summarize_effects, STUDYLOG_EFFECT_VERSION, STUDYLOG_EFFECT_METRICS,
)
from studylog_forms import (
    studylog_plus_get_dates, studylog_plus_build_filters, studylog_plus_form_data,
    STUDYLOG_PLUS_STUMBLE_OPTIONS, today_jst,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("STUDYLOG_DB_PATH", BASE_DIR / "studylog.db"))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH
DB_PATH = DB_PATH.resolve()
STUDYLOG_PLUS_DB_NAME = DB_PATH

app = Flask(__name__, root_path=str(BASE_DIR))
app.config.update(
    SECRET_KEY=os.environ.get("STUDYLOG_SECRET_KEY"),
    STUDYLOG_PIN=os.environ.get("STUDYLOG_PIN", ""),
    SESSION_COOKIE_NAME="studylog_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("STUDYLOG_COOKIE_SECURE", "1") != "0",
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=256 * 1024,
    DEBUG=False,
)

def studylog_valid_pin(value):
    return isinstance(value, str) and len(value) == 4 and value.isascii() and value.isdigit()


def studylog_auth_ready():
    key = app.secret_key
    return isinstance(key, str) and len(key) >= 32 and studylog_valid_pin(app.config["STUDYLOG_PIN"])


def studylog_auth_version():
    # PINの変更時には、それまでの解除済みCookieも無効になる。
    return hmac.new(app.secret_key.encode(), app.config["STUDYLOG_PIN"].encode(), hashlib.sha256).hexdigest()


def studylog_is_unlocked():
    version = session.get("studylog_auth_version")
    unlocked_at = session.get("studylog_unlocked_at")
    return (isinstance(version, str) and isinstance(unlocked_at, (int, float))
            and 0 <= time.time() - unlocked_at < 12 * 60 * 60
            and hmac.compare_digest(version, studylog_auth_version()))


def studylog_csrf_token():
    if "studylog_csrf" not in session:
        session["studylog_csrf"] = secrets.token_urlsafe(32)
    return session["studylog_csrf"]


@app.before_request
def studylog_require_unlock():
    if request.endpoint == "static":
        return None
    if not studylog_auth_ready():
        return render_template("login.html", configured=False,
                                      error="暗証番号の設定が完了していません。管理者がサーバー設定を確認してください。"), 503
    if request.endpoint != "studylog_login" and not studylog_is_unlocked():
        # favicon等の別リクエストで、入力中のログインフォームのCSRFを消さない。
        session.pop("studylog_auth_version", None)
        session.pop("studylog_unlocked_at", None)
        return redirect(url_for("studylog_login"), code=303)
    if request.method == "POST":
        expected = session.get("studylog_csrf")
        supplied = request.form.get("csrf_token", "")
        if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), supplied.encode()):
            return "画面の有効期限が切れました。画面を再読み込みして、もう一度お試しください。", 400


@app.after_request
def studylog_private_response(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


@app.route("/login", methods=["GET", "POST"])
def studylog_login():
    if studylog_is_unlocked():
        return redirect(url_for("index"), code=303)
    error = None
    status = 200
    retry_after = 0
    if request.method == "POST":
        accepted, retry_after = studylog_try_pin(request.form.get("pin", ""))
        if accepted:
            session.clear()
            session["studylog_auth_version"] = studylog_auth_version()
            session["studylog_unlocked_at"] = time.time()
            session.permanent = False
            return redirect(url_for("index"), code=303)
        status = 429 if retry_after else 401
        error = (f"入力を繰り返し間違えたため、{retry_after}秒ほど待ってからお試しください。"
                 if retry_after else "暗証番号が違います。数字4桁を確認してください。")
    response = app.make_response((render_template("login.html", configured=True, error=error), status))
    if retry_after:
        response.headers["Retry-After"] = str(retry_after)
    return response


@app.route("/logout", methods=["POST"])
def studylog_logout():
    session.clear()
    return redirect(url_for("studylog_login"), code=303)


@app.context_processor
def studylog_auth_context():
    return {"studylog_csrf_token": studylog_csrf_token,
            "studylog_number": studylog_display_number}


def studylog_display_number(log, field):
    low, high = (0, 100) if field.endswith("test_score") else (1, 2147483647) if field.endswith("minutes") else (1, 5)
    return studylog_analysis_number(dict(log), field, low, high)


def studylog_try_pin(candidate):
    return database.try_pin(DB_PATH, candidate, app.config["STUDYLOG_PIN"], time.time())


def studylog_plus_get_conn():
    return database.connect(DB_PATH)


def studylog_plus_add_missing_columns():
    return database.migrate(DB_PATH)


def studylog_plus_get_logs(where_sql="", params=None):
    if params is None:
        params = []

    with closing(studylog_plus_get_conn()) as conn:
        rows = conn.execute(
            f"SELECT * FROM logs {where_sql} ORDER BY study_date DESC, id DESC",
            params
        ).fetchall()
    return rows


def studylog_plus_get_summary(where_sql="", params=None):
    if params is None:
        params = []

    with closing(studylog_plus_get_conn()) as conn:
        row = conn.execute(
            f'''
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                COALESCE(SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress_count,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN minutes END), 0) AS total_minutes,
                ROUND(COALESCE(AVG(CASE WHEN status = 'completed' THEN concentration END), 0), 1) AS avg_concentration,
                ROUND(COALESCE(AVG(CASE WHEN status = 'completed' THEN understanding END), 0), 1) AS avg_understanding
            FROM logs
            {where_sql}
            ''',
            params
        ).fetchone()

    return {
        "count": row["count"],
        "completed_count": row["completed_count"],
        "in_progress_count": row["in_progress_count"],
        "total_minutes": row["total_minutes"],
        "avg_concentration": row["avg_concentration"],
        "avg_understanding": row["avg_understanding"]
    }


def studylog_plus_get_categories():
    with closing(studylog_plus_get_conn()) as conn:
        rows = conn.execute("""
            SELECT DISTINCT category
            FROM logs
            WHERE category IS NOT NULL AND TRIM(category) != ''
            ORDER BY category
        """).fetchall()
    return [row["category"] for row in rows]


def studylog_plus_get_log(log_id):
    with closing(studylog_plus_get_conn()) as conn:
        row = conn.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
    return row


def studylog_plan_serializer():
    return URLSafeSerializer(app.secret_key, salt="studylog-plan-adoption-v1")


def studylog_plan_token(log, plan, analysis):
    """プレビューした提案と比較元を署名し、保存時まで保持する。GETはDBを変更しない。"""
    log = dict(log)
    snapshot = {
        "version": STUDYLOG_EFFECT_VERSION,
        "source_id": log["id"], "source_date": log["study_date"],
        "category": plan["category"], "source_state": analysis["state"],
        "plan": {key: plan[key] for key in ("version", "minutes", "base_minutes", "goal", "strategy", "reason")},
        "source_results": {field: studylog_analysis_number(log, field, low, high)
                           for field, _, _, low, high in STUDYLOG_EFFECT_METRICS},
    }
    return studylog_plan_serializer().dumps(snapshot)


def studylog_adopt_plan(form, values, conn):
    token = form.get("plan_token")
    if not token:
        return None
    try:
        if not isinstance(token, str) or len(token) > 65536:
            raise ValueError
        snapshot = studylog_plan_serializer().loads(token)
        if not studylog_valid_tracking(snapshot):
            raise ValueError
    except (BadData, ValueError, TypeError):
        raise ValueError("引き継いだ計画を確認できません。元のログからもう一度準備してください。") from None
    source = conn.execute("SELECT id FROM logs WHERE id = ?", (snapshot["source_id"],)).fetchone()
    if source is None:
        raise ValueError("比較元のログが削除されています。別のログから計画を準備してください。")
    snapshot["adopted_at"] = values["updated_at"]
    snapshot["adopted_plan"] = {key: values[key] for key in ("planned_minutes", "goal", "strategy")}
    return json.dumps(snapshot, ensure_ascii=False, allow_nan=False)


def studylog_plus_insert(form):
    values = studylog_plus_form_data(form)
    values["created_at"] = values["updated_at"]
    with closing(studylog_plus_get_conn()) as conn, conn:
        # 比較元の確認と採用の保存は同一トランザクションで行う。
        conn.execute("BEGIN IMMEDIATE")
        values["plan_tracking"] = studylog_adopt_plan(form, values, conn)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        cursor = conn.execute(
            f"INSERT INTO logs ({columns}) VALUES ({placeholders})", tuple(values.values())
        )
        return cursor.lastrowid


def studylog_plus_update_db(log_id, form):
    with closing(studylog_plus_get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
        if current is None:
            return False
        values = studylog_plus_form_data(form, current)
        assignments = ", ".join(f"{name} = ?" for name in values)
        conn.execute(
            f"UPDATE logs SET {assignments} WHERE id = ?", (*values.values(), log_id)
        )
    return True


def studylog_plus_delete_db(log_id):
    with closing(studylog_plus_get_conn()) as conn, conn:
        return conn.execute("DELETE FROM logs WHERE id = ?", (log_id,)).rowcount > 0

def studylog_plus_index(form_data=None, error=None):
    try:
        where_sql, params, filters = studylog_plus_build_filters(request.args)
    except ValueError as exc:
        return render_template("error.html", message=str(exc)), 400
    all_logs = studylog_plus_get_logs()
    logs = studylog_plus_get_logs(where_sql, params) if where_sql else all_logs
    analyses = studylog_analyze_logs(all_logs)
    plans = {log["id"]: studylog_build_next_plan(log, analyses[log["id"]]) for log in all_logs}
    effects = {log["id"]: studylog_evaluate_plan(log) for log in all_logs}
    effect_summary = studylog_summarize_effects(logs, effects)
    summary = studylog_plus_get_summary(where_sql, params)
    categories = studylog_plus_get_categories()
    plan_notice = None
    response_status = 200
    if form_data is None:
        form_data = {"study_date": today_jst().isoformat()}
        source = request.args.get("plan_from")
        if source is not None:
            if not (source.isascii() and source.isdecimal() and len(source) <= 10 and 0 < int(source) <= 2147483647):
                error, response_status = "引き継ぐログの番号を確認してください。", 400
            elif int(source) not in plans:
                error, response_status = "引き継ぐログが見つかりません。", 404
            elif not plans[int(source)]["enabled"]:
                error, response_status = plans[int(source)]["reason"], 400
            else:
                plan = plans[int(source)]
                form_data.update(category=plan["category"], task=plan["task"], goal=plan["goal"],
                                 planned_minutes=plan["minutes"], strategy=plan["strategy"])
                source_log = next(log for log in all_logs if log["id"] == int(source))
                form_data["plan_token"] = studylog_plan_token(source_log, plan, analyses[int(source)])
                plan_notice = f"ログ #{int(source)} の補正計画を入力欄へ引き継ぎました。まだ保存していません。"

    html = render_template(
        "index.html",
        logs=logs,
        analyses=analyses,
        plans=plans,
        effects=effects,
        effect_summary=effect_summary,
        summary=summary,
        categories=categories,
        filters=filters,
        form_data=form_data,
        plan_notice=plan_notice,
        form_action="/add",
        is_edit=False,
        error=error,
        stumble_options=STUDYLOG_PLUS_STUMBLE_OPTIONS
    )
    return html if response_status == 200 else (html, response_status)


def studylog_plus_add():
    try:
        studylog_plus_insert(request.form)
    except ValueError as exc:
        return studylog_plus_index(dict(request.form), str(exc)), 400
    return redirect("/")


def studylog_plus_edit(log_id, form_data=None, error=None):
    log = studylog_plus_get_log(log_id)
    if log is None:
        return "log not found", 404

    return render_template(
        "edit.html",
        form_data=form_data if form_data is not None else dict(log),
        form_action=f"/update/{log_id}",
        is_edit=True,
        error=error,
        stumble_options=STUDYLOG_PLUS_STUMBLE_OPTIONS
    )


def studylog_plus_update(log_id):
    current = studylog_plus_get_log(log_id)
    if current is None:
        return "log not found", 404
    try:
        if not studylog_plus_update_db(log_id, request.form):
            return "log not found", 404
    except ValueError as exc:
        form_data = dict(current)
        form_data.update(request.form)
        # 保存状態はDBの値を使い、エラー画面でも完了・途中のボタンを保つ。
        form_data["status"] = current["status"]
        return studylog_plus_edit(log_id, form_data, str(exc)), 400
    return redirect("/")


def studylog_plus_delete(log_id):
    if not studylog_plus_delete_db(log_id):
        return "log not found", 404
    return redirect("/")


# Each URL is registered once; no route replacement or monkey patching.
app.add_url_rule("/", endpoint="index", view_func=studylog_plus_index)
app.add_url_rule("/add", endpoint="add", view_func=studylog_plus_add, methods=["POST"])
app.add_url_rule("/edit/<int:log_id>", endpoint="edit", view_func=studylog_plus_edit)
app.add_url_rule("/update/<int:log_id>", endpoint="update", view_func=studylog_plus_update, methods=["POST"])
app.add_url_rule("/delete/<int:log_id>", endpoint="delete_log", view_func=studylog_plus_delete, methods=["POST"])


@app.route("/backup")
def studylog_backup():
    # Online backup captures committed WAL data without changing the source DB.
    with tempfile.TemporaryDirectory(prefix="studylog-backup-") as directory:
        path = database.backup_database(DB_PATH, Path(directory))
        payload = BytesIO(path.read_bytes())
    return send_file(payload, mimetype="application/vnd.sqlite3", as_attachment=True,
                     download_name="studylog-backup.sqlite3", max_age=0)


@app.errorhandler(sqlite3.Error)
def database_error(error):
    app.logger.error("Database operation failed", exc_info=error)
    return render_template("error.html", message="記録の読み込み・保存ができませんでした。入力内容を控え、少し待ってからもう一度お試しください。"), 503


@app.errorhandler(500)
def internal_error(error):
    return render_template("error.html", message="処理を完了できませんでした。少し待ってからもう一度お試しください。"), 500


@app.cli.command("backup-databases")
@click.option("--directory", type=click.Path(path_type=Path), default=None,
              help="保存先。省略するとDBと同じ場所のbackups/。")
def backup_databases_command(directory):
    """Back up the configured DB and any repository-local SQLite files."""
    paths = database.find_databases(BASE_DIR) | {DB_PATH}
    for path in sorted(paths):
        if path.exists():
            click.echo(str(database.backup_database(path, directory)))


@app.cli.command("import-legacy")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--table", type=click.Choice(["study_logs", "logs"]), default="study_logs")
def import_legacy_command(source, table):
    """Explicit, repeatable import; never remove or overwrite source records."""
    try:
        result = database.import_legacy(DB_PATH, source, table)
    except (ValueError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps(result, ensure_ascii=False))


studylog_plus_add_missing_columns()

if __name__ == "__main__":
    app.run(debug=False)
