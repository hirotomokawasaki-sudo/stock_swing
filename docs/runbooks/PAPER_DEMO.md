# PAPER_DEMO.md - Paper Trading Demo Runbook

## Pipeline

broker bars -> normalize -> momentum features -> strategy signals
-> risk validation -> decision engine -> paper order submission
-> reconciliation -> audit log -> decisions saved

## Quick Start

```bash
cd ~/stock_swing

# Preview (no orders)
./scripts/run_paper_demo.sh --dry-run

# Outside market hours (orders queue)
./scripts/run_paper_demo.sh --allow-outside-hours

# Custom symbols / lower threshold
./scripts/run_paper_demo.sh --symbols AAPL,NVDA --min-momentum 0.02 --allow-outside-hours
```

## Kill Switch

```bash
# Trigger (block all execution)
echo "triggered" > ~/stock_swing/data/audits/kill_switch.txt

# Reset
echo "active" > ~/stock_swing/data/audits/kill_switch.txt
```

## Outputs

- `data/audits/paper_demo_YYYYMMDD.log` - audit log
- `data/decisions/decision_SYMBOL_TIMESTAMP.json` - decision records

## Current Limitations

- FRED not connected -> macro_regime = "unknown"
- Finnhub not connected -> EventSwingStrategy generates no signals
- Position sizing: fixed 10 shares (TODO: equity-based)
- Daily loss limit: not yet implemented
