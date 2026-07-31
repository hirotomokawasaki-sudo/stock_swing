# 08-20 リアルトレード移行 事前チェックリスト

**移行日**: 2026-08-20 以降（50% サイズで開始）  
**Go/No-Go 判定**: 2026-07-31 ✅ GO（7/7 全条件クリア）  
**作成日**: 2026-07-31

---

## A. 技術・システム条件（移行前日までに確認）

| 項目 | 状態 | 確認方法 |
|------|------|----------|
| `ledger_quality_gate: VALID` | ✅ 07-31 現在 | `python scripts/check_go_no_go.py` |
| `circuit_breaker: ok` | ✅ 07-31 現在 | 同上 |
| `broker_tracker_mismatch: 0` | ✅ 07-31 現在 | 同上 |
| `attribution_coverage ≥ 95%` | ✅ 98.5% | 同上 |
| paper 7日間連続エラーなし | 🔲 08-19 確認 | cron job health / audit log |
| BUY 正常稼働確認（今夜 07-31〜） | 🔲 08-01 以降 | `paper_demo_complete submitted > 0` |

---

## B. ブローカー設定変更（移行当日）

```yaml
# config/strategy/portfolio_allocation.yaml
# 変更は移行当日に実施、paper で事前テスト不可

# 変更前（現在 paper 設定）
stock_new_buy_multiplier: 1.0     # paper フルサイズ

# 変更後（リアル移行時）
stock_new_buy_multiplier: 0.50    # 50% サイズで開始
```

### cron 環境変数の変更
```bash
# scripts/cron/run_paper_demo.sh の PAPER_DEMO=true を削除 or false に変更
# BROKER_API_KEY / BROKER_API_SECRET をリアル口座のものに変更
# BROKER_BASE_URL を https://api.alpaca.markets に変更
```

> ⚠️ **実施手順**: `scripts/cron/switch_to_live.sh` を用意予定（08-15 までに作成）

---

## C. Go/No-Go 最終確認（移行当日 09:00 JST）

```bash
python scripts/check_go_no_go.py --save
# 全 7 件 PASS を確認してから切り替え
```

追加確認:
- [ ] Alpaca リアル口座の入金確認（目標元本 確認）
- [ ] API キー（リアル）の動作テスト（`broker_healthcheck.py --live` ）
- [ ] 当日のニュース / 市場環境を確認（セクターショック直後は延期推奨）

---

## D. 移行後 1 週間の監視項目

| 監視項目 | 閾値 | 対応 |
|----------|------|------|
| 日次損失 | `-$10,000` 超 | BUY 停止・手動確認 |
| 週次損失 | `-$25,000` 超 | 全ポジション手動確認 |
| broker/tracker mismatch | ≥ 1 | circuit_breaker HALT・調査 |
| fill rate | < 70% | execution レビュー |
| consecutive failures | ≥ 3 | cron health チェック |

### 推奨: 初週は毎朝コンソール確認
```
# 毎朝 09:00 JST
python scripts/check_go_no_go.py
# + daily_report_morning の Telegram を確認
```

---

## E. ロールバック手順

問題が発生した場合は即座に paper に戻す:

```bash
# 1. BUY 即時停止
export PAPER_DEMO_EXIT_ONLY=true

# 2. 設定を paper に戻す
# BROKER_BASE_URL=https://paper-api.alpaca.markets
# stock_new_buy_multiplier=1.0

# 3. open positions を確認してから全クローズ判断
python scripts/check_go_no_go.py
```

---

## F. 残 paper タスク（08-20 前に完了推奨）

| タスク | 予定 | 備考 |
|--------|------|------|
| sector_shock shadow ≥ 10件 | passive（07-31〜） | 現在 0/10 |
| RF-7b sector_shock A/B | shadow 到達後 | 10件で開始 |
| R4-C signal decile 精度向上 | 08-04〜 | clean records 200件+ 目安 |
| 20 clean runs soak（BUY 修正後） | 07-31〜08-20 | 修正後の動作安定確認 |

---

## G. サイズ拡大ロードマップ

| 期間 | サイズ | 条件 |
|------|--------|------|
| 08-20〜08-31 | **50%** | 移行直後 |
| 09-01〜 | **75%** | 2 週間問題なし + PF ≥ 1.0 |
| 09-15〜 | **100%** | 1 ヶ月問題なし + PF ≥ 1.2 |

> **注意**: 上記はガイドラインのみ。実際の拡大は Go/No-Go 判定で決定。

---

*作成: 2026-07-31 — 改訂: 移行判断時に更新*
