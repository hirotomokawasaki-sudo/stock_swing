# cron_backup/ - OpenClaw Cron Jobs バックアップ

このディレクトリには、OpenClawのCron Jobsのバックアップが保存されます。

## 📁 ファイル

- `jobs.json` - OpenClawのCron Jobs設定のバックアップ
  - ソース: `~/.openclaw/cron/jobs.json`
  - GitHubで管理

## 🔄 バックアップ方法

### 手動バックアップ
```bash
cp ~/.openclaw/cron/jobs.json ~/stock_swing/cron_backup/jobs.json
cd ~/stock_swing
git add cron_backup/jobs.json
git commit -m "chore: backup cron jobs"
git push origin main
```

### 自動バックアップスクリプト
```bash
~/stock_swing/scripts/utils/backup_cron_jobs.sh
```

## 📋 現在のCron Jobs

### stock_swing_data_collection
- **ID**: `4d76bf16-bd96-4ff3-b5db-a735f62c2d35`
- **スケジュール**: 2時間ごとの40分 (`40 */2 * * *`)
- **タイムゾーン**: Asia/Tokyo
- **機能**: データ収集（Finnhub, FRED, SEC, Broker）
- **対象シンボル**: AAPL, MSFT, GOOGL, AMZN, TSLA

## 🔧 リストア方法

Cron Jobsをリストアする場合:

```bash
# 1. バックアップから復元
cp ~/stock_swing/cron_backup/jobs.json ~/.openclaw/cron/jobs.json

# 2. OpenClaw gatewayを再起動
openclaw gateway restart
```

⚠️ **注意**: リストアすると既存のCron Jobsが上書きされます。

## 📝 変更時の手順

Cron Jobを追加・削除・変更した場合:

1. **バックアップ**
   ```bash
   cp ~/.openclaw/cron/jobs.json ~/stock_swing/cron_backup/jobs.json
   ```

2. **Git commit & push**
   ```bash
   cd ~/stock_swing
   git add cron_backup/jobs.json
   git commit -m "chore: update cron jobs - [変更内容]"
   git push origin main
   ```

3. **このREADMEを更新**
   新しいジョブを追加した場合、上記の「現在のCron Jobs」セクションを更新

## 🔍 Cron Jobs管理コマンド

```bash
# リスト表示
openclaw cron list

# ステータス確認
openclaw cron status

# ジョブ追加
openclaw cron add --job '{...}'

# ジョブ削除
openclaw cron remove --id <job-id>

# 実行履歴
openclaw cron runs --id <job-id>
```

## 🚨 重要

- Cron Jobsの変更は必ずバックアップ
- バックアップは必ずGitHubにpush
- 手動でjobs.jsonを編集しない（OpenClaw CLIを使用）
- 他のマシンで同期する場合は、このバックアップからリストア

---

最終更新: 2026-03-27
