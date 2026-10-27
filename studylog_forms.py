"""Input validation and date filters shared by add and edit."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import math


def today_jst():
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()

STUDYLOG_PLUS_STUMBLE_OPTIONS = ['', '集中できなかった', '難しすぎた', '計画不足', '時間不足', '疲れていた', '環境が悪かった', 'その他']

def studylog_plus_get_dates(range_name, start_date_str, end_date_str):
    today = today_jst()

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


def studylog_plus_build_filters(args):
    range_name = args.get("range", "all")
    category = args.get("category", "").strip()
    start_date_in = args.get("start_date", "")
    end_date_in = args.get("end_date", "")

    if range_name not in ("all", "today", "week", "month", "custom"):
        raise ValueError("表示する期間を選び直してください。")
    if len(category) > 100:
        raise ValueError("カテゴリは100文字以内で指定してください。")
    if range_name == "custom":
        for value in (start_date_in, end_date_in):
            if value:
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except ValueError:
                    raise ValueError("絞り込みの日付を正しい日付で入力してください。") from None
        if start_date_in and end_date_in and start_date_in > end_date_in:
            raise ValueError("開始日は終了日以前の日付で指定してください。")

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
        maximum = 100 if name == "category" else 10000 if name == "memo" else 2000
        if len(values[name]) > maximum:
            label = {"category": "カテゴリ", "task": "学習内容", "goal": "目標",
                     "strategy": "学習方法", "success_reason": "成功理由",
                     "fail_reason": "うまくいかなかった理由", "next_action": "次回の行動",
                     "stumble_reason": "つまずいた理由", "memo": "メモ"}[name]
            raise ValueError(f"{label}は{maximum}文字以内で入力してください。")

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
