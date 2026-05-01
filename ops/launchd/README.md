# launchd integration

macOS でコンソールを自動起動する構成です。

## セットアップ済み

以下のサービスが `launchd` で管理されています:

- **Label**: `com.hirotomookawasaki.stock_swing.console.watchdog`
- **実行**: `console/manage.sh watchdog-loop`
- **ポート**: HTTP 3335, WebSocket 3334
- **監視間隔**: 60秒
- **ログ**: `logs/launchd_watchdog.log`, `logs/launchd_watchdog.err`

## 動作

- **起動**: macOS ログイン時に自動起動（`RunAtLoad=true`）
- **監視**: watchdog が HTTP console / WebSocket を監視し、落ちたら自動再起動
- **復旧**: watchdog 自体が落ちても launchd が再起動（`KeepAlive=true`）

## コマンド

### サービス状態確認
```bash
launchctl list | grep stock_swing
```

### サービス停止
```bash
launchctl unload ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist
```

### サービス起動
```bash
launchctl load ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist
```

### サービス再起動
```bash
launchctl unload ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist
launchctl load ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist
```

### コンソール状態確認
```bash
cd /Users/hirotomookawasaki/stock_swing
./console/manage.sh status
./console/manage.sh health
```

### ログ確認
```bash
tail -f logs/launchd_watchdog.log
tail -f logs/console_http.log
tail -f logs/console_websocket.log
```

## 注意

- `manage.sh status` では "Watchdog: stopped" と表示されますが、これは PID ファイルに記録されていないためです
- 実際には `launchctl list | grep stock_swing` で確認できます
- コンソール自体は正常に起動・監視されています

## アンインストール

```bash
launchctl unload ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist
rm ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist
```

## 再セットアップ

```bash
cp ops/launchd/com.hirotomookawasaki.stock_swing.console.watchdog.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist
```
