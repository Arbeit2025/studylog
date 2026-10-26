"""7機能を実HTTPサーバーと独立した一時DBで3回確認する。"""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error

from http_auth_smoke import browser, request, check
from test_studylog import FormParser


def run_once(index):
    with tempfile.TemporaryDirectory(prefix='studylog-http-effects-') as directory:
        root = Path(directory)
        shutil.copy2(Path(__file__).resolve().parents[1] / 'soapp.py', root / 'soapp.py')
        environment = os.environ.copy()
        environment.update(STUDYLOG_PIN='4826', STUDYLOG_SECRET_KEY=secrets.token_hex(32), STUDYLOG_COOKIE_SECURE='0')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        process = None

        def start():
            nonlocal process
            code = ('from werkzeug.serving import make_server; from soapp import app; '
                    f"make_server('127.0.0.1', {port}, app).serve_forever()")
            process = subprocess.Popen([sys.executable, '-c', code], cwd=root, env=environment,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                check(process.poll() is None, 'HTTP server exited early')
                try:
                    if request(browser(), base, '/login')[0] == 200:
                        return
                except (OSError, urllib.error.URLError):
                    time.sleep(.05)
            raise AssertionError('HTTP server not ready')

        def stop():
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

        def form(path='/'):
            status, _, html = request(client, base, path)
            check(status == 200, f'form failed: {path}')
            return FormParser(html).fields

        def rows():
            with sqlite3.connect(root / 'studylog.db') as conn:
                conn.row_factory = sqlite3.Row
                return [dict(row) for row in conn.execute('SELECT * FROM logs ORDER BY id')]

        try:
            start()
            client = browser()
            check(request(client, base, '/')[0] == 303, 'entry not protected')
            login = form('/login')
            check(request(client, base, '/login', {**login, 'pin': '4826'})[0] == 303, 'login failed')
            for day in range(10, 15):
                data = form()
                data.update(study_date=f'2026-10-{day}', category='HTTP確認', task='過去の例題',
                            planned_minutes='40', minutes='40', concentration='4', understanding='4',
                            confidence='4', after_test_score='75', save_stage='after')
                check(request(client, base, '/add', data)[0] == 302, 'history save failed')
            data = form()
            data.update(study_date='2026-10-26', category='HTTP確認', task='今回の例題', planned_minutes='40',
                        before_understanding='1', before_test_score='0', save_stage='before')
            check(request(client, base, '/add', data)[0] == 302, 'before save failed')
            stop()
            start()
            data = form('/edit/6')
            check(data['before_test_score'] == '0.0', 'before data lost')
            data.update(minutes='35', concentration='3', understanding='2', confidence='2', after_test_score='25', save_stage='after')
            check(request(client, base, '/update/6', data)[0] == 302, 'after save failed')
            html = request(client, base, '/')[2]
            for fragment in ('個人別の判定基準', '理解の停滞候補', '同じカテゴリの過去5件', '次回の予定時間: 30分', '変化 +25点'):
                check(fragment in html, f'feature display missing: {fragment}')
            source = rows()[5]
            original = rows()
            for _ in range(3):
                adopted_form = form('/?plan_from=6')
                check(adopted_form['planned_minutes'] == '30' and bool(adopted_form['plan_token']), 'preview lacks tracking')
                check(rows() == original, 'preview mutated DB')
            adopted_form.update(study_date='2026-10-27', planned_minutes='28', before_understanding='2',
                                before_test_score='12.5', save_stage='before')
            invalid = {**adopted_form, 'plan_token': adopted_form['plan_token'] + 'x'}
            check(request(client, base, '/add', invalid)[0] == 400, 'forged token accepted')
            check(rows() == original, 'invalid adoption partially saved')
            check(request(client, base, '/add', adopted_form)[0] == 302, 'adoption save failed')
            saved = rows()[6]
            snapshot = saved['plan_tracking']
            tracking = json.loads(snapshot)
            check(tracking['plan']['minutes'] == 30 and tracking['adopted_plan']['planned_minutes'] == 28, 'edited adoption lost')
            check('学習後待ち 1件' in request(client, base, '/')[2], 'draft counted as evaluated')
            stop()
            start()
            data = form('/edit/7')
            check(data['before_test_score'] == '12.5', 'before score lost at restart')
            data.update(minutes='28', concentration='4', understanding='4', confidence='4', after_test_score='62.5', save_stage='after')
            check(request(client, base, '/update/7', data)[0] == 302, 'result save failed')
            for value in ('3', '5', '4'):
                data = form('/edit/7')
                data.update(understanding=value, save_stage='after')
                check(request(client, base, '/update/7', data)[0] == 302, 'repeated result edit failed')
                check('比較可能 1件' in request(client, base, '/')[2], 'repeated edit inflated adoption count')
            html = request(client, base, '/')[2]
            for fragment in ('補正効果の継続評価', 'この補正計画の評価', '比較値が上昇', '+37.5点', '+50点', '提案を編集して採用'):
                check(fragment in html, f'evaluation display missing: {fragment}')
            check(rows()[6]['plan_tracking'] == snapshot and rows()[5] == source, 'snapshot or source modified')
            data = form('/?plan_from=7')
            data.update(study_date='2026-10-28', minutes='25', concentration='4', understanding='4', confidence='4',
                        after_test_score='75', save_stage='after')
            check(request(client, base, '/add', data)[0] == 302, 'second adoption failed')
            check('比較可能 2件' in request(client, base, '/')[2], 'continuous evaluation did not add session')
            filtered = request(client, base, '/?range=custom&start_date=2026-10-28&end_date=2026-10-28')[2]
            check('補正計画から保存 1件' in filtered, 'evaluation filter ignored')
            check(request(client, base, '/delete/6', {'csrf_token': form()['csrf_token']})[0] == 302, 'source delete failed')
            stop()
            start()
            html = request(client, base, '/')[2]
            check('比較可能 2件' in html and '+37.5点' in html, 'source delete or restart changed baseline')
            check(next(r for r in rows() if r['id'] == 7)['plan_tracking'] == snapshot, 'snapshot lost')
            check(request(browser(), base, '/update/7', {})[0] == 303, 'anonymous update accepted')
            check(request(client, base, '/delete/7', {})[0] == 400, 'delete skipped CSRF')
            for row in rows():
                check(request(client, base, f"/delete/{row['id']}", {'csrf_token': form()['csrf_token']})[0] == 302, 'cleanup failed')
            check('補正計画から保存 0件' in request(client, base, '/')[2] and rows() == [], 'cleanup left evaluations')
            print(f'HTTP seven-feature smoke {index}/3: PASS', flush=True)
        finally:
            stop()


if __name__ == '__main__':
    for run in range(1, 4):
        run_once(run)
