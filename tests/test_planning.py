"""次回計画の境界、本人の基準、画面から次の記録への引き継ぎを検証する。"""
from copy import deepcopy
from datetime import date, timedelta
from html.parser import HTMLParser

from test_studylog import StudylogFixture


class PlanSections(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.sections = {}
        self.log_id = None
        self.depth = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and "next-plan" in attrs.get("class", "").split():
            self.log_id = int(attrs["data-log-id"])
            self.sections[self.log_id] = []
            self.depth = 1
        elif self.log_id is not None and tag == "div":
            self.depth += 1

    def handle_data(self, value):
        if self.log_id is not None and value.strip():
            self.sections[self.log_id].append(value.strip())

    def handle_endtag(self, tag):
        if self.log_id is not None and tag == "div":
            self.depth -= 1
            if not self.depth:
                self.log_id = None


class PlanningTest(StudylogFixture):
    def sample(self, **changes):
        row = dict(id=100, study_date="2026-10-26", category="Python", status="completed",
                   minutes=30, planned_minutes=30, concentration=3, understanding=3,
                   confidence=3, after_test_score=None, next_action="", task="例題",
                   goal="元の目標", strategy="自分の方法")
        row.update(changes)
        return row

    def history(self, count=5, **changes):
        return [self.sample(id=index + 1,
                            study_date=(date(2026, 10, 1) + timedelta(days=index)).isoformat(),
                            **changes) for index in range(count)]

    def plan(self, row, history=()):
        return self.module.studylog_build_next_plan(
            row, self.module.studylog_analyze_log(row, list(history)))

    def save(self, **changes):
        data = self.completed()
        data.update(changes)
        self.assertEqual(self.client.post("/add", data=data).status_code, 302)
        return self.rows()[-1]

    def plans(self):
        rows = self.rows()
        analyses = self.module.studylog_analyze_logs(rows)
        return {row["id"]: self.module.studylog_build_next_plan(row, analyses[row["id"]]) for row in rows}

    def test_each_state_generates_a_structured_plan(self):
        for changes, fragment in [
            ({"confidence": 5, "after_test_score": 0}, "予想と結果"),
            ({"understanding": 2, "confidence": 2}, "例題を1問"),
            ({"concentration": 2}, "一つの課題"),
            ({"confidence": 2}, "できたこと"),
            ({}, "元の目標"),
        ]:
            with self.subTest(changes=changes):
                row = self.sample(**changes)
                result = self.plan(row)
                self.assertTrue(result["enabled"])
                self.assertIn(fragment, result["goal"])
                self.assertTrue(result["strategy"])
                self.assertTrue(result["reason"])
                self.assertEqual(result["version"], "plan-v1")
                self.assertEqual(result["category"], "Python")

    def test_reduction_is_smaller_with_less_personal_history(self):
        row = self.sample(understanding=2, confidence=2, planned_minutes=100)
        for count, expected in [(0, 90), (2, 84), (3, 81), (5, 75)]:
            with self.subTest(count=count):
                self.assertEqual(self.plan(row, self.history(count))["minutes"], expected)

    def test_increase_requires_progress_enough_history_and_all_high_ratings(self):
        good = self.sample(concentration=5, understanding=5, confidence=5, planned_minutes=100)
        for count, expected in [(0, 100), (2, 100), (3, 106), (5, 110)]:
            with self.subTest(count=count):
                history = self.history(count, concentration=3, understanding=3, confidence=3)
                self.assertEqual(self.plan(good, history)["minutes"], expected)
        self.assertEqual(self.plan(self.sample(planned_minutes=100), self.history(5, concentration=1, understanding=1))["minutes"], 100)
        self.assertEqual(self.plan(good, self.history(5, concentration=5, understanding=5, confidence=5))["minutes"], 100)

    def test_rounding_and_limits_are_valid_for_tiny_and_extreme_plans(self):
        for base, expected in [(1, 1), (5, 5), (30, 27), (2147483647, 480)]:
            with self.subTest(base=base):
                self.assertEqual(self.plan(self.sample(planned_minutes=base, concentration=2))["minutes"], expected)
        reduced = self.plan(self.sample(planned_minutes=30, concentration=2), self.history())
        self.assertEqual(reduced["minutes"], 23)
        increased = self.plan(self.sample(planned_minutes=480, concentration=5, understanding=5, confidence=5), self.history())
        self.assertEqual(increased["minutes"], 480)

    def test_time_basis_prefers_plan_then_personal_average_then_actual(self):
        history = self.history(3, minutes=60)
        self.assertEqual(self.plan(self.sample(planned_minutes=40), history)["base_minutes"], 40)
        missing = self.sample(planned_minutes=None, minutes=20)
        self.assertEqual(self.plan(missing, history)["base_minutes"], 60)
        self.assertEqual(self.plan(missing, history[:2])["base_minutes"], 20)
        self.assertIn("過去3件", self.plan(missing, history)["reason"])
        for invalid in [None, "bad", 0, -1, 1.5, True, float("inf")]:
            self.assertEqual(self.plan(self.sample(planned_minutes=invalid), history)["base_minutes"], 60)

    def test_time_alone_does_not_change_good_or_bad_state(self):
        for minutes in (1, 30, 2147483647):
            result = self.plan(self.sample(minutes=minutes), self.history())
            self.assertEqual(result["minutes"], 30)
            self.assertEqual(result["factor"], 1)

    def test_own_next_action_is_kept_and_input_objects_are_not_mutated(self):
        row = self.sample(next_action="自分で選んだ次の目標", concentration=2)
        history = self.history()
        original = deepcopy((row, history))
        result = self.plan(row, history)
        self.assertEqual(result["goal"], "自分で選んだ次の目標")
        self.assertIn("短い学習時間", result["strategy"])
        self.assertEqual((row, history), original)
        self.assertEqual(self.plan(self.sample())["strategy"], "自分の方法")

    def test_drafts_bad_dates_missing_results_and_bad_legacy_times_wait(self):
        for changes in [
            {"status": "in_progress"}, {"study_date": "20260230"}, {"study_date": None},
            {"minutes": None}, {"minutes": "bad"}, {"minutes": 0},
            {"concentration": None, "understanding": None, "confidence": None},
        ]:
            with self.subTest(changes=changes):
                result = self.plan(self.sample(**changes))
                self.assertFalse(result["enabled"])
                self.assertTrue(result["reason"])

    def test_preview_then_save_new_draft_keeps_source_and_does_not_copy_results(self):
        source = self.save(concentration="2", understanding="3", confidence="3", after_test_score="50")
        original = self.rows()
        for _ in range(3):
            data = self.form(f"/?plan_from={source['id']}")
            self.assertEqual(self.rows(), original)
            self.assertEqual(data["planned_minutes"], "27")
            self.assertEqual(data["goal"], source["next_action"])
            for key in ("minutes", "concentration", "before_understanding", "before_test_score", "after_test_score", "memo"):
                self.assertEqual(data[key], "", key)
        data.update(study_date="2026-10-27", save_stage="before")
        self.assertEqual(self.client.post("/add", data=data).status_code, 302)
        source_after, draft = self.rows()
        self.assertEqual(source_after, source)
        self.assertEqual(draft["status"], "in_progress")
        self.assertEqual(draft["planned_minutes"], 27)
        self.assertIsNone(draft["minutes"])
        self.assertEqual(draft["strategy"], data["strategy"])
        self.load_app()
        self.assertEqual(self.rows()[1], draft)

    def test_previewed_plan_is_editable_and_validation_preserves_user_input(self):
        source = self.save()
        data = self.form(f"/?plan_from={source['id']}")
        data.update(planned_minutes="0", task="利用者が修正した内容", save_stage="before")
        response = self.client.post(f"/add?plan_from={source['id']}", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("利用者が修正した内容", response.get_data(as_text=True))
        self.assertEqual(len(self.rows()), 1)
        data.update(planned_minutes="17")
        self.assertEqual(self.client.post("/add", data=data).status_code, 302)
        self.assertEqual(self.rows()[1]["planned_minutes"], 17)

    def test_invalid_missing_and_incomplete_source_have_no_side_effects(self):
        source = self.save(save_stage="before")
        original = self.rows()
        for value in ("", "-1", "0", "1.5", "nan", "9" * 100, "1 OR 1=1", "１"):
            with self.subTest(value=value):
                self.assertEqual(self.client.get("/", query_string={"plan_from": value}).status_code, 400)
        self.assertEqual(self.client.get("/?plan_from=999").status_code, 404)
        self.assertEqual(self.client.get(f"/?plan_from={source['id']}").status_code, 400)
        self.assertEqual(self.rows(), original)

    def test_unauthenticated_preview_and_csrf_free_save_are_rejected(self):
        source = self.save()
        original = self.rows()
        anonymous = self.module.app.test_client()
        self.assertEqual(anonymous.get(f"/?plan_from={source['id']}").status_code, 303)
        data = self.form(f"/?plan_from={source['id']}")
        data.update(save_stage="before")
        data.pop("csrf_token")
        self.assertEqual(self.client.post("/add", data=data).status_code, 400)
        self.assertEqual(self.rows(), original)

    def test_category_filters_and_later_records_do_not_change_historical_plan(self):
        for index in range(5):
            self.save(study_date=f"2026-10-{10 + index:02d}", minutes="60", planned_minutes="", understanding="3", confidence="3", after_test_score="50")
        target = self.save(planned_minutes="", minutes="20", understanding="3", confidence="3", after_test_score="50")
        expected = self.plans()[target["id"]]
        self.save(category="別カテゴリ", minutes="1000")
        self.save(study_date="2026-10-27", minutes="1000")
        self.save(save_stage="before", minutes="1000")
        self.assertEqual(self.plans()[target["id"]], expected)
        full = PlanSections(self.client.get("/").get_data(as_text=True)).sections
        filtered = PlanSections(self.client.get("/?category=Python&range=custom&start_date=2026-10-26&end_date=2026-10-26").get_data(as_text=True)).sections
        self.assertEqual(full[target["id"]], filtered[target["id"]])
        self.assertEqual(expected["base_minutes"], 60)

    def test_history_edits_deletion_and_restart_recompute_plan(self):
        for index in range(3):
            self.save(study_date=f"2026-10-{10 + index:02d}", minutes="60", planned_minutes="", understanding="3", confidence="3", after_test_score="50")
        target = self.save(planned_minutes="", minutes="20", understanding="3", confidence="3", after_test_score="50")
        self.assertEqual(self.plans()[target["id"]]["minutes"], 60)
        for log_id in range(1, 4):
            self.assertEqual(self.client.post(f"/update/{log_id}", data={**self.csrf(), "minutes": "30"}).status_code, 302)
        self.assertEqual(self.plans()[target["id"]]["minutes"], 30)
        self.load_app()
        self.assertEqual(self.plans()[target["id"]]["minutes"], 30)
        self.assertEqual(self.client.post("/delete/1", data=self.csrf()).status_code, 302)
        self.assertEqual(self.plans()[target["id"]]["minutes"], 20)
        self.client.post(f"/delete/{target['id']}", data=self.csrf())
        self.assertEqual(self.client.get(f"/?plan_from={target['id']}").status_code, 404)

    def test_reading_plan_many_times_does_not_write_to_database(self):
        self.save()
        original = self.rows()
        for _ in range(3):
            self.assertIn("次回計画の自動補正", self.client.get("/").get_data(as_text=True))
            self.plans()
        self.assertEqual(self.rows(), original)

    def test_plan_content_is_html_escaped_in_display_and_prefill(self):
        attack = '<script>alert("x")</script>'
        source = self.save(task=attack, next_action=attack, strategy=attack)
        for path in ("/", f"/?plan_from={source['id']}"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotIn(attack, html)
            self.assertIn("&lt;script&gt;", html)
