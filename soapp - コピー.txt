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
# U999: 起動処理
# =========================================
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
