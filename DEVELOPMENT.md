# 開発者向け情報（Studylog 公開版）

利用者向けの概要は [README.md](README.md) を参照してください。ここでは開発者向けの情報（起動・テスト・開発体制）をまとめます。

## 起動（ローカル）
Python 3.12 / 3.13 で動作する基本機能を対象とします。

```bash
pip install -r requirements.txt
# STUDYLOG_PIN / STUDYLOG_SECRET_KEY 等を安全な環境変数として設定
gunicorn soapp:app
```

## テスト
```bash
python -m unittest discover -s tests -v
python tests/http_auth_smoke.py
node tests/theme_runtime.js
```

実行環境の構成や必要な環境変数の詳細はコードを参照してください。認証情報や学習データを GitHub にコミットしないでください。

## 開発体制
公開側は公開可能な機能に限り、変更は専用ブランチからの Pull Request と所有者レビューで統合します。非公開の研究開発コード・未出願の技術情報を公開側へ同期しないでください。

- 公開側: https://github.com/Arbeit2025/studylog
- サービス: https://studylog1.onrender.com/
- 共同開発ルール: [docs/AI_COLLABORATION.md](docs/AI_COLLABORATION.md)
