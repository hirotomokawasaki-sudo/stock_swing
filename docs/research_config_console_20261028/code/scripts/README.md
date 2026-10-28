# scripts/ - 運用スクリプトディレクトリ

このディレクトリには、stock_swingシステムの運用・メンテナンス用スクリプトが格納されています。

## ディレクトリ構造

```
scripts/
├── README.md              # このファイル
├── cron/                  # Cronジョブ用スクリプト
├── maintenance/           # メンテナンススクリプト
├── setup/                 # セットアップスクリプト
└── utils/                 # ユーティリティスクリプト
```

## カテゴリ別スクリプト

### 📅 cron/ - Cronジョブ用

定期実行用のスクリプト。OpenClawのCronジョブから呼び出される。

- `collect_data.sh` - データ収集（2時間ごと）
- `run_strategies.sh` - 戦略実行（計画中）
- `reconcile.sh` - ブローカー照合（計画中）

### 🔧 maintenance/ - メンテナンス用

システムの保守・管理用スクリプト。

- `backup_data.sh` - データバックアップ
- `clean_old_data.sh` - 古いデータの削除
- `health_check.sh` - システムヘルスチェック
- `broker_health_check.sh` - デモトレード用ブローカー接続チェック

### 🚀 setup/ - セットアップ用

初期設定・環境構築用スクリプト。

- `init_env.sh` - 環境初期化
- `install_deps.sh` - 依存関係インストール
- `configure_api.sh` - APIキー設定補助

### 🛠️ utils/ - ユーティリティ

その他の便利スクリプト。

- `backup_cron_jobs.sh` - ✅ Cron Jobsバックアップ
- `export_reports.sh` - レポート出力（計画中）
- `validate_data.sh` - データ検証（計画中）
- `test_connections.sh` - API接続テスト（計画中）

## Python CLI vs Shell Scripts

### Python CLI (`src/stock_swing/cli/`)
システム機能への直接的なアクセス。

```bash
# Python CLIの例
cd ~/stock_swing
source venv/bin/activate
python -m stock_swing.cli.collect_data --symbols AAPL
```

### Shell Scripts (`scripts/`)
運用タスクのラッパー。環境設定やエラーハンドリングを含む。

```bash
# Shell scriptの例
~/stock_swing/scripts/cron/collect_data.sh
```

## 実行方法

### 手動実行
```bash
cd ~/stock_swing
./scripts/cron/collect_data.sh
```

### Cron経由
OpenClawのCronジョブに登録済み（2時間ごとX:40分）

```bash
openclaw cron list
```

## 開発ガイドライン

### 新しいスクリプトを追加する場合

1. **適切なカテゴリを選択**
   - 定期実行 → `cron/`
   - メンテナンス → `maintenance/`
   - セットアップ → `setup/`
   - その他 → `utils/`

2. **スクリプトヘッダーを含める**
   ```bash
   #!/bin/bash
   # Description: スクリプトの説明
   # Usage: ./script_name.sh [options]
   ```

3. **実行権限を付与**
   ```bash
   chmod +x scripts/category/script_name.sh
   ```

4. **このREADMEを更新**
   新しいスクリプトを追加したら、このREADMEに記載する。

## メンテナンス

- 使用しなくなったスクリプトは削除するか`deprecated/`に移動
- スクリプトの変更は必ずGitにコミット
- Cronジョブの変更は`openclaw cron`コマンドで管理

---

最終更新: 2026-03-27
