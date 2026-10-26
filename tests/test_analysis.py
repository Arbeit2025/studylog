"""状態判定の境界と、実際の保存・編集・比較表示の回帰テスト。"""
from datetime import date, timedelta
from html.parser import HTMLParser
from unittest.mock import patch

from test_studylog import StudylogFixture


class AnalysisSections(HTMLParser):
    """絞り込み前後で、対象ログの分析部分だけを比べる。"""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.sections = {}
        self.log_id = None
        self.depth = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and "analysis" in attrs.get("class", "").split():
            self.log_id = int(attrs["data-log-id"])
            self.sections[self.log_id] = [attrs["data-state"]]
            self.depth = 1
        elif self.log_id is not None and tag == "div":
            self.depth += 1

    def handle_data(self, data):
        if self.log_id is not None and data.strip():
            self.sections[self.log_id].append(data.strip())

    def handle_endtag(self, tag):
        if self.log_id is not None and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.log_id = None


class AnalysisTest(StudylogFixture):
    def sample(self, **changes):
        row = dict(id=100, study_date="2026-10-26", category="Python", status="completed",
                   minutes=30, concentration=3, understanding=3, confidence=3, after_test_score=None)
        row.update(changes)
        return row

    def history(self, count=5, **changes):
        return [self.sample(id=index + 1, study_date=(date(2026, 10, 1) + timedelta(days=index)).isoformat(),
                            **changes) for index in range(count)]

    def analyze(self, row=None, history=None):
        return self.module.studylog_analyze_log(row or self.sample(), history or [])

    def metric(self, analysis, key):
        return next(item for item in analysis["metrics"] if item["key"] == key)

    def save(self, **changes):
        data = self.completed()
        data.update(changes)
        response = self.client.post("/add", data=data)
        self.assertEqual(response.status_code, 302)
        return self.rows()[-1]

    def test_every_state_and_support_mapping(self):
        cases = [
            ({"confidence": 5, "after_test_score": 0}, "calibration", "awareness"),
            ({"confidence": 1, "after_test_score": 100}, "calibration", "awareness"),
            ({"understanding": 1, "confidence": 2}, "understanding", "opportunity"),
            ({"concentration": 1}, "execution", "feedback"),
            ({"confidence": 2}, "confidence", "awareness"),
            ({"concentration": 5, "understanding": 5, "confidence": 5}, "improving", "visualization"),
            ({}, "stable", "visualization"),
            ({"concentration": None, "understanding": None, "confidence": None}, "insufficient", "visualization"),
            ({"status": "in_progress", "understanding": 1, "confidence": 5}, "pending", "visualization"),
        ]
        for changes, state, support in cases:
            with self.subTest(changes=changes):
                result = self.analyze(self.sample(**changes), self.history())
                self.assertEqual((result["state"], result["support_type"]), (state, support))
                self.assertTrue(result["reason"])
                self.assertTrue(result["action"])
                self.assertEqual(result["version"], "state-v1")

    def test_gap_boundary_and_test_precedence(self):
        for confidence, score in [(4, 37.5), (2, 62.5)]:
            result = self.analyze(self.sample(confidence=confidence, after_test_score=score))
            self.assertEqual(result["state"], "calibration")
            self.assertEqual(abs(result["gap"]), 1.5)
        self.assertEqual(self.analyze(self.sample(confidence=4, after_test_score=37.5001))["state"], "stable")
        fallback = self.analyze(self.sample(understanding=2, confidence=5))
        self.assertEqual(fallback["gap_basis"], "理解度の自己評価")
        measured = self.analyze(self.sample(understanding=2, confidence=5, after_test_score=100))
        self.assertEqual(measured["state"], "understanding")
        self.assertEqual(measured["gap"], 0)

    def test_low_rating_thresholds_and_partial_data(self):
        for key, state in [("understanding", "understanding"), ("concentration", "execution"), ("confidence", "confidence")]:
            with self.subTest(key=key):
                self.assertEqual(self.analyze(self.sample(**{key: 2}))["state"], state)
                self.assertEqual(self.analyze(self.sample(**{key: 3}))["state"], "stable")
        self.assertEqual(self.analyze(self.sample(concentration=None, understanding=2, confidence=None))["state"], "understanding")
        self.assertEqual(self.analyze(self.sample(concentration=None))["state"], "insufficient")

    def test_history_weight_and_minimum_sample_threshold(self):
        for count, baseline, state, adjusted in [(0, 4, "stable", None), (2, 5, "stable", -0.8),
                                                 (3, 4, "stable", -0.6), (3, 5, "understanding", -1.2),
                                                 (5, 4, "understanding", -1.0)]:
            with self.subTest(count=count, baseline=baseline):
                result = self.analyze(self.sample(), self.history(count, understanding=baseline))
                self.assertEqual(result["state"], state)
                metric = self.metric(result, "understanding")
                if adjusted is None:
                    self.assertIsNone(metric["adjusted_delta"])
                else:
                    self.assertAlmostEqual(metric["adjusted_delta"], adjusted)
        self.assertEqual(self.analyze(self.sample(), self.history())["comparable_count"], 5)
        self.assertIn("暫定", self.analyze()["label"])

    def test_rule_priority_is_deterministic(self):
        self.assertEqual(self.analyze(self.sample(concentration=1, understanding=1, confidence=5))["state"], "calibration")
        self.assertEqual(self.analyze(self.sample(concentration=1, understanding=1, confidence=1))["state"], "understanding")
        self.assertEqual(self.analyze(self.sample(concentration=1, understanding=3, confidence=2))["state"], "execution")

    def test_missing_invalid_values_and_zero_are_distinct(self):
        rows = self.history()
        for index, value in enumerate([None, "bad", float("nan"), 6, 4]):
            rows[index]["understanding"] = value
        for index, value in enumerate([None, float("inf"), -1, 101, 0]):
            rows[index]["after_test_score"] = value
        result = self.analyze(self.sample(after_test_score=0), rows)
        understanding = self.metric(result, "understanding")
        self.assertEqual((understanding["count"], understanding["baseline"]), (1, 4))
        score = self.metric(result, "after_test_score")
        self.assertEqual((score["current"], score["count"], score["baseline"], score["delta"]), (0, 1, 0, 0))
        invalid = self.analyze(self.sample(concentration=True, understanding="nan", confidence=3.5))
        self.assertEqual(invalid["state"], "insufficient")

    def test_individual_metric_counts_control_evidence(self):
        rows = self.history()
        rows[0]["confidence"] = None
        rows[1]["confidence"] = None
        result = self.analyze(self.sample(), rows)
        self.assertEqual(self.metric(result, "understanding")["count"], 5)
        self.assertEqual(self.metric(result, "confidence")["count"], 3)
        self.assertEqual(result["comparable_count"], 3)
        self.assertIn("一部", result["evidence"])

    def test_latest_five_exclude_self_future_category_and_drafts(self):
        rows = self.history(8)
        target = self.sample()
        rows += [target, self.sample(id=101, study_date="2026-10-27"),
                 self.sample(id=90, study_date="2026-10-20", category="数学"),
                 self.sample(id=91, study_date="2026-10-21", status="in_progress")]
        results = self.module.studylog_analyze_logs(list(reversed(rows)))
        self.assertEqual(results[100]["history_ids"], [8, 7, 6, 5, 4])
        self.assertEqual(results[100]["history_count"], 5)
        self.assertEqual(results[90]["history_count"], 0)
        self.assertEqual(results[91]["state"], "pending")
        self.assertEqual(results[101]["history_ids"], [100, 8, 7, 6, 5])

    def test_same_date_id_order_and_backdated_inserts(self):
        rows = [self.sample(id=9, study_date="2026-10-25"), self.sample(id=4),
                self.sample(id=2), self.sample(id=3)]
        results = self.module.studylog_analyze_logs(rows)
        self.assertEqual(results[2]["history_ids"], [9])
        self.assertEqual(results[3]["history_ids"], [2, 9])
        self.assertEqual(results[4]["history_ids"], [3, 2, 9])

    def test_missing_recent_values_do_not_expand_window(self):
        rows = self.history(6)
        for row in rows[1:]:
            row["understanding"] = None
        results = self.module.studylog_analyze_logs(rows + [self.sample()])
        metric = self.metric(results[100], "understanding")
        self.assertEqual(results[100]["history_ids"], [6, 5, 4, 3, 2])
        self.assertEqual(metric["count"], 0)
        self.assertIsNone(metric["baseline"])

    def test_blank_categories_only_compare_with_blank(self):
        rows = [self.sample(id=1, category=None), self.sample(id=2, category=""),
                self.sample(id=3, category="Python"), self.sample(id=4, category="   ")]
        result = self.module.studylog_analyze_logs(rows)
        self.assertEqual(result[4]["history_ids"], [2, 1])
        self.assertEqual(result[3]["history_ids"], [])

    def test_bad_legacy_dates_are_excluded_and_do_not_crash(self):
        rows = [self.sample(id=index + 1, study_date=value) for index, value in enumerate([None, "", "bad", "2026-02-30", "20261025"])]
        results = self.module.studylog_analyze_logs(rows + [self.sample()])
        self.assertEqual(results[100]["history_count"], 0)
        for row in rows:
            self.assertEqual(results[row["id"]]["state"], "insufficient")
            self.assertIn("学習日", results[row["id"]]["reason"])

    def test_time_is_comparison_only_not_judgment(self):
        for minutes in [1, 30, 2147483647]:
            result = self.analyze(self.sample(minutes=minutes), self.history())
            self.assertEqual(result["state"], "stable")
            self.assertEqual(self.metric(result, "minutes")["delta"], minutes - 30)

    def test_completed_draft_ui_and_zero_score_comparison(self):
        first = self.save(after_test_score="0", understanding="1", confidence="1", concentration="1")
        second = self.save(after_test_score="25", understanding="2", confidence="2", concentration="2")
        draft = self.save(save_stage="before", after_test_score="100", confidence="5")
        html = self.client.get("/").get_data(as_text=True)
        sections = AnalysisSections(html).sections
        self.assertEqual(sections[first["id"]][0], "understanding")
        self.assertEqual(sections[second["id"]][0], "understanding")
        self.assertEqual(sections[draft["id"]][0], "pending")
        self.assertIn("0.00点", " ".join(sections[second["id"]]))
        self.assertIn("+25.00点", " ".join(sections[second["id"]]))
        self.assertNotIn("None", html)

    def test_filters_do_not_change_analysis_or_baseline(self):
        for index in range(5):
            self.save(study_date=f"2026-10-{10 + index:02d}", understanding="4", confidence="4", after_test_score="75")
        current = self.save(study_date="2026-10-26", concentration="3", understanding="3", confidence="3", after_test_score="50")
        all_sections = AnalysisSections(self.client.get("/").get_data(as_text=True)).sections
        filtered = self.client.get("/?category=Python&range=custom&start_date=2026-10-26&end_date=2026-10-26")
        filtered_sections = AnalysisSections(filtered.get_data(as_text=True)).sections
        self.assertEqual(list(filtered_sections), [current["id"]])
        self.assertEqual(filtered_sections[current["id"]], all_sections[current["id"]])
        self.assertEqual(filtered_sections[current["id"]][0], "understanding")
        self.assertIn("5件", " ".join(filtered_sections[current["id"]]))

    def test_edit_delete_and_restart_recompute_without_stale_results(self):
        for index in range(5):
            self.save(study_date=f"2026-10-{10 + index:02d}", concentration="5", understanding="5", confidence="5", after_test_score="100")
        latest = self.save(concentration="3", understanding="3", confidence="3", after_test_score="50")
        def result():
            return self.module.studylog_analyze_logs(self.rows())[latest["id"]]
        self.assertEqual(result()["state"], "understanding")
        for log_id in range(1, 6):
            response = self.client.post(f"/update/{log_id}", data={"understanding": "3", "confidence": "3", "concentration": "3", "after_test_score": "50"})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(result()["state"], "stable")
        self.load_app()
        self.assertEqual(result()["state"], "stable")
        self.assertEqual(self.client.post("/delete/1").status_code, 302)
        self.assertEqual(result()["history_count"], 4)
        self.assertNotIn(1, result()["history_ids"])

    def test_display_and_analysis_do_not_modify_rows_or_next_action(self):
        self.save(next_action="自分で決めた計画")
        self.save(save_stage="before")
        before = self.rows()
        for _ in range(3):
            self.assertEqual(self.client.get("/").status_code, 200)
            self.module.studylog_analyze_logs(self.rows())
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.rows()[0]["next_action"], "自分で決めた計画")

    def test_analysis_adds_no_per_log_database_queries(self):
        for index in range(8):
            self.save(study_date=f"2026-10-{index + 1:02d}")
        statements = []
        connect = self.module.studylog_plus_get_conn
        def traced_connect():
            conn = connect()
            conn.set_trace_callback(statements.append)
            return conn
        with patch.object(self.module, "studylog_plus_get_conn", traced_connect):
            self.assertEqual(self.client.get("/").status_code, 200)
        selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        self.assertEqual(len(selects), 3, selects)
