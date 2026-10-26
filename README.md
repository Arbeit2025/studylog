# studylog

studylog は、Flask と SQLite で作られたシンプルな学習ログアプリです。
  
ブラウザから学習前の計画を保存し、学習後に同じログへ結果を追記できます。
一覧では前後の変化、表示範囲内の合計学習時間、平均集中度・平均理解度を確認できます。

小さくてシンプルな学習ログを目的としています。


Single-file Flask + SQLite study log app.

## Features
- 学習内容、カテゴリ、目標、予定時間、学習方法の保存
- 学習前の集中できそう度・理解度・自信度（1〜5）の保存
- 学習後の実際の時間・集中度・理解度・自信度、振り返りの保存
- 学習前後の確認テスト得点（0〜100点換算、任意入力）の保存
- 学習前だけの保存、途中保存、学習後の追記・編集・削除
- 理解度・自信度・確認テストの前後差、予定時間と実績の比較
- 期間・カテゴリでの絞り込みと、学習完了のログを対象にした時間・平均の集計

## 記録の流れ
1. 学習内容と学習前の計画・評価を入力し、「学習前を保存」を押します。
2. 一覧の「学習後を記録」を開き、実際の学習時間と学習後の結果を入力します。
3. 「学習後まで保存」を押すと、同じログが学習完了になります。

学習後に前後の情報をまとめて保存することもできます。実際の学習時間は
学習完了時に1分以上の整数が必須です。評価と確認テストは任意で、未入力は
未測定として保存します。前後両方が記録された項目だけ差分を表示します。
学習前の集中できそう度は予測値、学習後の集中度は振り返りの評価です。

## データの保存
データはアプリと同じディレクトリの `studylog.db` に保存します。
起動時に `logs` テーブルへ不足する列を追加します。以前の記録は学習完了として
引き継ぎ、存在しない学習前の評価・得点・保存日時は補いません。
旧 `study_logs` テーブルや別DBからの自動移行は行いません。

学習状態は `status`（`in_progress` / `completed`）、前評価は
`before_concentration` / `before_understanding` / `before_confidence`、後評価は
既存の `concentration` / `understanding` / `confidence` に保存します。
得点は `before_test_score` / `after_test_score`、前後の初回保存日時は
`before_saved_at` / `after_saved_at`、最終更新日時は `updated_at` です。
新しい保存日時はUTCのISO 8601形式です。既存の日時はそのまま保持します。

## Run (local)
```bash
pip install -r requirements.txt
python soapp.py
```

## Tests
```bash
python -m unittest discover -s tests -v
```
実アプリを一時ディレクトリへコピーし、FlaskのHTTPルートとSQLiteで検証します。
普段使っているDBは変更しません。追加・前後保存・繰り返し編集・再起動・
旧DBの列追加・入力エラー・集計・絞り込み・削除を確認します。

## Repository
https://studylog1.onrender.com/

