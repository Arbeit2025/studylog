"""公開サンプル用の限定インターフェース。

学習ログの保存・表示と数値検証のみを提供します。
個別判定・計画補正・効果評価の実装は非公開版に分離されています。
本ファイルに非公開版の実装をコピーしないでください。
"""
import math

STUDYLOG_EFFECT_VERSION = "public-basic"
STUDYLOG_EFFECT_METRICS = (
    ("concentration", "集中度", "", 1, 5),
    ("understanding", "理解度", "", 1, 5),
    ("confidence", "自信度", "", 1, 5),
    ("after_test_score", "確認テスト", "点", 0, 100),
)


def studylog_analysis_number(log, field, minimum, maximum):
    """保存データの表示時に不正・欠測値を数値として扱わない。"""
    raw = log.get(field)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        number = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return None
    if field not in ("before_test_score", "after_test_score") and not number.is_integer():
        return None
    return number


def studylog_analyze_log(log, history):
    """公開版では学習状態の自動判定を提供しない。"""
    return {
        "state": "unavailable",
        "label": "基本記録のみ",
        "reason": "学習状態の自動判定は公開サンプルに含まれません。",
        "support_type": "visualization",
        "support_label": "未提供",
        "action": "",
        "evidence": "",
        "history_ids": [],
        "history_count": 0,
        "comparable_count": 0,
        "metrics": [],
        "gap": None,
        "gap_basis": None,
    }


def studylog_analyze_logs(logs):
    return {log["id"]: studylog_analyze_log(log, []) for log in logs}


def studylog_build_next_plan(log, analysis):
    return {
        "enabled": False,
        "version": "public-basic",
        "reason": "計画の自動補正は公開サンプルに含まれません。",
        "category": dict(log).get("category") or "",
        "task": dict(log).get("task") or "",
        "minutes": None,
        "base_minutes": None,
        "goal": dict(log).get("goal") or "",
        "strategy": dict(log).get("strategy") or "",
    }


def studylog_valid_tracking(value, saved=False):
    # 非公開機能由来の入力を公開版では受け付けない。
    return False


def studylog_evaluate_plan(log):
    return {
        "tracked": False,
        "state": "untracked",
        "label": "未提供",
        "reason": "",
        "metrics": [],
        "tracking": None,
    }


def studylog_summarize_effects(logs, effects):
    return {"total": 0, "evaluated": 0, "waiting": 0, "excluded": 0, "groups": []}
