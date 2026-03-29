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
from flask import Flask, request, redirect, url_for, render_template_string
import sqlite3
from pathlib import Path


# =========================================
# U102: Flaskアプリ初期化
# =========================================
app = Flask(__name__)


# =========================================
# U103: DBパス設定
# =========================================
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "srl_log.db"


# =========================================
# U001: HTMLテンプレート
# =========================================
HTML_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <title>StudyLog</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans",
                         "Yu Gothic", "Segoe UI", sans-serif;
            background: #f4f8fb;
            color: #1f2a33;
            margin: 0;
            padding: 24px;
        }

        .wrap {
            max-width: 960px;
            margin: 0 auto;
        }

        .title-box, .card {
            background: #ffffff;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.06);
            margin-bottom: 20px;
        }

        h1 {
            margin: 0 0 8px 0;
            font-size: 28px;
        }

        .sub {
            color: #5c6b77;
            font-size: 14px;
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
        }

        .grid-1 {
            display: grid;
            grid-template-columns: 1fr;
            gap: 14px;
        }

        label {
            display: block;
            font-size: 14px;
            margin-bottom: 6px;
            color: #34424d;
            font-weight: 600;
        }

        input, textarea, select {
            width: 100%;
            box-sizing: border-box;
            border: 1px solid #cfd9e2;
            border-radius: 10px;
            padding: 10px 12px;
            font-size: 14px;
            background: #fbfdff;
        }

        textarea {
            min-height: 90px;
            resize: vertical;
        }

        .btn {
            border: none;
            border-radius: 10px;
            padding: 12px 16px;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
        }

        .btn-main {
            background: #5aa9e6;
            color: white;
        }

        .btn-delete {
            background: #e56b6f;
            color: white;
            padding: 8px 12px;
            font-size: 13px;
        }

        .summary-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 14px;
        }

        .summary-item {
            background: #eef7ff;
            border-radius: 14px;
            padding: 16px;
        }

        .summary-label {
            font-size: 13px;
            color: #5b6b78;
            margin-bottom: 6px;
        }

        .summary-value {
            font-size: 24px;
            font-weight: 800;
            color: #1f4f75;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            text-align: left;
            padding: 12px 10px;
            border-bottom: 1px solid #e6edf3;
            vertical-align: top;
            font-size: 14px;
        }

        th {
            background: #f7fbff;
            color: #43515d;
        }

        .mini {
            color: #6a7883;
            font-size: 12px;
        }

        .empty {
            color: #6b7a86;
            padding: 12px 0;
        }

        .danger-line {
            color: #b94b4f;
            font-size: 13px;
            margin-top: 10px;
        }

        @media (max-width: 800px) {
            .grid, .summary-grid {
                grid-template-columns: 1fr;
            }

            table, thead, tbody, th, td, tr {
                display: block;
            }

            thead {
                display: none;
            }

            tr {
                background: #fff;
                border: 1px solid #e6edf3;
                border-radius: 12px;
                padding: 10px;
                margin-bottom: 12px;
            }

            td {
                border-bottom: none;
                padding: 6px 0;
            }

            td::before {
                content: attr(data-label) ": ";
                font-weight: 700;
                color: #43515d;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">

        <div class="title-box">
            <h1>StudyLog</h1>
            <div class="sub">
                 <br>
                </div>
        </div>

        <div class="card">
            <h2>ログ追加</h2>
            <form method="post" action="{{ url_for('add_log') }}">
                <div class="grid">
                    <div>
                        <label>日付</label>
                        <input type="date" name="study_date" required>
                    </div>
                    <div>
                        <label>学習時間（分）</label>
                        <input type="number" name="minutes" min="0" max="1440" required>
                    </div>
                </div>

                <div class="grid">
                    <div>
                        <label>今日の目標</label>
                        <input type="text" name="goal" maxlength="100" placeholder="例: 卒論を進める">
                    </div>
                    <div>
                        <label>取り組んだ内容</label>
                        <input type="text" name="task" maxlength="100" placeholder="例: メモ整理">
                    </div>
                </div>

                <div class="grid">
                    <div>
                        <label>集中度（1〜5）</label>
                        <select name="focus_score" required>
                            <option value="1">1</option>
                            <option value="2">2</option>
                            <option value="3" selected>3</option>
                            <option value="4">4</option>
                            <option value="5">5</option>
                        </select>
                    </div>
                    <div>
                        <label>理解度（1〜5）</label>
                        <select name="understanding_score" required>
                            <option value="1">1</option>
                            <option value="2">2</option>
                            <option value="3" selected>3</option>
                            <option value="4">4</option>
                            <option value="5">5</option>
                        </select>
                    </div>
                </div>

                <div class="grid-1">
                    <div>
                        <label>振り返り</label>
                        <textarea name="reflection" maxlength="500" placeholder="例: 集中はできたが、整理が甘かった"></textarea>
                    </div>
                    <div>
                        <label>次にやること</label>
                        <textarea name="next_action" maxlength="500" placeholder="例: 明日は表を作る"></textarea>
                    </div>
                </div>

                <div style="margin-top: 14px;">
                    <button type="submit" class="btn btn-main">保存</button>
                </div>
            </form>
        </div>

        <div class="card">
            <h2>今月のサマリー</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <div class="summary-label">合計学習時間</div>
                    <div class="summary-value">{{ summary.total_minutes }} 分</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">平均集中度</div>
                    <div class="summary-value">{{ summary.avg_focus }}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">平均理解度</div>
                    <div class="summary-value">{{ summary.avg_understanding }}</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>ログ一覧</h2>

            {% if logs %}
                <table>
                    <thead>
                        <tr>
                            <th>日付</th>
                            <th>内容</th>
                            <th>学習時間</th>
                            <th>集中/理解</th>
                            <th>振り返り / 次</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for row in logs %}
                        <tr>
                            <td data-label="日付">
                                {{ row["study_date"] }}<br>
                                <span class="mini">{{ row["created_at"] }}</span>
                            </td>
                            <td data-label="内容">
                                <strong>目標:</strong> {{ row["goal"] or "-" }}<br>
                                <strong>実施:</strong> {{ row["task"] or "-" }}
                            </td>
                            <td data-label="学習時間">
                                {{ row["minutes"] }} 分
                            </td>
                            <td data-label="集中/理解">
                                集中 {{ row["focus_score"] }} / 5<br>
                                理解 {{ row["understanding_score"] }} / 5
                            </td>
                            <td data-label="振り返り / 次">
                                <strong>振り返り:</strong> {{ row["reflection"] or "-" }}<br>
                                <strong>次:</strong> {{ row["next_action"] or "-" }}
                            </td>
                            <td data-label="操作">
                                <form method="post" action="{{ url_for('delete_log', log_id=row['id']) }}">
                                    <button type="submit" class="btn btn-delete">削除</button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% else %}
                <div class="empty">まだ学習ログはありません。</div>
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
    init_db()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM study_logs
        ORDER BY study_date DESC, id DESC
    """)
    logs = cur.fetchall()
    conn.close()

    summary = get_summary()

    return render_template_string(
        HTML_TEMPLATE,
        logs=logs,
        summary=summary
    )


# =========================================
# U202: 学習ログ追加
# =========================================
@app.route("/add", methods=["POST"])
def add_log():
    study_date = request.form.get("study_date", "").strip()
    goal = request.form.get("goal", "").strip()[:100]
    task = request.form.get("task", "").strip()[:100]
    minutes = safe_int(request.form.get("minutes", "0"))
    focus_score = safe_int(request.form.get("focus_score", "3"), 3)
    understanding_score = safe_int(request.form.get("understanding_score", "3"), 3)
    reflection = request.form.get("reflection", "").strip()[:500]
    next_action = request.form.get("next_action", "").strip()[:500]

    if not study_date:
        return redirect(url_for("index"))

    if minutes < 0:
        minutes = 0
    if minutes > 1440:
        minutes = 1440

    if focus_score < 1:
        focus_score = 1
    if focus_score > 5:
        focus_score = 5

    if understanding_score < 1:
        understanding_score = 1
    if understanding_score > 5:
        understanding_score = 5

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO study_logs (
            study_date, goal, task, minutes,
            focus_score, understanding_score,
            reflection, next_action
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        study_date, goal, task, minutes,
        focus_score, understanding_score,
        reflection, next_action
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
from datetime import datetime, date, timedelta
from flask import render_template_string

# -----------------------------------------
# U902: 追加テンプレート（一覧）
# -----------------------------------------
STUDYLOG_PLUS_INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <title>studylog+</title>
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
    <h1>studylog+</h1>

    <div class="card">
        <h2>学習ログを追加</h2>
        <form method="post" action="/add">
            <div class="grid-3">
                <div>
                    <label>学習日</label>
                    <input type="date" name="study_date" value="{{ today }}" required>
                </div>
                <div>
                    <label>カテゴリ</label>
                    <input type="text" name="category" placeholder="例: Python / 卒論 / 英語">
                </div>
                <div>
                    <label>学習時間（分）</label>
                    <input type="number" name="minutes" min="1" required>
                </div>
            </div>

            <div class="grid-3" style="margin-top:14px;">
                <div>
                    <label>集中度（1〜5）</label>
                    <select name="concentration">
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3" selected>3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                    </select>
                </div>
                <div>
                    <label>理解度（1〜5）</label>
                    <select name="understanding">
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3" selected>3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                    </select>
                </div>
                <div>
                    <label>自信度（1〜5）</label>
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
                <textarea name="goal" placeholder="例: 先行研究を2本読む / 編集機能を実装する"></textarea>
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
                    <label>自由メモ</label>
                    <textarea name="memo"></textarea>
                </div>
            </div>

            <div style="margin-top:16px;">
                <button type="submit">保存する</button>
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
                        {% if log["stumble_reason"] %}
                            <span class="pill">つまずき: {{ log["stumble_reason"] }}</span>
                        {% endif %}
                    </div>

                    <div class="section">
                        <strong>学習前の目標</strong>
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
                        <form method="post" action="/delete/{{ log['id'] }}" onsubmit="return confirm('このログを削除しますか？');">
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

# -----------------------------------------
# U903: 追加テンプレート（編集）
# -----------------------------------------
STUDYLOG_PLUS_EDIT_HTML = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <title>studylog+ 編集</title>
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
        @media (max-width:900px){.grid-2,.grid-3{grid-template-columns:1fr;}}
    </style>
</head>
<body>
<div class="wrap">
    <div class="card">
        <h1>ログを編集</h1>

        <form method="post" action="/update/{{ log['id'] }}">
            <div class="grid-3">
                <div>
                    <label>学習日</label>
                    <input type="date" name="study_date" value="{{ log['study_date'] }}" required>
                </div>
                <div>
                    <label>カテゴリ</label>
                    <input type="text" name="category" value="{{ log['category'] or '' }}">
                </div>
                <div>
                    <label>学習時間（分）</label>
                    <input type="number" name="minutes" min="1" value="{{ log['minutes'] }}" required>
                </div>
            </div>

            <div class="grid-3" style="margin-top:14px;">
                <div>
                    <label>集中度（1〜5）</label>
                    <select name="concentration">
                        {% for i in [1,2,3,4,5] %}
                            <option value="{{ i }}" {% if log['concentration'] == i %}selected{% endif %}>{{ i }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label>理解度（1〜5）</label>
                    <select name="understanding">
                        {% for i in [1,2,3,4,5] %}
                            <option value="{{ i }}" {% if log['understanding'] == i %}selected{% endif %}>{{ i }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label>自信度（1〜5）</label>
                    <select name="confidence">
                        {% for i in [1,2,3,4,5] %}
                            <option value="{{ i }}" {% if log['confidence'] == i %}selected{% endif %}>{{ i }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>

            <div class="section">
                <h3>学習前</h3>
                <label>今日の目標</label>
                <textarea name="goal">{{ log['goal'] or '' }}</textarea>
            </div>

            <div class="section">
                <h3>学習後</h3>
                <div class="grid-2">
                    <div>
                        <label>うまくいった理由</label>
                        <textarea name="success_reason">{{ log['success_reason'] or '' }}</textarea>
                    </div>
                    <div>
                        <label>うまくいかなかった理由</label>
                        <textarea name="fail_reason">{{ log['fail_reason'] or '' }}</textarea>
                    </div>
                </div>

                <div style="margin-top:14px;">
                    <label>次回どうするか</label>
                    <textarea name="next_action">{{ log['next_action'] or '' }}</textarea>
                </div>

                <div style="margin-top:14px;">
                    <label>つまずき理由</label>
                    <select name="stumble_reason">
                        {% for item in stumble_options %}
                            <option value="{{ item }}" {% if log['stumble_reason'] == item %}selected{% endif %}>{{ item }}</option>
                        {% endfor %}
                    </select>
                </div>

                <div style="margin-top:14px;">
                    <label>自由メモ</label>
                    <textarea name="memo">{{ log['memo'] or '' }}</textarea>
                </div>
            </div>

            <div style="margin-top:16px;">
                <button type="submit">更新する</button>
            </div>
        </form>

        <a class="back" href="/">← 一覧へ戻る</a>
    </div>
</div>
</body>
</html>
"""

