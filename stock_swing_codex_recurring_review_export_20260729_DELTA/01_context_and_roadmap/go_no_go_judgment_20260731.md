# Go/No-Go 最終判定シート（2026-07-31）

**判定日**: 2026-07-31（木）  
**判定者**:  
**判定時刻**:  
**事前レポート**: `docs/go_no_go_prereport_20260727.md`

---

## STEP 1: ハード基準チェック（全 PASS で先へ進む）

| # | 基準 | 確認コマンド | 結果 | 判定 |
|---|------|------------|------|------|
| H1 | Circuit Breaker = ok | `cat data/guardrails/circuit_breaker.json \| python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])"` | | ☐ PASS / ☐ FAIL |
| H2 | Ledger Quality = VALID | コンソール SAFETY GATE 確認 | | ☐ PASS / ☐ FAIL |
| H3 | Cron jobs 全 ok | `openclaw cron list` で全 lastRunStatus=ok | | ☐ PASS / ☐ FAIL |
| H4 | Attribution ≥ 95% | コンソール LEDGER QUALITY の attribution 表示 | | ☐ PASS / ☐ FAIL |
| H5 | broker/tracker mismatch = 0 | コンソール BROKER/TRACKER DIFF 確認 | | ☐ PASS / ☐ FAIL |
| H6 | テスト全 PASS | `python -m pytest --tb=short -q \| tail -3` | | ☐ PASS / ☐ FAIL |

**→ H1〜H6 のうち 1 件でも FAIL ならリアルトレード延期。**

---

## STEP 2: ソフト基準チェック（07-28〜30 データ込み）

```bash
# 07-28〜30 の paper_demo 結果を集計するコマンド
python3 scripts/analyze_stop_loss_post_exit.py --days 5 --since 2026-07-28
```

| # | 基準 | 目標値 | 実測値 | 判定 |
|---|------|--------|--------|------|
| S1 | trailing_stop PF（07-28〜30） | ≥ 1.0 | | ☐ OK / ☐ NG |
| S2 | **正しい止損率**（07-28〜30 のstop） | ≥ 70% | | ☐ OK / ☐ NG |
| S3 | Circuit Breaker HALT 回数（07-28〜30） | 0 回 | | ☐ OK / ☐ NG |
| S4 | broker/tracker mismatch（最終日末） | 0 | | ☐ OK / ☐ NG |
| S5 | Overall PF（全期間） | 参考値（0.727） | | 記録のみ |

> **注**: S1〜S4 が全 OK なら Go。1 件でも NG でも「条件付き Go」の選択肢あり（→ STEP 3）

---

## STEP 3: 判定

### パターン A: 完全 Go
- H1〜H6: 全 PASS
- S1〜S4: 全 OK
- **→ 08-01 から 50% サイズでリアルトレード開始**

### パターン B: 条件付き Go
- H1〜H6: 全 PASS
- S3（HALT 0回）と S4（mismatch 0）は必須 PASS
- S1 か S2 が未達でも許容する場合
- **→ 08-01 から 25% サイズ（さらに絞る）で開始。2週間後に 50% へ昇格判定**

### パターン C: No-Go（延期）
- H1〜H6 のいずれかが FAIL
- または S3（HALT）が 1 回以上
- **→ 延期。根本原因を特定してから再判定日を設定**

---

## STEP 4: 判定記録

```
判定結果: [ ] Go  [ ] 条件付きGo  [ ] No-Go

選択パターン: _______

理由:
_______________________________________________

開始サイズ: _______ %

初期2週間のモニタリング基準:
- weekly PF ≥ _______
- 正しい止損率 ≥ _______
- 単週損失上限: $_______

次の判定日（昇格/縮小）: _______________
```

---

## STEP 5: 実行手順（Go の場合）

```bash
# 1. 環境変数確認
cat .env | grep BROKER_

# 2. portfolio_allocation を本番サイズに確認
cat config/strategy/portfolio_allocation.yaml

# 3. paper → live モード切替（該当する設定変更）
# ※ runtime_mode の変更は慎重に

# 4. 最初の run の前に circuit_breaker が ok であることを再確認
cat data/guardrails/circuit_breaker.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])"

# 5. premarket cron の動作確認（market_open 前）
```

---

## 参照資料

- 事前レポート: `docs/go_no_go_prereport_20260727.md`
- Stop Loss 評価指針: `docs/stop_loss_evaluation_guidelines.md`
- テスト基準書: `docs/testing_standards.md`
- 改善計画: `docs/console_improvement_tasks.md`

---

*本シートは 07-31 当日に記入・保存し、git commit すること。*
