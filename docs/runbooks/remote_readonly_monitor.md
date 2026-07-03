# Remote Read-Only Monitor Runbook

**Created**: 2026-07-02
**Scope**: R6-F smartphone-friendly read-only monitoring

This monitor is separate from `console/app.py`. The full console has parameter
mutation endpoints, so it must not be exposed remotely as the R6-F surface.

## Current Exposure Plan

| Phase | Choice | Status |
|---|---|---|
| Same-day verification | LAN/local | Verified on 2026-07-02 |
| Production (R6-F-GW) | Tailscale Serve | ✅ 完了 2026-07-03 |

### Tailscale Serve URL (tailnet 内のみ・HTTPS)

```
https://hirotomoonomac-mini.tail64d731.ts.net/?token=r6f-lan-dc2943cf7469a02aa07b177f
```

- tailnet: `hirotomokawasaki-sudo@`
- Tailscale IP: `100.89.217.16`
- アクセス条件: スマホに Tailscale アプリをインストールし、同じ tailnet に接続すること
- WireGuard 暗号化 + トークン認証の二重保護

2026-07-02 LAN verification:

- Mac LAN IP: `192.168.0.190`
- Server bind: `0.0.0.0:3340`
- `GET /health` via localhost: `200`
- `GET /health` via LAN IP: `200`
- authenticated `GET /api/status` via LAN IP: `200`
- unauthenticated `GET /api/status` via LAN IP: `401`

---

## Tailscale Serve セットアップ（R6-F-GW）

### 前提
- Tailscale v1.98+ インストール済み（`brew install tailscale`）
- Tailscale アカウント: `hirotomokawasaki-sudo@`
- tailnet: `tail64d731.ts.net`
- Tailscale 管理コンソールで MagicDNS + HTTPS Certificates が有効

### LaunchAgent（自動起動）

```text
~/Library/LaunchAgents/com.hirotomookawasaki.tailscaled.plist
```

tailscaled をユーザースペースネットワークモードで起動する。
state: `~/.tailscale/state` / socket: `/tmp/tailscale.sock`

```bash
# 手動起動（LaunchAgent が動いていない場合）
/opt/homebrew/opt/tailscale/bin/tailscaled \
  --tun=userspace-networking \
  --state=/Users/hirotomookawasaki/.tailscale/state \
  --socket=/tmp/tailscale.sock &
```

### Serve 設定確認

```bash
/opt/homebrew/bin/tailscale --socket=/tmp/tailscale.sock serve status
# 期待: https://hirotomoonomac-mini.tail64d731.ts.net/ -> proxy http://127.0.0.1:3340
```

### Serve が外れていた場合の復元

```bash
/opt/homebrew/bin/tailscale --socket=/tmp/tailscale.sock serve --bg 3340
```

### スマホ側セットアップ

1. App Store / Google Play で **Tailscale** をインストール
2. 同じアカウント（`hirotomokawasaki-sudo@`）でログイン
3. ブラウザで以下を開く:
   ```
   https://hirotomoonomac-mini.tail64d731.ts.net/?token=r6f-lan-dc2943cf7469a02aa07b177f
   ```
4. トークンが自動保存され、次回からはトップ URL のみで OK

### 障害対応

```bash
# tailscale 状態確認
/opt/homebrew/bin/tailscale --socket=/tmp/tailscale.sock status

# serve 状態確認
/opt/homebrew/bin/tailscale --socket=/tmp/tailscale.sock serve status

# ログ確認
tail -f /Users/hirotomookawasaki/stock_swing/logs/tailscaled.log
tail -f /Users/hirotomookawasaki/stock_swing/logs/tailscaled.err

# LaunchAgent 再起動
launchctl bootout gui/$(id -u)/com.hirotomookawasaki.tailscaled
launchctl load ~/Library/LaunchAgents/com.hirotomookawasaki.tailscaled.plist
```

---

## Start Locally

```bash
cd /Users/hirotomookawasaki/stock_swing
export REMOTE_READONLY_TOKEN="$(openssl rand -hex 24)"
export REMOTE_READONLY_HOST=127.0.0.1
export REMOTE_READONLY_PORT=3340
venv/bin/python console/remote_readonly_app.py
```

Open:

```text
http://127.0.0.1:3340/
```

Enter the token in the mobile UI.

---

## LAN Mode

Use only on a trusted network or behind a VPN/tunnel with access control.

```bash
export REMOTE_READONLY_HOST=0.0.0.0
export REMOTE_READONLY_PORT=3340
venv/bin/python console/remote_readonly_app.py
```

Then open:

```text
http://<mac-mini-lan-ip>:3340/
```

For phone setup, this URL stores the token in the browser and then removes it
from the address bar:

```text
http://<mac-mini-lan-ip>:3340/?token=<REMOTE_READONLY_TOKEN>
```

## Persistent LAN Mode with launchctl

2026-07-02 verification uses a user LaunchAgent:

```text
~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.remote_readonly.plist
```

Check:

```bash
launchctl print gui/$(id -u)/com.hirotomookawasaki.stock_swing.remote_readonly
lsof -nP -iTCP:3340 -sTCP:LISTEN
curl -s http://192.168.0.190:3340/health | python3 -m json.tool
```

Stop:

```bash
launchctl bootout gui/$(id -u)/com.hirotomookawasaki.stock_swing.remote_readonly
```

Logs:

```bash
tail -f logs/remote_readonly.log
tail -f logs/remote_readonly.err
```

---

## Read-Only Endpoints

All `/api/*` endpoints require `Authorization: Bearer <token>`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Server health, no portfolio data |
| `GET /api/status` | Summary availability and freshness |
| `GET /api/console_summary` | Latest `reports/console/latest_console_summary.json` |
| `GET /api/go_no_go` | `docs/runbooks/go_no_go_checklist.md` |
| `GET /api/positions` | Open positions list |
| `GET /api/recent_trades?limit=25` | Recent closed trades |
| `GET /api/at_risk_positions` | Positions near stop / loss / giveback conditions |
| `GET /api/operational_health` | Cron, guardrail, circuit breaker health |
| `GET /api/broker_tracker_detail` | Broker-only / tracker-only / qty mismatch detail |

Mutation methods return `405 read_only`.

## Smartphone Panels

The mobile UI intentionally stays dense and read-only. As of 2026-07-02 it
shows:

- Portfolio / Run Health
- Operational Health
- At-risk Positions
- Open Positions
- Recent Trades
- Exit Attribution
- Broker / Tracker summary and detail
- Decision Funnel
- Alerts
- Go / No-Go checklist

---

## Verification

```bash
curl -s http://127.0.0.1:3340/health | python3 -m json.tool

curl -s \
  -H "Authorization: Bearer $REMOTE_READONLY_TOKEN" \
  http://127.0.0.1:3340/api/status | python3 -m json.tool
```

Expected:

- `read_only: true`
- `summary_available: true`
- no POST/PUT/DELETE support

---

## Stop

Press `Ctrl+C` in the foreground terminal, or stop the owning process if it is
running under launchd/tmux.

---

## Security Notes

- Do not expose `console/app.py` as the remote monitoring surface.
- Do not add buy/sell/cancel/reset/parameter apply endpoints to this server.
- Rotate `REMOTE_READONLY_TOKEN` if it appears in logs, shell history, or chat.
- Prefer VPN/OpenClaw gateway over raw port forwarding.
- Tailscale Serve URL は tailnet メンバーのみがアクセス可能（Funnel ではないため公衆インターネットには露出しない）。
- tailscale serve config は `~/.tailscale/state` に永続化されるため、tailscaled 再起動後も自動復元される。
