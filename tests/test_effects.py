"""計画の採用履歴と、採用後の結果の継続評価を実アプリ・一時SQLiteで検証する。"""
from copy import deepcopy
import json
import sqlite3
from unittest.mock import patch

from test_studylog import StudylogFixture


class EffectsTest(StudylogFixture):
    def save(self, **changes):
        data = self.completed()
        data.update(changes)
        self.assertEqual(self.client.post('/add', data=data).status_code, 302)
        return self.rows()[-1]

    def adopt(self, source, stage='before', **changes):
        data = self.form(f"/?plan_from={source['id']}")
        data.update(study_date='2026-10-27', save_stage=stage)
        if stage == 'after':
            data.update(minutes='25', concentration='4', understanding='4', confidence='4', after_test_score='75')
        data.update(changes)
        self.assertEqual(self.client.post('/add', data=data).status_code, 302)
        return self.rows()[-1]

    def effect(self, row):
        return self.module.studylog_evaluate_plan(row)

    def summary(self, rows=None):
        rows = self.rows() if rows is None else rows
        effects = {row['id']: self.effect(row) for row in rows}
        return self.module.studylog_summarize_effects(rows, effects)

    def update(self, row, **changes):
        data = self.form(f"/edit/{row['id']}")
        data.update(save_stage='after', **changes)
        self.assertEqual(self.client.post(f"/update/{row['id']}", data=data).status_code, 302)
        return next(item for item in self.rows() if item['id'] == row['id'])

    def test_old_database_migration_preserves_every_existing_value(self):
        with sqlite3.connect(self.root / 'studylog.db') as conn:
            conn.execute('DROP TABLE logs')
            conn.execute('CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, study_date TEXT, minutes INTEGER, concentration INTEGER, understanding INTEGER, memo TEXT, created_at TEXT)')
            conn.execute("INSERT INTO logs VALUES (4, '2026-10-20', 20, 3, 2, '元のメモ', 'old-time')")
        for _ in range(3):
            self.load_app()
            row = self.rows()[0]
            self.assertIsNone(row['plan_tracking'])
            self.assertEqual((row['id'], row['minutes'], row['memo'], row['created_at']), (4, 20, '元のメモ', 'old-time'))
            self.assertFalse(self.effect(row)['tracked'])

    def test_preview_is_signed_and_repeated_gets_do_not_save_an_adoption(self):
        source = self.save(concentration='2')
        original = self.rows()
        for _ in range(3):
            form = self.form(f"/?plan_from={source['id']}")
            payload = self.module.studylog_plan_serializer().loads(form['plan_token'])
            self.assertEqual(payload['source_id'], source['id'])
            self.assertEqual(payload['plan']['minutes'], 27)
            self.assertEqual(payload['source_results']['concentration'], 2)
            self.assertEqual(self.rows(), original)
        self.assertEqual(self.summary()['total'], 0)

    def test_before_completion_and_restart_keep_snapshot_and_show_gains(self):
        source = self.save(concentration='2', understanding='2', confidence='2', after_test_score='0')
        draft = self.adopt(source, before_understanding='2', before_confidence='2', before_test_score='12.5')
        self.assertEqual(self.effect(draft)['state'], 'waiting')
        snapshot = draft['plan_tracking']
        self.load_app()
        self.assertEqual(self.rows()[1]['plan_tracking'], snapshot)
        after = self.update(draft, minutes='25', concentration='4', understanding='4', confidence='4', after_test_score='62.5')
        effect = self.effect(after)
        self.assertEqual(effect['state'], 'evaluated')
        metrics = {m['key']: m for m in effect['metrics']}
        self.assertEqual(metrics['understanding']['gain'], 2)
        self.assertEqual(metrics['after_test_score']['gain'], 50)
        self.assertEqual(metrics['after_test_score']['delta'], 62.5)
        self.assertIsNone(metrics['concentration']['gain'])
        self.assertEqual(after['plan_tracking'], snapshot)
        html = self.client.get('/').get_data(as_text=True)
        for fragment in ('補正効果の継続評価', 'この補正計画の評価', '比較値が上昇', '+62.5点', '比較可能 1件'):
            self.assertIn(fragment, html)

    def test_source_edit_and_delete_do_not_change_the_saved_baseline(self):
        source = self.save(understanding='2', confidence='2', after_test_score='25')
        adopted = self.adopt(source, stage='after')
        original = self.effect(adopted)
        self.update(source, understanding='5', confidence='5', after_test_score='100')
        self.assertEqual(self.effect(self.rows()[1]), original)
        self.assertEqual(self.client.post(f"/delete/{source['id']}", data=self.csrf()).status_code, 302)
        self.load_app()
        self.assertEqual(self.effect(self.rows()[0]), original)
        self.assertEqual(self.summary()['evaluated'], 1)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_preview_snapshot_is_retained_even_if_source_changes_before_save(self):
        source = self.save(understanding='2', confidence='2', after_test_score='25')
        data = self.form(f"/?plan_from={source['id']}")
        self.update(source, understanding='5', confidence='5')
        data.update(study_date='2026-10-27', save_stage='before')
        self.assertEqual(self.client.post('/add', data=data).status_code, 302)
        tracking = json.loads(self.rows()[1]['plan_tracking'])
        self.assertEqual(tracking['source_results']['understanding'], 2)
        self.assertEqual(tracking['plan']['minutes'], 27)

    def test_edited_adoption_and_later_edits_preserve_original_suggestion(self):
        source = self.save(concentration='2')
        adopted = self.adopt(source, stage='after', planned_minutes='17', goal='自分の目標', strategy='自分の方法')
        tracking = json.loads(adopted['plan_tracking'])
        self.assertEqual(tracking['plan']['minutes'], 27)
        self.assertEqual(tracking['adopted_plan']['planned_minutes'], 17)
        self.assertEqual(self.effect(adopted)['adoption_label'], '提案を編集して採用')
        edited = self.update(adopted, planned_minutes='19', plan_tracking='forged', plan_token='forged')
        self.assertEqual(edited['plan_tracking'], adopted['plan_tracking'])
        self.assertIn('採用後にも計画を編集', self.effect(edited)['adoption_label'])
        self.assertEqual(self.summary()['evaluated'], 1)

    def test_complete_at_once_can_be_evaluated_without_before_ratings(self):
        source = self.save()
        adopted = self.adopt(source, stage='after')
        self.assertEqual(self.effect(adopted)['state'], 'evaluated')
        self.assertEqual(self.effect(adopted)['adoption_label'], '提案どおりに採用')
        self.assertTrue(all(m['gain'] is None for m in self.effect(adopted)['metrics']))

    def test_validation_failure_preserves_token_user_input_and_database(self):
        source = self.save()
        data = self.form(f"/?plan_from={source['id']}")
        original = self.rows()
        data.update(planned_minutes='0', goal='編集した目標', save_stage='before')
        response = self.client.post('/add', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows(), original)
        from test_studylog import FormParser
        restored = FormParser(response.get_data(as_text=True)).fields
        self.assertEqual(restored['plan_token'], data['plan_token'])
        self.assertEqual(restored['goal'], '編集した目標')
        restored.update(planned_minutes='18', save_stage='before')
        self.assertEqual(self.client.post('/add', data=restored).status_code, 302)
        self.assertIsNotNone(self.rows()[1]['plan_tracking'])

    def test_forged_invalid_oversize_and_old_key_tokens_are_rejected_atomically(self):
        source = self.save()
        data = self.form(f"/?plan_from={source['id']}")
        original = self.rows()
        tokens = ['broken', data['plan_token'] + 'x', 'x' * 65537,
                  self.module.studylog_plan_serializer().dumps({'version': 'effect-v1'})]
        for token in tokens:
            with self.subTest(token_length=len(token)):
                self.assertEqual(self.client.post('/add', data={**data, 'plan_token': token, 'save_stage': 'before'}).status_code, 400)
                self.assertEqual(self.rows(), original)
        self.module.app.config['SECRET_KEY'] = 'another-secret-key-with-at-least-32-characters'
        self.client = self.module.app.test_client()
        from test_studylog import FormParser
        login = FormParser(self.client.get('/login').get_data(as_text=True)).fields
        self.client.post('/login', data={**login, 'pin': '4826'})
        self.assertEqual(self.client.post('/add', data={**data, **self.csrf(), 'save_stage': 'before'}).status_code, 400)
        self.assertEqual(self.rows(), original)

    def test_source_deleted_before_adoption_is_rejected_without_partial_save(self):
        source = self.save()
        data = self.form(f"/?plan_from={source['id']}")
        self.client.post(f"/delete/{source['id']}", data=self.csrf())
        response = self.client.post('/add', data={**data, 'save_stage': 'before'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('比較元のログが削除', response.get_data(as_text=True))
        self.assertEqual(self.rows(), [])

    def test_manual_logs_and_unsolicited_tracking_fields_do_not_invent_adoption(self):
        source = self.save(plan_tracking='forged', plan_from='1')
        self.assertIsNone(source['plan_tracking'])
        self.assertFalse(self.effect(source)['tracked'])
        self.assertEqual(self.summary()['total'], 0)

    def test_missing_scores_and_zero_decimal_scores_have_per_metric_counts(self):
        source = self.save(concentration='', understanding='2', confidence='', after_test_score='0')
        adopted = self.adopt(source, stage='after', concentration='3', understanding='', confidence='3', after_test_score='0.5')
        metrics = {m['key']: m for m in self.effect(adopted)['metrics']}
        self.assertEqual(metrics['after_test_score']['delta'], .5)
        for field in ('concentration', 'understanding', 'confidence'):
            self.assertIsNone(metrics[field]['delta'])
        summary = {m['key']: m for m in self.summary()['groups'][0]['metrics']}
        self.assertEqual(summary['after_test_score']['count'], 1)
        self.assertEqual(summary['understanding']['count'], 0)

    def test_no_paired_data_or_invalid_legacy_values_are_excluded(self):
        source = self.save()
        adopted = self.adopt(source, stage='after')
        original = deepcopy(adopted)
        tracking = json.loads(adopted['plan_tracking'])
        for field in tracking['source_results']:
            tracking['source_results'][field] = 'invalid'
        adopted['plan_tracking'] = json.dumps(tracking)
        adopted.update(concentration=-1, understanding=99, confidence='nan', after_test_score=float('inf'))
        result = self.effect(adopted)
        self.assertEqual(result['state'], 'excluded')
        self.assertTrue(all(m['delta'] is None for m in result['metrics']))
        self.assertEqual(self.effect(original)['state'], 'evaluated')

    def test_labels_describe_observed_changes_and_never_use_time_as_success(self):
        source = self.save(concentration='3', understanding='3', confidence='3', after_test_score='50')
        adopted = self.adopt(source, stage='after')
        cases = [({'concentration': 4, 'understanding': 4, 'confidence': 4, 'after_test_score': 75}, '比較値が上昇'),
                 ({'concentration': 2, 'understanding': 2, 'confidence': 2, 'after_test_score': 25}, '比較値が低下'),
                 ({'concentration': 2, 'understanding': 4, 'confidence': 3, 'after_test_score': 50}, '上昇・低下が混在'),
                 ({'concentration': 3, 'understanding': 3, 'confidence': 3, 'after_test_score': 50}, '比較値に変化なし')]
        for changes, label in cases:
            for minutes in (1, 2147483647):
                self.assertEqual(self.effect({**adopted, **changes, 'minutes': minutes})['label'], label)

    def test_category_change_and_dates_before_source_are_excluded(self):
        source = self.save()
        adopted = self.adopt(source, stage='after')
        for changes in ({'category': '別カテゴリ'}, {'study_date': '2026-10-25'},
                        {'study_date': 'bad'}, {'study_date': None}, {'id': source['id']}):
            self.assertEqual(self.effect({**adopted, **changes})['state'], 'excluded')
        self.assertEqual(self.effect({**adopted, 'study_date': source['study_date']})['state'], 'evaluated')
        self.assertEqual(self.effect({**adopted, 'category': ' Python '})['state'], 'evaluated')

    def test_multiple_sessions_categories_filtering_and_recent_order(self):
        source = self.save(concentration='3', understanding='3', confidence='3', after_test_score='50')
        for day in range(27, 33):
            self.adopt(source, stage='after', study_date=f'2026-11-{day-26:02d}', after_test_score='' if day == 27 else '75')
        other = self.save(category='中国語')
        self.adopt(other, stage='after')
        summary = self.summary()
        self.assertEqual((summary['total'], summary['evaluated']), (7, 7))
        groups = {g['category']: g for g in summary['groups']}
        python = groups['Python']
        self.assertEqual(len(python['recent']), 5)
        self.assertEqual([r['id'] for r in python['recent']], [7, 6, 5, 4, 3])
        metrics = {m['key']: m for m in python['metrics']}
        self.assertEqual((metrics['after_test_score']['count'], metrics['after_test_score']['mean']), (5, 25))
        self.assertEqual(metrics['understanding']['count'], 6)
        html = self.client.get('/?category=中国語').get_data(as_text=True)
        self.assertIn('補正計画から保存 1件', html)
        filtered = [r for r in self.rows() if r['category'] == '中国語']
        self.assertEqual(self.summary(filtered)['evaluated'], 1)

    def test_repeated_result_edits_deletion_and_restart_recalculate_without_duplicates(self):
        source = self.save(understanding='2', confidence='2')
        adopted = self.adopt(source, stage='after')
        for value in ('3', '4', '5'):
            adopted = self.update(adopted, understanding=value)
            metric = next(m for m in self.summary()['groups'][0]['metrics'] if m['key'] == 'understanding')
            self.assertEqual((metric['count'], metric['mean']), (1, int(value) - 2))
        self.load_app()
        self.assertEqual(self.summary()['evaluated'], 1)
        self.client.post(f"/delete/{adopted['id']}", data=self.csrf())
        self.assertEqual(self.summary()['total'], 0)

    def test_chained_plans_compare_each_session_to_its_own_adoption_source(self):
        first = self.save(understanding='2', confidence='2')
        second = self.adopt(first, stage='after', understanding='3', confidence='3')
        third = self.adopt(second, stage='after', study_date='2026-10-28', understanding='4')
        for row in (second, third):
            metric = next(m for m in self.effect(row)['metrics'] if m['key'] == 'understanding')
            self.assertEqual(metric['delta'], 1)
        self.assertEqual(self.summary()['evaluated'], 2)

    def test_authentication_csrf_and_read_only_views_preserve_tracking(self):
        source = self.save()
        data = self.form(f"/?plan_from={source['id']}")
        anonymous = self.module.app.test_client()
        self.assertEqual(anonymous.get(f"/?plan_from={source['id']}").status_code, 303)
        self.assertEqual(anonymous.post('/add', data={**data, 'save_stage': 'before'}).status_code, 303)
        data.pop('csrf_token')
        self.assertEqual(self.client.post('/add', data={**data, 'save_stage': 'before'}).status_code, 400)
        adopted = self.adopt(source, stage='after')
        original = self.rows()
        for _ in range(3):
            self.client.get('/')
            self.client.get(f"/edit/{adopted['id']}")
            self.summary()
        self.assertEqual(self.rows(), original)

    def test_corrupt_tracking_is_safe_and_snapshot_text_is_html_escaped(self):
        source = self.save(goal='<script>alert(1)</script>', strategy='<img src=x onerror=alert(1)>', next_action='')
        adopted = self.adopt(source, stage='after')
        html = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('<img src=x onerror=alert(1)>', html)
        self.assertIn('&lt;script&gt;', html)
        for raw in ('not-json', 'null', '[]', '{}', '{"version":"future"}', '3'):
            self.assertEqual(self.effect({**adopted, 'plan_tracking': raw})['state'], 'excluded')
        tracking = json.loads(adopted['plan_tracking'])
        for key in ('plan', 'adopted_plan', 'source_results', 'source_date'):
            damaged = deepcopy(tracking)
            damaged[key] = None
            self.assertEqual(self.effect({**adopted, 'plan_tracking': json.dumps(damaged)})['state'], 'excluded')
        damaged = deepcopy(tracking)
        del damaged['adopted_plan']['planned_minutes']
        with sqlite3.connect(self.root / 'studylog.db') as conn:
            conn.execute('UPDATE logs SET plan_tracking = ? WHERE id = ?', (json.dumps(damaged), adopted['id']))
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.summary()['excluded'], 1)

    def test_evaluation_does_not_add_queries_per_tracked_log(self):
        source = self.save()
        original_connect = self.module.studylog_plus_get_conn
        statements = []
        def connect():
            conn = original_connect()
            conn.set_trace_callback(lambda sql: statements.append(sql) if sql.startswith('SELECT') else None)
            return conn
        def count_queries():
            statements.clear()
            with patch.object(self.module, 'studylog_plus_get_conn', side_effect=connect):
                self.assertEqual(self.client.get('/').status_code, 200)
            return len(statements)
        before = count_queries()
        for _ in range(5):
            self.adopt(source, stage='after')
        self.assertEqual(count_queries(), before)