# -----------------------------------------
# U904: DB名取得
# -----------------------------------------
STUDYLOG_PLUS_DB_NAME = globals().get("DB_NAME", "studylog.db")

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
        "stumble_reason": "TEXT"
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
            COALESCE(SUM(minutes), 0) AS total_minutes,
            ROUND(COALESCE(AVG(concentration), 0), 1) AS avg_concentration,
            ROUND(COALESCE(AVG(understanding), 0), 1) AS avg_understanding
        FROM logs
        {where_sql}
        ''',
        params
    ).fetchone()
    conn.close()

    return {
        "count": row["count"],
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
# U913: 追加処理本体
# -----------------------------------------
def studylog_plus_insert(form):
    conn = studylog_plus_get_conn()
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
        form.get("study_date", ""),
        form.get("category", "").strip(),
        int(form.get("minutes", 0)),
        int(form.get("concentration", 3)),
        int(form.get("understanding", 3)),
        int(form.get("confidence", 3)),
        form.get("goal", "").strip(),
        form.get("success_reason", "").strip(),
        form.get("fail_reason", "").strip(),
        form.get("next_action", "").strip(),
        form.get("stumble_reason", "").strip(),
        form.get("memo", "").strip(),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()

# -----------------------------------------
# U914: 更新処理本体
# -----------------------------------------
def studylog_plus_update_db(log_id, form):
    conn = studylog_plus_get_conn()
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
        form.get("study_date", ""),
        form.get("category", "").strip(),
        int(form.get("minutes", 0)),
        int(form.get("concentration", 3)),
        int(form.get("understanding", 3)),
        int(form.get("confidence", 3)),
        form.get("goal", "").strip(),
        form.get("success_reason", "").strip(),
        form.get("fail_reason", "").strip(),
        form.get("next_action", "").strip(),
        form.get("stumble_reason", "").strip(),
        form.get("memo", "").strip(),
        log_id
    ))
    conn.commit()
    conn.close()

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
def studylog_plus_index():
    where_sql, params, filters = studylog_plus_build_filters()
    logs = studylog_plus_get_logs(where_sql, params)
    summary = studylog_plus_get_summary(where_sql, params)
    categories = studylog_plus_get_categories()

    return render_template_string(
        STUDYLOG_PLUS_INDEX_HTML,
        logs=logs,
        summary=summary,
        categories=categories,
        filters=filters,
        today=date.today().isoformat()
    )

# -----------------------------------------
# U917: 新しい追加処理
# -----------------------------------------
def studylog_plus_add():
    studylog_plus_insert(request.form)
    return redirect("/")

# -----------------------------------------
# U918: 編集画面
# -----------------------------------------
def studylog_plus_edit(log_id):
    log = studylog_plus_get_log(log_id)
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

    return render_template_string(
        STUDYLOG_PLUS_EDIT_HTML,
        log=log,
        stumble_options=stumble_options
    )

# -----------------------------------------
# U919: 更新処理
# -----------------------------------------
def studylog_plus_update(log_id):
    if studylog_plus_get_log(log_id) is None:
        return "log not found", 404
    studylog_plus_update_db(log_id, request.form)
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
# U999: 起動処理
# =========================================
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
