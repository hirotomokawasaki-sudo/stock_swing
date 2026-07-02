# Remote Read-Only Monitor Runbook

**Created**: 2026-07-02
**Scope**: R6-F smartphone-friendly read-only monitoring

This monitor is separate from `console/app.py`. The full console has parameter
mutation endpoints, so it must not be exposed remotely as the R6-F surface.

## Current Exposure Plan

| Phase | Choice | Status |
|---|---|---|
| Same-day verification | LAN/local | Verified on 2026-07-02 |
| Production candidate before 2026-08-01 | OpenClaw gateway | Pending gateway route design |

2026-07-02 LAN verification:

- Mac LAN IP: `192.168.0.190`
- Server bind: `0.0.0.0:3340`
- `GET /health` via localhost: `200`
- `GET /health` via LAN IP: `200`
- authenticated `GET /api/status` via LAN IP: `200`
- unauthenticated `GET /api/status` via LAN IP: `401`

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

---

## Read-Only Endpoints

All `/api/*` endpoints require `Authorization: Bearer <token>`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Server health, no portfolio data |
| `GET /api/status` | Summary availability and freshness |
| `GET /api/console_summary` | Latest `reports/console/latest_console_summary.json` |
| `GET /api/go_no_go` | `docs/runbooks/go_no_go_checklist.md` |

Mutation methods return `405 read_only`.

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
