# =========================================
# 目次
# =========================================
# 【デザイン系】
# U001: HTMLテンプレート
#
# 【その他】
# U101: ライブラリ読み込み
# U102: Flaskアプリ初期化
# U103: DBパス設定
# U104: DB接続関数
# U105: DB初期化
# U106: 数値安全変換
# U107: サマリー取得
#
# 【実行系】
# U201: 一覧ページ
# U202: 学習ログ追加
# U203: 学習ログ削除
# U999: 起動処理
# =========================================


# =========================================
# U101: ライブラリ読み込み
# =========================================
from flask import Flask, request, redirect, url_for, render_template_string, session
import hashlib
import hmac
import math
import os
import secrets
import sqlite3
import time
from pathlib import Path


# =========================================
# U102: Flaskアプリ初期化
# =========================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("STUDYLOG_SECRET_KEY"),
    STUDYLOG_PIN=os.environ.get("STUDYLOG_PIN", ""),
    SESSION_COOKIE_NAME="studylog_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("STUDYLOG_COOKIE_SECURE", "1") != "0",
    SESSION_COOKIE_SAMESITE="Lax",
)


# 4桁PINは公開ソースに保存せず、サーバーの環境変数から読む。
STUDYLOG_LOGIN_HTML = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ロック解除 · studylog</title>
    <style>
        *{box-sizing:border-box;}
        body{margin:0;padding:24px;min-height:100svh;display:grid;place-items:center;
            font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",sans-serif;
            background:#f6f7fb;color:#222;}
        main{width:100%;max-width:380px;background:#fff;border-radius:20px;padding:32px 24px;
            box-shadow:0 8px 24px rgba(0,0,0,.06);}
        h1{margin:0 0 10px;font-size:28px;}
        p{font-size:14px;line-height:1.8;color:#555;}
        label{display:block;font-size:14px;font-weight:700;margin:24px 0 8px;}
        input,button{width:100%;border-radius:12px;padding:14px;font-size:18px;}
        input{border:1px solid #d7dbea;text-align:center;letter-spacing:.45em;}
        input:focus{outline:2px solid #6366f1;outline-offset:2px;}
        button{margin-top:18px;border:0;background:#222;color:white;font-weight:700;cursor:pointer;}
        .error{color:#b91c1c;background:#fff1f2;border-radius:10px;padding:12px;}
    </style>
</head>
<body>
<main>
    <h1>studylog</h1>
    <p>4桁の暗証番号を入力して、学習の記録を開きます。</p>
    {% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
    {% if configured %}
    <form method="post" action="{{ url_for('studylog_login') }}">
        <input type="hidden" name="csrf_token" value="{{ studylog_csrf_token() }}">
        <label for="pin">暗証番号（数字4桁）</label>
        <input id="pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}"
            minlength="4" maxlength="4" autocomplete="current-password" required autofocus
            aria-describedby="pin-help" {% if error %}aria-invalid="true"{% endif %}>
        <p id="pin-help">半角の数字4桁で入力してください。</p>
        <button type="submit">ロック解除</button>
    </form>
    {% endif %}
</main>
</body>
</html>
"""


STUDYLOG_LOCK_HTML = """
<form id="studylog-lock" method="post" action="{{ url_for('studylog_logout') }}" hidden>
    <input type="hidden" name="csrf_token" value="{{ studylog_csrf_token() }}">
</form>
<script>
window.addEventListener('pageshow', function(event) {
    if (event.persisted) window.location.reload();
});
</script>
"""


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


@app.context_processor
def studylog_auth_context():
    return {"studylog_csrf_token": studylog_csrf_token}


@app.before_request
def studylog_require_unlock():
    if not studylog_auth_ready():
        return render_template_string(STUDYLOG_LOGIN_HTML, configured=False,
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
    return response


def studylog_try_pin(candidate):
    # 1人用の軽い制限。Cookieを消しても、別プロセスでも試行回数を共有する。
    now = time.time()
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS studylog_auth_attempts (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            failures INTEGER NOT NULL, last_failure REAL NOT NULL, blocked_until REAL NOT NULL
        )""")
        conn.execute("INSERT OR IGNORE INTO studylog_auth_attempts VALUES (1, 0, 0, 0)")
        failures, last_failure, blocked_until = conn.execute(
            "SELECT failures, last_failure, blocked_until FROM studylog_auth_attempts WHERE id = 1").fetchone()
        if blocked_until > now:
            return False, math.ceil(blocked_until - now)
        if blocked_until or now - last_failure >= 300:
            failures = 0
        accepted = studylog_valid_pin(candidate) and hmac.compare_digest(candidate, app.config["STUDYLOG_PIN"])
        failures = 0 if accepted else failures + 1
        blocked_until = now + 30 if failures >= 5 else 0
        conn.execute("UPDATE studylog_auth_attempts SET failures = ?, last_failure = ?, blocked_until = ? WHERE id = 1",
                     (failures, now, blocked_until))
    return accepted, 30 if blocked_until else 0


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
    response = app.make_response((render_template_string(STUDYLOG_LOGIN_HTML, configured=True, error=error), status))
    if retry_after:
        response.headers["Retry-After"] = str(retry_after)
    return response


@app.route("/logout", methods=["POST"])
def studylog_logout():
    session.clear()
    return redirect(url_for("studylog_login"), code=303)


# =========================================
# U103: DBパス設定
# =========================================
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "studylog.db"


# =========================================
# U001: HTMLテンプレート
# =========================================
HTML_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <title>studylog</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{
            font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",sans-serif;
            background:#f6f7fb;color:#222;margin:0;padding:24px;
        }
        .wrap{max-width:1100px;margin:0 auto;}
        .card{
            background:#fff;border-radius:18px;padding:18px;margin-bottom:18px;
            box-shadow:0 8px 24px rgba(0,0,0,0.06);
        }
        h1{margin:0 0 18px 0;font-size:30px;}
        h2{margin:0 0 14px 0;font-size:22px;}
        h3{margin:0 0 10px 0;font-size:17px;}
        .grid-2,.grid-3,.grid-4{display:grid;gap:14px;}
        .grid-2{grid-template-columns:1fr 1fr;}
        .grid-3{grid-template-columns:1fr 1fr 1fr;}
        .grid-4{grid-template-columns:1fr 1fr 1fr 1fr;}
        label{display:block;font-size:14px;font-weight:700;margin-bottom:6px;}
        input,select,textarea,button{
            width:100%;box-sizing:border-box;border:1px solid #d7dbea;
            border-radius:12px;padding:10px 12px;font-size:14px;background:#fff;
        }
        textarea{min-height:90px;resize:vertical;}
        button{border:none;background:#222;color:#fff;font-weight:700;cursor:pointer;}
        .danger{background:#b91c1c;}
        .pill{
            display:inline-block;background:#eef2ff;color:#334155;
            padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700;
            margin:0 6px 6px 0;
        }
        .summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
        .summary-box{background:#f8f9ff;border-radius:14px;padding:14px;}
        .summary-label{font-size:12px;color:#666;margin-bottom:6px;}
        .summary-value{font-size:24px;font-weight:800;}
        .log{border:1px solid #e8ebf4;border-radius:16px;padding:16px;margin-bottom:14px;}
        .section{margin-top:12px;padding-top:12px;border-top:1px dashed #e5e7eb;}
        .muted{color:#666;font-size:13px;white-space:pre-wrap;}
        .actions{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap;}
        .btn-link{
            display:inline-block;text-decoration:none;background:#111827;color:#fff;
            padding:10px 14px;border-radius:12px;font-size:14px;font-weight:700;
        }
        .inline{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
        .empty{color:#666;padding:10px 0 4px 0;}
        @media (max-width:900px){
            .grid-2,.grid-3,.grid-4,.summary{grid-template-columns:1fr;}
        }
    </style>
</head>
<body>
<div class="wrap">
    <h1>studylog</h1>

    <div class="card">
        <h2>学習ログ</h2>
        <form method="post" action="/add">
            <div class="grid-3">
                <div>
                    <label>学習日</label>
                    <input type="date" name="study_date" value="{{ today }}" required>
                </div>
                <div>
                    <label>カテゴリ</label>
                    <input type="text" name="category">
                </div>
                <div>
                    <label>学習時間（分）</label>
                    <input type="number" name="minutes" min="1" required>
                </div>
            </div>

            <div class="grid-3" style="margin-top:14px;">
                <div>
                    <label>集中度</label>
                    <select name="concentration">
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3" selected>3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                    </select>
                </div>
                <div>
                    <label>理解度</label>
                    <select name="understanding">
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3" selected>3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                    </select>
                </div>
                <div>
                    <label>自信度</label>
                    <select name="confidence">
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3" selected>3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                    </select>
                </div>
            </div>

            <div class="section">
                <h3>学習前</h3>
                <label>今日の目標</label>
                <textarea name="goal"></textarea>
            </div>

            <div class="section">
                <h3>学習後</h3>
                <div class="grid-2">
                    <div>
                        <label>うまくいった理由</label>
                        <textarea name="success_reason"></textarea>
                    </div>
                    <div>
                        <label>うまくいかなかった理由</label>
                        <textarea name="fail_reason"></textarea>
                    </div>
                </div>

                <div style="margin-top:14px;">
                    <label>次回どうするか</label>
                    <textarea name="next_action"></textarea>
                </div>

                <div style="margin-top:14px;">
                    <label>つまずき理由</label>
                    <select name="stumble_reason">
                        <option value="">選択なし</option>
                        <option value="集中できなかった">集中できなかった</option>
                        <option value="難しすぎた">難しすぎた</option>
                        <option value="計画不足">計画不足</option>
                        <option value="時間不足">時間不足</option>
                        <option value="疲れていた">疲れていた</option>
                        <option value="環境が悪かった">環境が悪かった</option>
                        <option value="その他">その他</option>
                    </select>
                </div>

                <div style="margin-top:14px;">
                    <label>メモ</label>
                    <textarea name="memo"></textarea>
                </div>
            </div>

            <div style="margin-top:16px;">
                <button type="submit">保存</button>
            </div>
        </form>
    </div>

    <div class="card">
        <h2>しぼりこみ</h2>
        <form method="get" action="/">
            <div class="grid-4">
                <div>
                    <label>表示範囲</label>
                    <select name="range">
                        <option value="all" {% if filters["range"] == "all" %}selected{% endif %}>全期間</option>
                        <option value="today" {% if filters["range"] == "today" %}selected{% endif %}>今日</option>
                        <option value="week" {% if filters["range"] == "week" %}selected{% endif %}>今週</option>
                        <option value="month" {% if filters["range"] == "month" %}selected{% endif %}>今月</option>
                        <option value="custom" {% if filters["range"] == "custom" %}selected{% endif %}>カスタム</option>
                    </select>
                </div>
                <div>
                    <label>開始日</label>
                    <input type="date" name="start_date" value="{{ filters['start_date'] }}">
                </div>
                <div>
                    <label>終了日</label>
                    <input type="date" name="end_date" value="{{ filters['end_date'] }}">
                </div>
                <div>
                    <label>カテゴリ</label>
                    <select name="category">
                        <option value="">すべて</option>
                        {% for c in categories %}
                            <option value="{{ c }}" {% if filters["category"] == c %}selected{% endif %}>{{ c }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>
            <div class="inline" style="margin-top:14px;">
                <button type="submit">しぼりこむ</button>
                <a href="/" class="btn-link">リセット</a>
            </div>
        </form>
    </div>

    <div class="card">
        <h2>集計</h2>
        <div class="summary">
            <div class="summary-box">
                <div class="summary-label">件数</div>
                <div class="summary-value">{{ summary["count"] }}</div>
            </div>
            <div class="summary-box">
                <div class="summary-label">合計学習時間</div>
                <div class="summary-value">{{ summary["total_minutes"] }}分</div>
            </div>
            <div class="summary-box">
                <div class="summary-label">平均集中度</div>
                <div class="summary-value">{{ summary["avg_concentration"] }}</div>
            </div>
            <div class="summary-box">
                <div class="summary-label">平均理解度</div>
                <div class="summary-value">{{ summary["avg_understanding"] }}</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>ログ一覧</h2>
        {% if logs %}
            {% for log in logs %}
                <div class="log">
                    <div>
                        <span class="pill">{{ log["study_date"] }}</span>
                        <span class="pill">{{ log["category"] or "カテゴリ未設定" }}</span>
                        <span class="pill">{{ log["minutes"] }}分</span>
                        <span class="pill">集中 {{ log["concentration"] }}</span>
                        <span class="pill">理解 {{ log["understanding"] }}</span>
                        <span class="pill">自信 {{ log["confidence"] or 3 }}</span>
                    </div>

                    <div class="section">
                        <strong>目標</strong>
                        <div class="muted">{{ log["goal"] or "なし" }}</div>
                    </div>
                    <div class="section">
                        <strong>うまくいった理由</strong>
                        <div class="muted">{{ log["success_reason"] or "なし" }}</div>
                    </div>
                    <div class="section">
                        <strong>うまくいかなかった理由</strong>
                        <div class="muted">{{ log["fail_reason"] or "なし" }}</div>
                    </div>
                    <div class="section">
                        <strong>次回どうするか</strong>
                        <div class="muted">{{ log["next_action"] or "なし" }}</div>
                    </div>
                    <div class="section">
                        <strong>自由メモ</strong>
                        <div class="muted">{{ log["memo"] or "なし" }}</div>
                    </div>

                    <div class="actions">
                        <a class="btn-link" href="/edit/{{ log['id'] }}">編集</a>
                        <form method="post" action="/delete/{{ log['id'] }}">
                            <button type="submit" class="danger">削除</button>
                        </form>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <div class="empty">まだログがありません。</div>
        {% endif %}
    </div>
</div>
</body>
</html>
"""


# =========================================
# U104: DB接続関数
# =========================================
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =========================================
# U105: DB初期化
# =========================================
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS study_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_date TEXT NOT NULL,
            goal TEXT,
            task TEXT,
            minutes INTEGER NOT NULL,
            focus_score INTEGER NOT NULL,
            understanding_score INTEGER NOT NULL,
            reflection TEXT,
            next_action TEXT,
            created_at TEXT DEFAULT (datetime('now', '+9 hours'))
        )
    """)

    conn.commit()
    conn.close()


# =========================================
# U106: 数値安全変換
# =========================================
def safe_int(value, default=0):
    try:
        return int(value)
    except:
        return default


# =========================================
# U107: サマリー取得
# =========================================
def get_summary():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COALESCE(SUM(minutes), 0) AS total_minutes,
            COALESCE(ROUND(AVG(focus_score), 1), 0) AS avg_focus,
            COALESCE(ROUND(AVG(understanding_score), 1), 0) AS avg_understanding
        FROM study_logs
        WHERE substr(study_date, 1, 7) = strftime('%Y-%m', 'now', '+9 hours')
    """)

    row = cur.fetchone()
    conn.close()

    return {
        "total_minutes": row["total_minutes"],
        "avg_focus": row["avg_focus"],
        "avg_understanding": row["avg_understanding"],
    }


# =========================================
# U201: 一覧ページ
# =========================================
@app.route("/")
def index():
    add_missing_columns()

    filters = get_filter_values()

    where_parts = []
    params = []

    if filters["start_date"]:
        where_parts.append("study_date >= ?")
        params.append(filters["start_date"])

    if filters["end_date"]:
        where_parts.append("study_date <= ?")
        params.append(filters["end_date"])

    if filters["category"]:
        where_parts.append("category = ?")
        params.append(filters["category"])

    where_sql = ""
    if where_parts:
        where_sql = "WHERE " + " AND ".join(where_parts)

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    logs = conn.execute(
        f"SELECT * FROM logs {where_sql} ORDER BY study_date DESC, id DESC",
        params
    ).fetchall()

    summary_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS count,
            COALESCE(SUM(minutes), 0) AS total_minutes,
            ROUND(COALESCE(AVG(concentration), 0), 1) AS avg_concentration,
            ROUND(COALESCE(AVG(understanding), 0), 1) AS avg_understanding
        FROM logs
        {where_sql}
        """,
        params
    ).fetchone()

    conn.close()

    summary = {
        "count": summary_row["count"],
        "total_minutes": summary_row["total_minutes"],
        "avg_concentration": summary_row["avg_concentration"],
        "avg_understanding": summary_row["avg_understanding"]
    }

    return render_template(
        "index.html",
        logs=logs,
        summary=summary,
        filters=filters,
        categories=get_categories(),
        today=date.today().isoformat()
    )


# =========================================
# U202: 学習ログ追加
# =========================================
@app.route("/add", methods=["POST"])
def add():
    add_missing_columns()

    study_date = request.form.get("study_date", "")
    category = request.form.get("category", "").strip()
    minutes = int(request.form.get("minutes", 0))
    concentration = int(request.form.get("concentration", 3))
    understanding = int(request.form.get("understanding", 3))
    confidence = int(request.form.get("confidence", 3))
    goal = request.form.get("goal", "").strip()
    success_reason = request.form.get("success_reason", "").strip()
    fail_reason = request.form.get("fail_reason", "").strip()
    next_action = request.form.get("next_action", "").strip()
    stumble_reason = request.form.get("stumble_reason", "").strip()
    memo = request.form.get("memo", "").strip()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    conn.execute("""
        INSERT INTO logs (
            study_date,
            category,
            minutes,
            concentration,
            understanding,
            confidence,
            goal,
            success_reason,
            fail_reason,
            next_action,
            stumble_reason,
            memo,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        study_date,
        category,
        minutes,
        concentration,
        understanding,
        confidence,
        goal,
        success_reason,
        fail_reason,
        next_action,
        stumble_reason,
        memo,
        created_at
    ))
    conn.commit()
    conn.close()

    return redirect(url_for("index"))


# =========================================
# U203: 学習ログ削除
# =========================================
@app.route("/delete/<int:log_id>", methods=["POST"])
def delete_log(log_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM study_logs WHERE id = ?", (log_id,))

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

# =========================================
# 追記専用: studylog 中くらい改良パック
# ※ これを app.run(...) の前に貼る
# =========================================

# -----------------------------------------
# U901: 追加import
# -----------------------------------------
from datetime import datetime, date, timedelta, timezone
from contextlib import closing
from collections import defaultdict, deque
import math
from flask import render_template_string

# 追加と編集で同じ入力欄を使い、保存時の入力エラーでも値を残す。
STUDYLOG_PLUS_FORM_HTML = """
{% macro field_value(name) -%}
    {{ form_data.get(name) if form_data.get(name) is not none else '' }}
{%- endmacro %}
{% macro rating(name, label) -%}
    <div>
        <label for="{{ name }}">{{ label }}（1〜5）</label>
        <select id="{{ name }}" name="{{ name }}">
            <option value="">未入力</option>
            {% for i in [1,2,3,4,5] %}
                <option value="{{ i }}" {% if form_data.get(name)|string == i|string %}selected{% endif %}>{{ i }}</option>
            {% endfor %}
        </select>
    </div>
{%- endmacro %}
{% if error %}
    <p role="alert" style="color:#991b1b;background:#fef2f2;padding:12px;border-radius:12px;">{{ error }}</p>
{% endif %}
{% if plan_notice %}
    <p role="status" style="background:#eef2ff;padding:12px;border-radius:12px;">{{ plan_notice }} 内容を調整し、「学習前を保存」で新しい記録として保存できます。</p>
{% endif %}
<p class="muted">学習前だけでも保存できます。一覧の「学習後を記録」から、同じログに結果を追記できます。</p>
{% if is_edit %}
    <p>状態：<strong>{{ '学習中' if form_data.get('status') == 'in_progress' else '学習完了' }}</strong></p>
{% endif %}
<form method="post" action="{{ form_action }}">
    <input type="hidden" name="csrf_token" value="{{ studylog_csrf_token() }}">
    <div class="grid-2">
        <div>
            <label for="study_date">学習日</label>
            <input id="study_date" type="date" name="study_date" value="{{ field_value('study_date') }}" required>
        </div>
        <div>
            <label for="category">カテゴリ</label>
            <input id="category" type="text" name="category" value="{{ field_value('category') }}" placeholder="例: 卒論">
        </div>
    </div>
    <div style="margin-top:14px;">
        <label for="task">学習内容</label>
        <textarea id="task" name="task" placeholder="例: 第2章を読み、要点をまとめる">{{ field_value('task') }}</textarea>
    </div>

    <div class="section">
        <h3>学習前</h3>
        <label for="goal">今日の目標</label>
        <textarea id="goal" name="goal">{{ field_value('goal') }}</textarea>
        <div class="grid-2" style="margin-top:14px;">
            <div>
                <label for="planned_minutes">予定学習時間（分）</label>
                <input id="planned_minutes" type="number" name="planned_minutes" min="1" step="1" value="{{ field_value('planned_minutes') }}">
            </div>
            <div>
                <label for="strategy">学習方法・作戦</label>
                <input id="strategy" type="text" name="strategy" value="{{ field_value('strategy') }}" placeholder="例: 25分ずつ区切って取り組む">
            </div>
        </div>
        <div class="grid-3" style="margin-top:14px;">
            {{ rating('before_concentration', '学習前の集中できそう度') }}
            {{ rating('before_understanding', '学習前の理解度') }}
            {{ rating('before_confidence', '学習前の自信度') }}
        </div>
        <div style="margin-top:14px;">
            <label for="before_test_score">学習前の確認テスト（0〜100点換算・任意）</label>
            <input id="before_test_score" type="number" name="before_test_score" min="0" max="100" step="any" value="{{ field_value('before_test_score') }}">
        </div>
    </div>

    <div class="section">
        <h3>学習後</h3>
        <p class="muted">学習が終わったら入力してください。未入力の評価は空欄のまま保存されます。</p>
        <label for="minutes">実際の学習時間（分・学習完了時は必須）</label>
        <input id="minutes" type="number" name="minutes" min="1" step="1" value="{{ field_value('minutes') }}">
        <div class="grid-3" style="margin-top:14px;">
            {{ rating('concentration', '学習後の集中度') }}
            {{ rating('understanding', '学習後の理解度') }}
            {{ rating('confidence', '学習後の自信度') }}
        </div>
        <div style="margin-top:14px;">
            <label for="after_test_score">学習後の確認テスト（0〜100点換算・任意）</label>
            <input id="after_test_score" type="number" name="after_test_score" min="0" max="100" step="any" value="{{ field_value('after_test_score') }}">
        </div>
        <div class="grid-2" style="margin-top:14px;">
            <div>
                <label for="success_reason">うまくいった理由</label>
                <textarea id="success_reason" name="success_reason">{{ field_value('success_reason') }}</textarea>
            </div>
            <div>
                <label for="fail_reason">うまくいかなかった理由</label>
                <textarea id="fail_reason" name="fail_reason">{{ field_value('fail_reason') }}</textarea>
            </div>
        </div>
        <div style="margin-top:14px;">
            <label for="next_action">次回どうするか</label>
            <textarea id="next_action" name="next_action">{{ field_value('next_action') }}</textarea>
        </div>
        <div style="margin-top:14px;">
            <label for="stumble_reason">つまずき理由</label>
            <select id="stumble_reason" name="stumble_reason">
                {% for item in stumble_options %}
                    <option value="{{ item }}" {% if form_data.get('stumble_reason') == item %}selected{% endif %}>{{ item or '選択なし' }}</option>
                {% endfor %}
            </select>
        </div>
        <div style="margin-top:14px;">
            <label for="memo">メモ</label>
            <textarea id="memo" name="memo">{{ field_value('memo') }}</textarea>
        </div>
    </div>
    <div class="grid-2" style="margin-top:16px;">
        {% if not is_edit or form_data.get('status') == 'in_progress' %}
            <button type="submit" name="save_stage" value="before">{{ '途中保存' if is_edit else '学習前を保存' }}</button>
        {% endif %}
        <button type="submit" name="save_stage" value="after">{{ '更新' if is_edit and form_data.get('status') == 'completed' else '学習後まで保存' }}</button>
    </div>
</form>
"""

# -----------------------------------------
# U902: 追加テンプレート（一覧）
# -----------------------------------------
STUDYLOG_PLUS_INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <title>studylog</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{
            font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",sans-serif;
            background:#f6f7fb;color:#222;margin:0;padding:24px;
        }
        .wrap{max-width:1100px;margin:0 auto;}
        .card{
            background:#fff;border-radius:18px;padding:18px;margin-bottom:18px;
            box-shadow:0 8px 24px rgba(0,0,0,0.06);
        }
        h1{margin:0 0 18px 0;font-size:30px;}
        h2{margin:0 0 14px 0;font-size:22px;}
        h3{margin:0 0 10px 0;font-size:17px;}
        .grid-2,.grid-3,.grid-4{
            display:grid;gap:14px;
        }
        .grid-2{grid-template-columns:1fr 1fr;}
        .grid-3{grid-template-columns:1fr 1fr 1fr;}
        .grid-4{grid-template-columns:1fr 1fr 1fr 1fr;}
        label{
            display:block;font-size:14px;font-weight:700;margin-bottom:6px;
        }
        input,select,textarea,button{
            width:100%;box-sizing:border-box;border:1px solid #d7dbea;
            border-radius:12px;padding:10px 12px;font-size:14px;background:#fff;
        }
        textarea{min-height:90px;resize:vertical;}
        button{
            border:none;background:#222;color:#fff;font-weight:700;cursor:pointer;
        }
        .danger{background:#b91c1c;}
        .pill{
            display:inline-block;background:#eef2ff;color:#334155;
            padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700;
            margin:0 6px 6px 0;
        }
        .summary{
            display:grid;grid-template-columns:repeat(4,1fr);gap:12px;
        }
        .summary-box{
            background:#f8f9ff;border-radius:14px;padding:14px;
        }
        .summary-label{font-size:12px;color:#666;margin-bottom:6px;}
        .summary-value{font-size:24px;font-weight:800;}
        .log{
            border:1px solid #e8ebf4;border-radius:16px;padding:16px;margin-bottom:14px;
        }
        .section{
            margin-top:12px;padding-top:12px;border-top:1px dashed #e5e7eb;
        }
        .muted{color:#666;font-size:13px;white-space:pre-wrap;}
        .actions{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap;}
        .btn-link{
            display:inline-block;text-decoration:none;background:#111827;color:#fff;
            padding:10px 14px;border-radius:12px;font-size:14px;font-weight:700;
        }
        .inline{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
        .empty{color:#666;padding:10px 0 4px 0;}
        @media (max-width:900px){
            .grid-2,.grid-3,.grid-4,.summary{grid-template-columns:1fr;}
        }
    </style>
</head>
<body>
<div class="wrap">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px;">
        <h1 style="margin:0;">studylog</h1>
        <button type="submit" form="studylog-lock" style="width:auto;">ロック</button>
    </div>

    <div class="card" id="studylog-add">
        <h2>学習ログを追加</h2>
""" + STUDYLOG_PLUS_FORM_HTML + """
    </div>

    <div class="card">
        <h2>しぼりこみ</h2>
        <form method="get" action="/">
            <div class="grid-4">
                <div>
                    <label>表示範囲</label>
                    <select name="range">
                        <option value="all" {% if filters["range"] == "all" %}selected{% endif %}>全期間</option>
                        <option value="today" {% if filters["range"] == "today" %}selected{% endif %}>今日</option>
                        <option value="week" {% if filters["range"] == "week" %}selected{% endif %}>今週</option>
                        <option value="month" {% if filters["range"] == "month" %}selected{% endif %}>今月</option>
                        <option value="custom" {% if filters["range"] == "custom" %}selected{% endif %}>カスタム</option>
                    </select>
                </div>
                <div>
                    <label>開始日</label>
                    <input type="date" name="start_date" value="{{ filters['start_date'] }}">
                </div>
                <div>
                    <label>終了日</label>
                    <input type="date" name="end_date" value="{{ filters['end_date'] }}">
                </div>
                <div>
                    <label>カテゴリ</label>
                    <select name="category">
                        <option value="">すべて</option>
                        {% for c in categories %}
                            <option value="{{ c }}" {% if filters["category"] == c %}selected{% endif %}>{{ c }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>
            <div class="inline" style="margin-top:14px;">
                <button type="submit">しぼりこむ</button>
                <a href="/" class="btn-link">リセット</a>
            </div>
        </form>
    </div>

    <div class="card">
        <h2>集計</h2>
        <p class="muted">完了 {{ summary["completed_count"] }}件 / 学習中 {{ summary["in_progress_count"] }}件。時間・平均は学習完了の記録を集計します。</p>
        <div class="summary">
            <div class="summary-box">
                <div class="summary-label">件数</div>
                <div class="summary-value">{{ summary["count"] }}</div>
            </div>
            <div class="summary-box">
                <div class="summary-label">合計学習時間</div>
                <div class="summary-value">{{ summary["total_minutes"] }}分</div>
            </div>
            <div class="summary-box">
                <div class="summary-label">平均集中度</div>
                <div class="summary-value">{{ summary["avg_concentration"] }}</div>
            </div>
            <div class="summary-box">
                <div class="summary-label">平均理解度</div>
                <div class="summary-value">{{ summary["avg_understanding"] }}</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>ログ一覧</h2>

        {% if logs %}
            {% for log in logs %}
                <div class="log">
                    <div>
                        <span class="pill">{{ log["study_date"] }}</span>
                        <span class="pill">{{ log["category"] or "カテゴリ未設定" }}</span>
                        <span class="pill">{{ '学習中' if log['status'] == 'in_progress' else '学習完了' }}</span>
                        {% if log['status'] == 'completed' %}
                            <span class="pill">{{ log["minutes"] }}分</span>
                            <span class="pill">集中 {{ log["concentration"] if log["concentration"] is not none else '未記録' }}</span>
                            <span class="pill">理解 {{ log["understanding"] if log["understanding"] is not none else '未記録' }}</span>
                            <span class="pill">自信 {{ log["confidence"] if log["confidence"] is not none else '未記録' }}</span>
                        {% endif %}
                        {% if log["stumble_reason"] %}
                            <span class="pill">つまずき: {{ log["stumble_reason"] }}</span>
                        {% endif %}
                    </div>

                    <div class="section">
                        <strong>学習内容</strong>
                        <div class="muted">{{ log["task"] or "未記録" }}</div>
                    </div>

                    <div class="section">
                        <strong>学習前の目標</strong>
                        <div class="muted">{{ log["goal"] or "なし" }}</div>
                        <div class="muted">予定時間: {{ (log["planned_minutes"]|string + '分') if log["planned_minutes"] is not none else '未記録' }}</div>
                        <div class="muted">学習方法: {{ log["strategy"] or "未記録" }}</div>
                    </div>

                    {% set analysis = analyses[log['id']] %}
                    <div class="section analysis" data-log-id="{{ log['id'] }}" data-state="{{ analysis['state'] }}">
                        <h3>状態分類・過去ログとの比較</h3>
                        <span class="pill">{{ analysis['label'] }}</span>
                        <div class="muted">{{ analysis['reason'] }}</div>
                        <div class="muted">支援の方向: {{ analysis['support_label'] }}</div>
                        <div>{{ analysis['action'] }}</div>
                        <details style="margin-top:10px;">
                            <summary>比較の内訳（同じカテゴリの過去{{ analysis['history_count'] }}件）</summary>
                            <p class="muted">{{ analysis['evidence'] }}。入力記録から見た暫定的な傾向です。</p>
                            <div style="overflow-x:auto;">
                                <table style="width:100%;min-width:390px;text-align:left;border-spacing:8px;">
                                    <caption>学習後の値と直前5件以内の平均</caption>
                                    <thead><tr><th scope="col">項目</th><th scope="col">今回</th><th scope="col">過去平均</th><th scope="col">差</th><th scope="col">比較数</th></tr></thead>
                                    <tbody>
                                    {% for metric in analysis['metrics'] %}
                                        <tr>
                                            <th scope="row">{{ metric['label'] }}</th>
                                            <td>{{ ('%.2f'|format(metric['current'])) + metric['unit'] if metric['current'] is not none else '未記録' }}</td>
                                            <td>{{ ('%.2f'|format(metric['baseline'])) + metric['unit'] if metric['baseline'] is not none else '比較なし' }}</td>
                                            <td>{{ ('%+.2f'|format(metric['delta'])) + metric['unit'] if metric['delta'] is not none else '—' }}</td>
                                            <td>{{ metric['count'] }}件</td>
                                        </tr>
                                    {% endfor %}
                                    </tbody>
                                </table>
                            </div>
                            {% if analysis['history_ids'] %}
                                <div class="muted">比較したログ（新しい順）:
                                    {% for history_id in analysis['history_ids'] %}<a href="/edit/{{ history_id }}">#{{ history_id }}</a>{% if not loop.last %} / {% endif %}{% endfor %}
                                </div>
                            {% endif %}
                            <p class="muted">同じカテゴリの完了ログだけを、学習日と同日の登録順で比較します。表示の絞り込みは基準に影響しません。学習時間の長短だけでは良否を判定しません。</p>
                            <strong>個人別の判定基準</strong>
                            <p class="muted">過去との差は記録数に応じて弱め、3件以上で傾向を判定します。テストと自信度の比較は参考換算です。テストの内容・難しさの違いも振り返ってください。</p>
                        </details>
                    </div>

                    {% set plan = plans[log['id']] %}
                    <div class="section next-plan" data-log-id="{{ log['id'] }}" data-plan-version="{{ plan['version'] }}">
                        <h3>次回計画の自動補正</h3>
                        {% if plan['enabled'] %}
                            <div><strong>次回の予定時間: {{ plan['minutes'] }}分</strong>（基準 {{ plan['base_minutes'] }}分）</div>
                            <div class="muted">目標: {{ plan['goal'] }}</div>
                            <div class="muted">学習方法: {{ plan['strategy'] }}</div>
                            <details style="margin-top:10px;">
                                <summary>補正の理由</summary>
                                <p class="muted">{{ plan['reason'] }}</p>
                                <p class="muted">元の記録は保持し、表示時に再計算します。次の学習へ引き継いで保存した内容は、新しいログに残ります。</p>
                            </details>
                            <a class="btn-link" style="margin-top:10px;" href="/?plan_from={{ log['id'] }}#studylog-add">この計画で次の学習を準備</a>
                        {% else %}
                            <p class="muted">{{ plan['reason'] }}</p>
                        {% endif %}
                    </div>

                    <div class="section">
                        <strong>学習前 → 学習後</strong>
                        <div class="muted">集中できそう度 → 集中度: {{ log['before_concentration'] if log['before_concentration'] is not none else '未記録' }} → {{ log['concentration'] if log['status'] == 'completed' and log['concentration'] is not none else '未記録' }}</div>
                        {% for before, after, label, unit in [
                            ('before_understanding', 'understanding', '理解度', ''),
                            ('before_confidence', 'confidence', '自信度', ''),
                            ('before_test_score', 'after_test_score', '確認テスト', '点')
                        ] %}
                            <div class="muted">{{ label }}: {{ log[before] if log[before] is not none else '未記録' }} → {{ log[after] if log['status'] == 'completed' and log[after] is not none else '未記録' }}{% if log['status'] == 'completed' and log[before] is not none and log[after] is not none %}（変化 {{ '%+g'|format(log[after] - log[before]) }}{{ unit }}）{% endif %}</div>
                        {% endfor %}
                        {% if log['status'] == 'completed' and log['planned_minutes'] is not none and log['minutes'] is not none %}
                            <div class="muted">学習時間: {{ log['planned_minutes'] }}分 → {{ log['minutes'] }}分（予定との差 {{ '%+d'|format(log['minutes'] - log['planned_minutes']) }}分）</div>
                        {% endif %}
                    </div>

                    <div class="section">
                        <strong>うまくいった理由</strong>
                        <div class="muted">{{ log["success_reason"] or "なし" }}</div>
                    </div>

                    <div class="section">
                        <strong>うまくいかなかった理由</strong>
                        <div class="muted">{{ log["fail_reason"] or "なし" }}</div>
                    </div>

                    <div class="section">
                        <strong>次回どうするか</strong>
                        <div class="muted">{{ log["next_action"] or "なし" }}</div>
                    </div>

                    <div class="section">
                        <strong>メモ</strong>
                        <div class="muted">{{ log["memo"] or "なし" }}</div>
                    </div>

                    <div class="actions">
                        <a class="btn-link" href="/edit/{{ log['id'] }}">{{ '学習後を記録' if log['status'] == 'in_progress' else '編集' }}</a>
                        <form method="post" action="/delete/{{ log['id'] }}" onsubmit="return confirm('このログを削除しますか？');">
                            <input type="hidden" name="csrf_token" value="{{ studylog_csrf_token() }}">
                            <button type="submit" class="danger">削除</button>
                        </form>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <div class="empty">まだログがありません。</div>
        {% endif %}
    </div>
</div>
""" + STUDYLOG_LOCK_HTML + """
</body>
</html>
"""

# -----------------------------------------
# U903: 追加テンプレート（編集）
# -----------------------------------------
STUDYLOG_PLUS_EDIT_HTML = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <title>studylog 編集</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{
            font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",sans-serif;
            background:#f6f7fb;color:#222;margin:0;padding:24px;
        }
        .wrap{max-width:900px;margin:0 auto;}
        .card{
            background:#fff;border-radius:18px;padding:18px;
            box-shadow:0 8px 24px rgba(0,0,0,0.06);
        }
        h1{margin:0 0 18px 0;}
        h3{margin:0 0 10px 0;}
        .grid-2,.grid-3{display:grid;gap:14px;}
        .grid-2{grid-template-columns:1fr 1fr;}
        .grid-3{grid-template-columns:1fr 1fr 1fr;}
        label{display:block;font-size:14px;font-weight:700;margin-bottom:6px;}
        input,select,textarea,button{
            width:100%;box-sizing:border-box;border:1px solid #d7dbea;
            border-radius:12px;padding:10px 12px;font-size:14px;background:#fff;
        }
        textarea{min-height:90px;resize:vertical;}
        button{border:none;background:#222;color:#fff;font-weight:700;cursor:pointer;}
        .section{margin-top:16px;padding-top:14px;border-top:1px dashed #e5e7eb;}
        .back{display:inline-block;margin-top:14px;color:#374151;text-decoration:none;font-weight:700;}
        .muted{color:#666;font-size:13px;white-space:pre-wrap;}
        @media (max-width:900px){.grid-2,.grid-3{grid-template-columns:1fr;}}
    </style>
</head>
<body>
<div class="wrap">
    <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px;">
            <h1 style="margin:0;">ログを編集</h1>
            <button type="submit" form="studylog-lock" style="width:auto;">ロック</button>
        </div>

""" + STUDYLOG_PLUS_FORM_HTML + """

        <a class="back" href="/">← 一覧へ戻る</a>
    </div>
</div>
""" + STUDYLOG_LOCK_HTML + """
</body>
</html>
"""

# -----------------------------------------
# U904: DB名取得
# -----------------------------------------
STUDYLOG_PLUS_DB_NAME = DB_PATH

# -----------------------------------------
# U905: 接続関数
# -----------------------------------------
def studylog_plus_get_conn():
    conn = sqlite3.connect(STUDYLOG_PLUS_DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# -----------------------------------------
# U906: 不足カラム追加
# -----------------------------------------
def studylog_plus_add_missing_columns():
    conn = studylog_plus_get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_date TEXT,
            minutes INTEGER,
            concentration INTEGER,
            understanding INTEGER,
            memo TEXT,
            created_at TEXT
        )
    """)

    existing = conn.execute("PRAGMA table_info(logs)").fetchall()
    existing_names = {row["name"] for row in existing}

    needed = {
        "category": "TEXT",
        "goal": "TEXT",
        "confidence": "INTEGER DEFAULT 3",
        "success_reason": "TEXT",
        "fail_reason": "TEXT",
        "next_action": "TEXT",
        "stumble_reason": "TEXT",
        "task": "TEXT",
        "planned_minutes": "INTEGER",
        "strategy": "TEXT",
        "before_concentration": "INTEGER",
        "before_understanding": "INTEGER",
        "before_confidence": "INTEGER",
        "before_test_score": "REAL",
        "after_test_score": "REAL",
        "status": "TEXT NOT NULL DEFAULT 'completed'",
        "before_saved_at": "TEXT",
        "after_saved_at": "TEXT",
        "updated_at": "TEXT"
    }

    for col_name, col_type in needed.items():
        if col_name not in existing_names:
            conn.execute(f"ALTER TABLE logs ADD COLUMN {col_name} {col_type}")

    conn.commit()
    conn.close()

# -----------------------------------------
# U907: フィルタ日付
# -----------------------------------------
def studylog_plus_get_dates(range_name, start_date_str, end_date_str):
    today = date.today()

    if range_name == "today":
        return today.isoformat(), today.isoformat()

    if range_name == "week":
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat(), today.isoformat()

    if range_name == "month":
        first_day = today.replace(day=1)
        return first_day.isoformat(), today.isoformat()

    if range_name == "custom":
        return start_date_str or "", end_date_str or ""

    return "", ""

# -----------------------------------------
# U908: WHERE句組み立て
# -----------------------------------------
def studylog_plus_build_filters():
    range_name = request.args.get("range", "all")
    category = request.args.get("category", "").strip()
    start_date_in = request.args.get("start_date", "")
    end_date_in = request.args.get("end_date", "")

    start_date, end_date = studylog_plus_get_dates(range_name, start_date_in, end_date_in)

    where_parts = []
    params = []

    if start_date:
        where_parts.append("study_date >= ?")
        params.append(start_date)

    if end_date:
        where_parts.append("study_date <= ?")
        params.append(end_date)

    if category:
        where_parts.append("category = ?")
        params.append(category)

    where_sql = ""
    if where_parts:
        where_sql = " WHERE " + " AND ".join(where_parts)

    filters = {
        "range": range_name,
        "category": category,
        "start_date": start_date,
        "end_date": end_date
    }

    return where_sql, params, filters

# -----------------------------------------
# U909: 一覧データ
# -----------------------------------------
def studylog_plus_get_logs(where_sql="", params=None):
    if params is None:
        params = []

    conn = studylog_plus_get_conn()
    rows = conn.execute(
        f"SELECT * FROM logs {where_sql} ORDER BY study_date DESC, id DESC",
        params
    ).fetchall()
    conn.close()
    return rows

# -----------------------------------------
# U910: 集計
# -----------------------------------------
def studylog_plus_get_summary(where_sql="", params=None):
    if params is None:
        params = []

    conn = studylog_plus_get_conn()
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
    conn.close()

    return {
        "count": row["count"],
        "completed_count": row["completed_count"],
        "in_progress_count": row["in_progress_count"],
        "total_minutes": row["total_minutes"],
        "avg_concentration": row["avg_concentration"],
        "avg_understanding": row["avg_understanding"]
    }

# -----------------------------------------
# U911: カテゴリ一覧
# -----------------------------------------
def studylog_plus_get_categories():
    conn = studylog_plus_get_conn()
    rows = conn.execute("""
        SELECT DISTINCT category
        FROM logs
        WHERE category IS NOT NULL AND TRIM(category) != ''
        ORDER BY category
    """).fetchall()
    conn.close()
    return [row["category"] for row in rows]

# -----------------------------------------
# U912: 単一取得
# -----------------------------------------
def studylog_plus_get_log(log_id):
    conn = studylog_plus_get_conn()
    row = conn.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
    conn.close()
    return row

# -----------------------------------------
# U924: 状態分類・過去ログ比較（DBを書き換えない純粋な計算）
# -----------------------------------------
STUDYLOG_ANALYSIS_VERSION = "state-v1"
STUDYLOG_HISTORY_LIMIT = 5
STUDYLOG_MIN_HISTORY = 3
STUDYLOG_CHANGE_THRESHOLD = 1.0
STUDYLOG_GAP_THRESHOLD = 1.5
STUDYLOG_ANALYSIS_METRICS = (
    ("minutes", "学習時間", "分", 1, 2147483647),
    ("concentration", "集中度", "", 1, 5),
    ("understanding", "理解度", "", 1, 5),
    ("confidence", "自信度", "", 1, 5),
    ("after_test_score", "確認テスト", "点", 0, 100),
)
STUDYLOG_SUPPORT_TYPES = {
    "visualization": "学習状況の可視化",
    "awareness": "自己認識の促進",
    "opportunity": "学習機会の提供",
    "feedback": "個別のフィードバック・介入",
}


def studylog_analysis_number(log, field, minimum, maximum):
    """未測定・範囲外の旧データを0や3で埋めない。"""
    raw = log.get(field)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        return None
    if field != "after_test_score" and not value.is_integer():
        return None
    return value


def studylog_analyze_log(log, history):
    """同カテゴリの直前5件を受け取る。historyの順序は古い→新しい。"""
    log = dict(log)
    completed = log.get("status") == "completed"
    metrics = []
    for field, label, unit, minimum, maximum in STUDYLOG_ANALYSIS_METRICS:
        current = studylog_analysis_number(log, field, minimum, maximum) if completed else None
        previous = [studylog_analysis_number(row, field, minimum, maximum) for row in history]
        previous = [value for value in previous if value is not None]
        count = len(previous)
        baseline = math.fsum(previous) / count if count else None
        delta = current - baseline if current is not None and baseline is not None else None
        # 少数記録の差を弱める。これは確率や統計的な信頼区間ではない。
        weight = min(count / STUDYLOG_HISTORY_LIMIT, 1)
        metrics.append({
            "key": field, "label": label, "unit": unit, "current": current,
            "baseline": baseline, "delta": delta, "count": count,
            "weight": weight, "adjusted_delta": delta * weight if delta is not None else None,
        })
    by_key = {metric["key"]: metric for metric in metrics}
    ratings = [by_key[key] for key in ("concentration", "understanding", "confidence")]
    current_count = sum(metric["current"] is not None for metric in ratings)
    comparable_count = min(metric["count"] if metric["current"] is not None else 0 for metric in ratings)
    evidence = ("比較データ充足（各5件）" if comparable_count >= 5 else
                "比較データ一部あり（各3件以上）" if comparable_count >= STUDYLOG_MIN_HISTORY else
                "参考判定（比較データが少ない／未測定あり）")
    result = {
        "version": STUDYLOG_ANALYSIS_VERSION,
        "state": "insufficient", "label": "判定保留", "reason": "学習後の集中度・理解度・自信度を記録すると、状態の傾向を確認できます。",
        "support_type": "visualization", "action": "未記録の評価を入力し、次の学習と比べてみましょう。",
        "metrics": metrics, "history_ids": [row["id"] for row in reversed(history)],
        "history_count": len(history), "evidence": evidence, "comparable_count": comparable_count,
        "gap": None, "gap_basis": None,
    }

    def choose(state, label, reason, support_type, action):
        result.update(state=state, label=label, reason=reason, support_type=support_type, action=action)

    def fell(key):
        metric = by_key[key]
        return (metric["count"] >= STUDYLOG_MIN_HISTORY and metric["adjusted_delta"] is not None
                and metric["adjusted_delta"] <= -STUDYLOG_CHANGE_THRESHOLD)

    def rose(key):
        metric = by_key[key]
        return (metric["count"] >= STUDYLOG_MIN_HISTORY and metric["adjusted_delta"] is not None
                and metric["adjusted_delta"] >= STUDYLOG_CHANGE_THRESHOLD)

    def reason_for(key):
        metric = by_key[key]
        if metric["current"] is not None and metric["current"] <= 2:
            return f"今回の{metric['label']}が{metric['current']:g}/5です。"
        return f"{metric['label']}が過去平均から{metric['delta']:+.2f}（比較{metric['count']}件）変化し、記録数で補正しても低下が見られます。"

    if not completed:
        choose("pending", "学習後の記録待ち", "学習前だけの記録は状態判定と過去の基準値から除外します。",
               "visualization", "学習が終わったら、同じログに学習後の結果を保存してください。")
    else:
        focus, understanding, confidence = (metric["current"] for metric in ratings)
        score = by_key["after_test_score"]["current"]
        # 0〜100点を1〜5へ線形換算した試作上の参考指標。能力の測定尺度ではない。
        reference = 1 + score / 25 if score is not None else understanding
        if confidence is not None and reference is not None:
            result["gap"] = confidence - reference
            result["gap_basis"] = "確認テスト（1〜5に参考換算）" if score is not None else "理解度の自己評価"
        if result["gap"] is not None and abs(result["gap"]) >= STUDYLOG_GAP_THRESHOLD:
            direction = "高め" if result["gap"] > 0 else "低め"
            choose("calibration", f"自己評価のずれ候補（自信が{direction}）",
                   f"自信度が{result['gap_basis']}より{abs(result['gap']):.2f}段階{direction}です。",
                   "awareness", "解けた問題・間違えた問題と自信のつけ方を見比べてみましょう。")
        elif (understanding is not None and understanding <= 2) or fell("understanding"):
            choose("understanding", "理解の停滞候補", reason_for("understanding"),
                   "opportunity", "つまずいた範囲を小さく区切り、例題を1問解いてから理解度を記録しましょう。")
        elif (focus is not None and focus <= 2) or fell("concentration"):
            choose("execution", "実行・集中の見直し候補", reason_for("concentration"),
                   "feedback", "次回は短い学習時間を決め、休憩や学習環境を一つ調整してみましょう。")
        elif (confidence is not None and confidence <= 2) or fell("confidence"):
            choose("confidence", "自信の低下候補", reason_for("confidence"),
                   "awareness", "できたことを一つ書き出し、確認テストや理解度と照らし合わせてみましょう。")
        elif current_count == 3 and (rose("understanding") or rose("concentration")):
            choose("improving", "前進傾向", "理解度または集中度に、記録数で補正した過去平均からの上昇が見られます。",
                   "visualization", "今回うまくいった方法を残し、次回も試して変化を確認しましょう。")
        elif current_count == 3:
            choose("stable", "大きな変化なし" if comparable_count >= STUDYLOG_MIN_HISTORY else "今回の評価は中程度以上（暫定）",
                   "今回の3評価はすべて3以上です。比較データがある項目では、大きな低下の条件に当てはまりません。",
                   "visualization", "今の学習方法で記録を続け、同じカテゴリの過去ログと比べてみましょう。")
    result["support_label"] = STUDYLOG_SUPPORT_TYPES[result["support_type"]]
    return result


def studylog_analyze_logs(logs):
    """表示フィルタに依存せず、学習日・ID順に1回走査する（追加DB照会なし）。"""
    results = {}
    history_by_category = defaultdict(lambda: deque(maxlen=STUDYLOG_HISTORY_LIMIT))
    rows = [dict(row) for row in logs]
    valid_rows = []
    for row in rows:
        try:
            value = row.get("study_date")
            valid_date = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
        except ValueError:
            valid_date = False
        if valid_date:
            valid_rows.append(row)
        else:
            analysis = studylog_analyze_log(row, [])
            analysis.update(state="insufficient", label="判定保留", reason="学習日を確認して保存し直すと、過去ログと比較できます。",
                            support_type="visualization", support_label=STUDYLOG_SUPPORT_TYPES["visualization"],
                            action="学習日を正しい日付に直して保存してください。")
            results[row["id"]] = analysis
    for row in sorted(valid_rows, key=lambda item: (item["study_date"], item["id"])):
        category = (row.get("category") or "").strip()
        history = history_by_category[category]
        results[row["id"]] = studylog_analyze_log(row, list(history))
        if row.get("status") == "completed":
            history.append(row)
    return results


STUDYLOG_PLAN_VERSION = "plan-v1"
STUDYLOG_PLAN_MAX_MINUTES = 480


def studylog_build_next_plan(log, analysis):
    """本人の過去比較と今回の状態から次回案を作る。元のログには書き込まない。"""
    log = dict(log)
    result = {"version": STUDYLOG_PLAN_VERSION, "enabled": False,
              "reason": "学習後の結果を保存すると、次回の計画を自動で組み立てます。"}
    if log.get("status") != "completed":
        return result
    try:
        value = log.get("study_date")
        valid_date = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        valid_date = False
    if not valid_date:
        result["reason"] = "学習日を正しい日付に直すと、次回計画を作れます。"
        return result
    actual = studylog_analysis_number(log, "minutes", 1, 2147483647)
    if actual is None or analysis["state"] == "insufficient":
        result["reason"] = "実際の学習時間と学習後の評価を記録すると、次回計画を作れます。"
        return result

    time_metric = next(metric for metric in analysis["metrics"] if metric["key"] == "minutes")
    planned = studylog_analysis_number(log, "planned_minutes", 1, 2147483647)
    if planned is not None:
        base, basis = planned, "今回の予定時間"
    elif time_metric["count"] >= STUDYLOG_MIN_HISTORY:
        base, basis = time_metric["baseline"], f"同じカテゴリの過去{time_metric['count']}件の平均時間"
    else:
        base, basis = actual, "今回の実際の学習時間（予定と十分な過去記録がないため）"

    weight = min(analysis["comparable_count"] / STUDYLOG_HISTORY_LIMIT, 1)
    factor = 1.0
    state = analysis["state"]
    if state in ("understanding", "execution"):
        factor -= 0.1 + 0.15 * weight
        adjustment = "理解・集中を見直す状態のため、記録の充足度に応じて時間を10〜25%短くします。"
    elif state == "improving" and analysis["comparable_count"] >= STUDYLOG_MIN_HISTORY and all(
            metric["current"] is not None and metric["current"] >= 4
            for metric in analysis["metrics"] if metric["key"] in ("concentration", "understanding", "confidence")):
        factor += 0.1 * weight
        adjustment = "過去3件以上と比べて前進し、3評価も4以上のため、時間を最大10%増やします。"
    else:
        adjustment = "時間を増減する条件には当てはまらないため、基準の時間を維持します。"

    base_minutes = max(1, int(math.floor(base + 0.5)))
    minutes = max(1, min(STUDYLOG_PLAN_MAX_MINUTES, int(math.floor(base * factor + 0.5))))
    goals = {
        "calibration": "確認問題を1問解き、予想と結果を比べる",
        "understanding": "つまずいた範囲の例題を1問解き、要点を説明する",
        "execution": "一つの課題に取り組み、終了時に進んだ範囲を記録する",
        "confidence": "解ける問題を1問確かめ、できたことを一つ記録する",
    }
    own_next_action = (log.get("next_action") or "").strip()
    goal = own_next_action or goals.get(state) or (log.get("goal") or "").strip() or "一つの課題に取り組み、結果を記録する"
    strategy = (log.get("strategy") or "").strip() if state in ("stable", "improving") else ""
    reason = (f"{analysis['label']}。{analysis['reason']} {basis}を基準にします。{adjustment} "
              f"{analysis['evidence']}。分単位で四捨五入し、1〜{STUDYLOG_PLAN_MAX_MINUTES}分に収めます。"
              "学習時間の長短だけで成功・失敗は判定しません。")
    if own_next_action:
        reason += " 自分で記録した「次回どうするか」を目標に引き継ぎます。"
    result.update(enabled=True, minutes=minutes, base_minutes=base_minutes,
                  goal=goal, strategy=strategy or analysis["action"], reason=reason,
                  category=(log.get("category") or "").strip(), task=log.get("task") or "",
                  factor=factor, history_ids=list(analysis["history_ids"]))
    return result

# -----------------------------------------
# U913: 追加処理本体
# -----------------------------------------
STUDYLOG_PLUS_STUMBLE_OPTIONS = [
    "", "集中できなかった", "難しすぎた", "計画不足", "時間不足",
    "疲れていた", "環境が悪かった", "その他"
]


def studylog_plus_form_data(form, existing=None):
    """省略された新項目は既存値を保持し、明示的な空欄だけを未測定に戻す。"""
    current = dict(existing) if existing is not None else {}
    values = {}
    stage = form.get("save_stage", "after")
    if stage not in ("before", "after"):
        raise ValueError("保存方法を選び直してください。")
    if current.get("status") == "completed" and stage == "before":
        raise ValueError("学習完了のログは「更新」で保存してください。")

    def raw(name):
        value = form.get(name, current.get(name))
        return str(value).strip() if value is not None else ""

    study_date = raw("study_date")
    try:
        if date.fromisoformat(study_date).isoformat() != study_date:
            raise ValueError
    except ValueError:
        raise ValueError("学習日を正しい日付で入力してください。") from None
    values["study_date"] = study_date

    for name in ("category", "task", "goal", "strategy", "success_reason",
                 "fail_reason", "next_action", "stumble_reason", "memo"):
        values[name] = raw(name)

    def integer(name, label, minimum, maximum=None, required=False):
        text = raw(name)
        if not text:
            if required:
                raise ValueError(f"{label}を入力してください。")
            return None
        try:
            value = int(text)
        except ValueError:
            raise ValueError(f"{label}は整数で入力してください。") from None
        if value < minimum or (maximum is not None and value > maximum):
            bounds = f"{minimum}〜{maximum}" if maximum is not None else f"{minimum}以上"
            raise ValueError(f"{label}は{bounds}で入力してください。")
        return value

    # SQLiteで扱える範囲に収め、極端な値でも保存エラーにしない。
    values["planned_minutes"] = integer("planned_minutes", "予定学習時間", 1, 2147483647)
    values["minutes"] = integer("minutes", "実際の学習時間", 1, 2147483647, stage == "after")
    for name, label in (
        ("before_concentration", "学習前の集中できそう度"),
        ("before_understanding", "学習前の理解度"),
        ("before_confidence", "学習前の自信度"),
        ("concentration", "学習後の集中度"),
        ("understanding", "学習後の理解度"),
        ("confidence", "学習後の自信度"),
    ):
        values[name] = integer(name, label, 1, 5)

    for name, label in (("before_test_score", "学習前の確認テスト"),
                        ("after_test_score", "学習後の確認テスト")):
        text = raw(name)
        try:
            score = float(text) if text else None
        except ValueError:
            raise ValueError(f"{label}は0〜100の数値で入力してください。") from None
        if score is not None and (not math.isfinite(score) or not 0 <= score <= 100):
            raise ValueError(f"{label}は0〜100の数値で入力してください。")
        values[name] = score

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    values["status"] = "in_progress" if stage == "before" else "completed"
    before_fields = ("goal", "planned_minutes", "strategy", "before_concentration",
                     "before_understanding", "before_confidence", "before_test_score")
    has_before = any(values[name] is not None and values[name] != "" for name in before_fields)
    values["before_saved_at"] = current.get("before_saved_at") or (now if has_before or stage == "before" else None)
    values["after_saved_at"] = current.get("after_saved_at") or (now if stage == "after" else None)
    values["updated_at"] = now
    return values


def studylog_plus_insert(form):
    values = studylog_plus_form_data(form)
    values["created_at"] = values["updated_at"]
    # カラム名は上の固定辞書からのみ取得し、入力値はプレースホルダで渡す。
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    with closing(studylog_plus_get_conn()) as conn, conn:
        cursor = conn.execute(
            f"INSERT INTO logs ({columns}) VALUES ({placeholders})", tuple(values.values())
        )
        return cursor.lastrowid

# -----------------------------------------
# U914: 更新処理本体
# -----------------------------------------
def studylog_plus_update_db(log_id, form):
    with closing(studylog_plus_get_conn()) as conn, conn:
        current = conn.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
        if current is None:
            return False
        values = studylog_plus_form_data(form, current)
        assignments = ", ".join(f"{name} = ?" for name in values)
        conn.execute(
            f"UPDATE logs SET {assignments} WHERE id = ?", (*values.values(), log_id)
        )
    return True

# -----------------------------------------
# U915: 削除処理本体
# -----------------------------------------
def studylog_plus_delete_db(log_id):
    conn = studylog_plus_get_conn()
    conn.execute("DELETE FROM logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()

# -----------------------------------------
# U916: 新しい一覧画面
# -----------------------------------------
def studylog_plus_index(form_data=None, error=None):
    where_sql, params, filters = studylog_plus_build_filters()
    all_logs = studylog_plus_get_logs()
    logs = studylog_plus_get_logs(where_sql, params) if where_sql else all_logs
    analyses = studylog_analyze_logs(all_logs)
    plans = {log["id"]: studylog_build_next_plan(log, analyses[log["id"]]) for log in all_logs}
    summary = studylog_plus_get_summary(where_sql, params)
    categories = studylog_plus_get_categories()
    plan_notice = None
    response_status = 200
    if form_data is None:
        form_data = {"study_date": date.today().isoformat()}
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
                plan_notice = f"ログ #{int(source)} の補正計画を入力欄へ引き継ぎました。まだ保存していません。"

    html = render_template_string(
        STUDYLOG_PLUS_INDEX_HTML,
        logs=logs,
        analyses=analyses,
        plans=plans,
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

# -----------------------------------------
# U917: 新しい追加処理
# -----------------------------------------
def studylog_plus_add():
    try:
        studylog_plus_insert(request.form)
    except ValueError as exc:
        return studylog_plus_index(dict(request.form), str(exc)), 400
    return redirect("/")

# -----------------------------------------
# U918: 編集画面
# -----------------------------------------
def studylog_plus_edit(log_id, form_data=None, error=None):
    log = studylog_plus_get_log(log_id)
    if log is None:
        return "log not found", 404

    return render_template_string(
        STUDYLOG_PLUS_EDIT_HTML,
        form_data=form_data if form_data is not None else dict(log),
        form_action=f"/update/{log_id}",
        is_edit=True,
        error=error,
        stumble_options=STUDYLOG_PLUS_STUMBLE_OPTIONS
    )

# -----------------------------------------
# U919: 更新処理
# -----------------------------------------
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

# -----------------------------------------
# U920: 削除処理
# -----------------------------------------
def studylog_plus_delete(log_id):
    studylog_plus_delete_db(log_id)
    return redirect("/")

# -----------------------------------------
# U921: 既存ルート差し替え補助
# -----------------------------------------
def studylog_plus_patch_existing_rule(target_rule, target_methods, new_func):
    found_endpoint = None

    for rule in app.url_map.iter_rules():
        if rule.rule == target_rule:
            rule_methods = set(rule.methods or [])
            if set(target_methods).issubset(rule_methods):
                found_endpoint = rule.endpoint
                break

    if found_endpoint:
        app.view_functions[found_endpoint] = new_func
        return True

    return False

# -----------------------------------------
# U922: 追加ルート/差し替え実行
# -----------------------------------------
def studylog_plus_apply_patch():
    studylog_plus_add_missing_columns()

    # 既存 / を差し替え。なければ新規追加。
    if not studylog_plus_patch_existing_rule("/", ["GET"], studylog_plus_index):
        app.add_url_rule("/", endpoint="studylog_plus_index", view_func=studylog_plus_index, methods=["GET"])

    # 既存 /add を差し替え。なければ新規追加。
    if not studylog_plus_patch_existing_rule("/add", ["POST"], studylog_plus_add):
        app.add_url_rule("/add", endpoint="studylog_plus_add", view_func=studylog_plus_add, methods=["POST"])

    # 既存 /delete/<int:log_id> を差し替え。なければ新規追加。
    if not studylog_plus_patch_existing_rule("/delete/<int:log_id>", ["POST"], studylog_plus_delete):
        app.add_url_rule("/delete/<int:log_id>", endpoint="studylog_plus_delete", view_func=studylog_plus_delete, methods=["POST"])

    # edit / update は新規追加
    existing_rules = {rule.rule for rule in app.url_map.iter_rules()}

    if "/edit/<int:log_id>" not in existing_rules:
        app.add_url_rule("/edit/<int:log_id>", endpoint="studylog_plus_edit", view_func=studylog_plus_edit, methods=["GET"])

    if "/update/<int:log_id>" not in existing_rules:
        app.add_url_rule("/update/<int:log_id>", endpoint="studylog_plus_update", view_func=studylog_plus_update, methods=["POST"])

# -----------------------------------------
# U923: 追記パック起動
# -----------------------------------------
studylog_plus_apply_patch()

# =========================================
# 追加: studylog 中改良用の補助関数
# =========================================

from datetime import date, timedelta

def add_missing_columns():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_date TEXT,
            minutes INTEGER,
            concentration INTEGER,
            understanding INTEGER,
            memo TEXT,
            created_at TEXT
        )
    """)

    rows = conn.execute("PRAGMA table_info(logs)").fetchall()
    existing = {row["name"] for row in rows}

    needed = {
        "category": "TEXT",
        "goal": "TEXT",
        "confidence": "INTEGER DEFAULT 3",
        "success_reason": "TEXT",
        "fail_reason": "TEXT",
        "next_action": "TEXT",
        "stumble_reason": "TEXT"
    }

    for col, col_type in needed.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE logs ADD COLUMN {col} {col_type}")

    conn.commit()
    conn.close()


def get_filter_values():
    range_name = request.args.get("range", "all")
    category = request.args.get("category", "").strip()
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    today = date.today()

    if range_name == "today":
        start_date = today.isoformat()
        end_date = today.isoformat()
    elif range_name == "week":
        monday = today - timedelta(days=today.weekday())
        start_date = monday.isoformat()
        end_date = today.isoformat()
    elif range_name == "month":
        first_day = today.replace(day=1)
        start_date = first_day.isoformat()
        end_date = today.isoformat()

    return {
        "range": range_name,
        "category": category,
        "start_date": start_date,
        "end_date": end_date
    }


def get_categories():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT DISTINCT category
        FROM logs
        WHERE category IS NOT NULL AND TRIM(category) != ''
        ORDER BY category
    """).fetchall()
    conn.close()
    return [row["category"] for row in rows]

@app.route("/edit/<int:log_id>")
def edit(log_id):
    add_missing_columns()

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    log = conn.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
    conn.close()

    if log is None:
        return "log not found", 404

    stumble_options = [
        "",
        "集中できなかった",
        "難しすぎた",
        "計画不足",
        "時間不足",
        "疲れていた",
        "環境が悪かった",
        "その他"
    ]

    return render_template(
        "edit.html",
        log=log,
        stumble_options=stumble_options
    )


@app.route("/update/<int:log_id>", methods=["POST"])
def update(log_id):
    add_missing_columns()

    conn = get_db_connection()
    conn.execute("""
        UPDATE logs
        SET
            study_date = ?,
            category = ?,
            minutes = ?,
            concentration = ?,
            understanding = ?,
            confidence = ?,
            goal = ?,
            success_reason = ?,
            fail_reason = ?,
            next_action = ?,
            stumble_reason = ?,
            memo = ?
        WHERE id = ?
    """, (
        request.form.get("study_date", ""),
        request.form.get("category", "").strip(),
        int(request.form.get("minutes", 0)),
        int(request.form.get("concentration", 3)),
        int(request.form.get("understanding", 3)),
        int(request.form.get("confidence", 3)),
        request.form.get("goal", "").strip(),
        request.form.get("success_reason", "").strip(),
        request.form.get("fail_reason", "").strip(),
        request.form.get("next_action", "").strip(),
        request.form.get("stumble_reason", "").strip(),
        request.form.get("memo", "").strip(),
        log_id
    ))
    conn.commit()
    conn.close()

    return redirect(url_for("index"))


# =========================================
# U999: 起動処理
# =========================================
if __name__ == "__main__":
    init_db()
    app.run(debug=False)


