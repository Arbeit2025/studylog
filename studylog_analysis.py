"""Pure state comparison, next-plan generation, and outcome summaries (no database writes)."""
from collections import defaultdict, deque
from datetime import date
import json
import math

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
    if field not in ("before_test_score", "after_test_score") and not value.is_integer():
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


STUDYLOG_EFFECT_VERSION = "effect-v1"
STUDYLOG_EFFECT_METRICS = tuple(metric for metric in STUDYLOG_ANALYSIS_METRICS if metric[0] != "minutes")


def studylog_valid_tracking(value, saved=False):
    """壊れた旧値や将来版を効果として誤集計しない。"""
    if not isinstance(value, dict) or value.get("version") != STUDYLOG_EFFECT_VERSION:
        return False
    if type(value.get("source_id")) is not int or not 0 < value["source_id"] <= 2147483647:
        return False
    try:
        valid_date = isinstance(value.get("source_date"), str) and date.fromisoformat(value["source_date"]).isoformat() == value["source_date"]
    except ValueError:
        valid_date = False
    if not valid_date or not isinstance(value.get("category"), str):
        return False
    plan = value.get("plan")
    if not isinstance(plan, dict) or not isinstance(value.get("source_results"), dict):
        return False
    if not all(isinstance(plan.get(key), str) for key in ("version", "goal", "strategy", "reason")):
        return False
    if any(type(plan.get(key)) is not int or plan[key] < 1 for key in ("minutes", "base_minutes")):
        return False
    if saved:
        adopted = value.get("adopted_plan")
        if not isinstance(value.get("adopted_at"), str) or not isinstance(adopted, dict):
            return False
        if not all(isinstance(adopted.get(key), str) for key in ("goal", "strategy")):
            return False
        if "planned_minutes" not in adopted:
            return False
        if adopted.get("planned_minutes") is not None and (type(adopted["planned_minutes"]) is not int or adopted["planned_minutes"] < 1):
            return False
    return True


def studylog_evaluate_plan(log):
    """採用時の比較元との差を示す。時間の長短や因果効果を成功と見なさない。"""
    log = dict(log)
    raw = log.get("plan_tracking")
    result = {"tracked": bool(raw), "state": "untracked", "label": "補正計画の記録なし",
              "reason": "", "metrics": []}
    if not raw:
        return result
    result.update(state="excluded", label="比較保留", reason="採用時の情報を確認できません。")
    try:
        tracking = json.loads(raw)
    except (ValueError, TypeError):
        return result
    if not studylog_valid_tracking(tracking, saved=True):
        return result
    plan, adopted = tracking["plan"], tracking["adopted_plan"]
    edited = any(adopted[key] != plan["minutes" if key == "planned_minutes" else key]
                 for key in ("planned_minutes", "goal", "strategy"))
    changed = any(log.get(key) != adopted[key] for key in ("planned_minutes", "goal", "strategy"))
    result.update(tracking=tracking, adoption_label="提案を編集して採用" if edited else "提案どおりに採用")
    if changed:
        result["adoption_label"] += "・採用後にも計画を編集"
    try:
        current_date = log.get("study_date")
        valid_date = isinstance(current_date, str) and date.fromisoformat(current_date).isoformat() == current_date
    except ValueError:
        valid_date = False
    if not valid_date or current_date < tracking["source_date"] or log.get("id", 0) <= tracking["source_id"]:
        result["reason"] = "学習日または記録の順序が比較元より前のため、継続評価を保留しています。"
        return result
    if (log.get("category") or "").strip() != tracking["category"]:
        result["reason"] = "採用時とカテゴリが異なるため、異なる学習の結果を混ぜずに比較を保留しています。"
        return result
    if log.get("status") != "completed":
        result.update(state="waiting", label="学習後の結果待ち", reason="同じ記録に学習後の結果を保存すると評価します。")
        return result
    metrics = []
    for field, label, unit, low, high in STUDYLOG_EFFECT_METRICS:
        current = studylog_analysis_number(log, field, low, high)
        baseline = studylog_analysis_number(tracking["source_results"], field, low, high)
        before_field = {"understanding": "before_understanding", "confidence": "before_confidence",
                        "after_test_score": "before_test_score"}.get(field)
        before = studylog_analysis_number(log, before_field, low, high) if before_field else None
        metrics.append({"key": field, "label": label, "unit": unit, "current": current, "baseline": baseline,
                        "delta": current - baseline if current is not None and baseline is not None else None,
                        "gain": current - before if current is not None and before is not None else None})
    result["metrics"] = metrics
    deltas = [metric["delta"] for metric in metrics if metric["delta"] is not None]
    if not deltas:
        result["reason"] = "今回と比較元の両方にある評価・得点がないため、比較を保留しています。"
        return result
    up, down = any(delta > 0 for delta in deltas), any(delta < 0 for delta in deltas)
    label = "上昇・低下が混在" if up and down else "比較値が上昇" if up else "比較値が低下" if down else "比較値に変化なし"
    result.update(state="evaluated", label=label,
                  reason=f"採用時の比較元と{len(deltas)}項目で比較しています。記録上の変化であり、補正による因果効果や統計的な有意差を示すものではありません。")
    return result


def studylog_summarize_effects(logs, effects):
    """表示中の対象をカテゴリ別・項目別件数で集計。再編集で件数を重複させない。"""
    summary = {"total": 0, "evaluated": 0, "waiting": 0, "excluded": 0, "groups": []}
    groups = {}
    for row in logs:
        effect = effects[row["id"]]
        if not effect["tracked"]:
            continue
        summary["total"] += 1
        summary[effect["state"]] += 1
        if effect["state"] != "evaluated":
            continue
        category = effect["tracking"]["category"]
        if category not in groups:
            groups[category] = {"category": category, "evaluated": 0, "recent": [],
                                "values": {field: [] for field, *_ in STUDYLOG_EFFECT_METRICS}}
        group = groups[category]
        group["evaluated"] += 1
        group["recent"].append({"id": row["id"], "study_date": row["study_date"], "label": effect["label"]})
        for metric in effect["metrics"]:
            if metric["delta"] is not None:
                group["values"][metric["key"]].append(metric["delta"])
    for category in sorted(groups):
        group = groups[category]
        group["metrics"] = [{"key": field, "label": label, "unit": unit, "count": len(group["values"][field]),
                              "mean": sum(group["values"][field]) / len(group["values"][field]) if group["values"][field] else None}
                             for field, label, unit, *_ in STUDYLOG_EFFECT_METRICS]
        group.pop("values")
        group["recent"] = sorted(group["recent"], key=lambda item: (item["study_date"], item["id"]), reverse=True)[:5]
        summary["groups"].append(group)
    return summary
