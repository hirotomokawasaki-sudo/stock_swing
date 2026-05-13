# Alpaca Account Migration - 2026-05-12

## Summary

Switched Alpaca paper trading account and reset console performance tracking from 2026-05-12.

## New Account

- Account ID: `9a0de1fb-af95-47b1-9529-f2f4581ff6d5`
- Account Number: `PA3SEQKOZ91C`
- Status: `ACTIVE`
- Initial Equity: $1,000,000
- Initial Cash: $1,000,000
- Open Positions: 0

## Previous Account Archived

- Previous Account ID: `2bf02097-8ccd-4f4f-93ce-1e2f5c33c5ed`
- Archive Path: `data/archive/account_2bf02097-8ccd-4f4f-93ce-1e2f5c33c5ed_20260512/`

Archived contents:
- `tracking/` (full pnl_state history and backups)
- `audits/` (current audit/report files)
- `manifest.json` (migration metadata)

## What Was Preserved

✅ Learning / intelligence data remains intact:
- `data/decisions/`
- `data/signals/`
- strategy configs under `config/strategy/`
- models, parameters, benchmarks, and research data

## What Was Reset

🔄 Account-specific console data was reset:
- `data/tracking/pnl_state.json`
- console realized/unrealized P&L history
- console open position tracking
- drawdown / win-rate / trade-count performance metrics

## New Tracking Baseline

- Baseline Date: `2026-05-12`
- Baseline Equity: `$1,000,000`
- Tracking Label: `alpaca_account_epoch_2026-05-12`
- Performance Scope: `current_account_since_baseline`

## UI / API Change

Trading summary now exposes tracking context so the console can show:
- active account scope
- baseline date
- baseline equity
- tracking label

## Verification Target

After restart, the console should show:
- current Alpaca account = new account
- equity = $1,000,000
- open positions = 0
- performance metrics reset from 2026-05-12 baseline
