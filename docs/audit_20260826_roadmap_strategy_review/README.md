# 2026-08-26 ロードマップ・戦略検証手法 監査

**依頼内容**: 現在の改善状況・計画に落ち度や抜け漏れがないか、特に戦略の改善・新規戦略の
検証手法を有効性・実用性の観点からレビュー。

**手法**: `evidence-based-system-audit`スキル準拠。既存ドキュメントの記述を鵜呑みにせず、
実際のスクリプト/ソースコードを読んで再検証。2本のサブエージェント（戦略バックテスト手法監査、
shadow実装安全性監査）+ 自分自身の直接検証（ロードマップ整合性・スケジュール・監視スクリプト）
の3系統で並行実施。全て読み取り専用、本番コード変更なし。

---

## サマリー（重要度順）

| # | 重要度 | 項目 | 状態 |
|---|---|---|---|
| 1 | 🔴High | R11-C（代替シグナル4候補、全て見送り判定）が古い手法（同日終値約定、コスト無視）のまま再検証されていない | 未対応 |
| 2 | 🔴High | attribution_coverage_pct 75.2%がGo/No-Go Required閾値(95%)をブロック中、既存スクリプトで96.2%まで回復可能なのに未実施 | 未対応 |
| 3 | 🟡Medium | R13-D Phase1のGO判定はコスト無視・現在銘柄リストの遡及適用のfrictionless proxyのみに依存 | 既知の限界（一部文書化済み） |
| 4 | 🟡Medium | R13-D `min_members`パラメータが定義済みだが未使用、single-ETFセクターノイズを抑えられていない | 未対応 |
| 5 | 🟡Medium | R13-D shadow/Phase3のリバランス間隔（暦日21日）がPhase1検証（取引日21日）と別物 | 既知（README自己開示済み） |
| 6 | 🟡Medium | R13-D/R14のshadow→本番配線の判断基準が定量化されておらず日程メモのみ | 未対応 |
| 7 | 🟡Medium | R14 Phase1のGO判定根拠の一部（chop-window比較等）がスクリプト直接出力ではなく手組み | 未対応 |
| 8 | 🟡Medium | R13-C/R14ともATR連動stop調整を本番同様に再現していない（volatility_multiplier固定） | 未対応 |
| 9 | 🟢Low | check_quarantine_trend.pyのロジックバグ（件数減少+新entry_timeで誤って"growing"判定） | 未対応（軽微、実害なし） |
| 10 | 🟢Low | R13-D shadowレビュー日程（09-08）がリバランス頻度（21日）と噛み合わない | 未対応 |
| — | ✅ | Shadow実装の安全性（本番発注経路への未配線） | 検証済み、問題なし（構造的注記あり） |
| — | ✅ | R13-C v3/v4, R14のlook-ahead bias（t+1約定） | 検証済み、問題なし |
| — | ✅ | R13-D shadowの本番state file隔離 | 検証済み、問題なし |

---

## 🔴 High 1: R11-C（代替シグナル4候補）が古い検証手法のまま放置されている

**発見**: 2026-08-15にRSI逆張り/セクター相対強度/決算近接/ニュースセンチメントの4候補を
検証し「全滅」と判定した`scripts/r11c_candidate_backtest.py`は、その後R13-Cで確立された
検証手法（t+1約定、point-in-time universe、slippageモデリング）を一切反映していない。

- Entry fillは**シグナル発生日の当日終値**（`r11c_candidate_backtest.py:223-229`
  `entry_price = bar["close"]`）——R13-C/R14で採用されたt+1約定方式ではない
- slippage/PIT universe引数が存在しない（`123-129`, `461-490`）
- walk-forward比較の分割日が候補ごとにバラバラ（各候補自身のmedian entry_dateで分割、
  共通カレンダーではない）。実測: baseline分割日2025-10-08 vs ニュース候補2026-06-15
  （データ期間自体が4ヶ月しかないため）

**なぜ重要か**: R13-Cは「同一のバックテスト手法の欠陥（look-ahead/survivorship bias）を
解消する」ことを目的とした根本的再構築だったが、R11-Cで「見送り」と判定した4候補は、
まさにR13-Cが問題視した旧手法のままの結果。もしR13-C同等の手法で再検証すれば結論が
変わる可能性を排除できていない。

**推奨対応**: R11-C全候補（RSI逆張り/セクター相対強度/決算近接/ニュースセンチメント）を
`r11_backtest_engine_v4.py`相当のt+1約定+PIT universe+slippage込みで再実行し、同じ
「見送り」判定が出るか確認。工数は中程度（既存v4基盤の再利用で1日程度と推定）。

---

## 🔴 High 2: attribution_coverage_pct 75.2%のGo/No-Goブロッカーが放置されている

**発見**: 08-24 rebuild（見落とされたブローカー注文84件を復元）によりattribution_
coverage_pctが98.8%→74.6%（現在75.2%）に低下し、これが`check_go_no_go.py`の
Required 7条件のうち95%閾値を明確にブロックしている（実行確認: 現在NO-GO、
ブロック項目に`attribution_coverage_pct`明記）。

既存の回復スクリプト`scripts/rf8b_recover_attribution.py --dry-run`を実行したところ：

```
Attribution coverage: 75.2% → 96.2%  (target ≥ 95%)
  from trade_events:     10件
  from pending:          0件
  from decision JSONs:   60件
  from manual annot.:    2件
  still unknown:        13件
```

**なぜ重要か**: 09-15 Go/No-Go判定のRequired条件を直接ブロックしている項目の一つに、
即座に実行可能な回復手段が既に存在するのに、ロードマップ上「実施予定」として一切
言及されていなかった。09-10のPre-Launch Gate Reviewまで放置すると、土壇場で
「なぜもっと早く気づかなかったのか」という状況になりかねない。

**推奨対応**: `rf8b_recover_attribution.py`の実行（本番データ書き換えのためユーザー
承認必須、xhigh reasoning推奨）。dry-runで効果を確認済みなので、実行自体のリスクは
低い（既存スクリプトの再利用、新規ロジックなし）。

---

## 🟡 Medium: R13-D ETFセクターローテーションの検証手法の限界（複数）

1. **Phase1のGOはfrictionless proxyのSharpe比較のみ**: コスト無視・現在のETF構成を
   過去に遡及適用（`r13d_etf_sector_rotation_phase1.py:42-56`）。robustnessチェックでは
   単独期間でequal-weight baselineを上回れていないケースもある
   （`robustness_checks.md:16-27`）。
2. **`min_members`パラメータが未使用**: `run_rotation()`が`min_members: int = 2`を
   受け取るが本体で一切参照していない（`r13d_etf_sector_rotation_phase1.py:144-155`）。
   実際の結果には`technology_cloud`等single-member sectorが初回リバランスから
   保有対象に入っている。
3. **リバランス間隔の定義齟齬**: Phase1検証は21**取引日**間隔（`158-189`）だが、
   本番実装のstate machine（Phase3・shadow）は21**暦日**間隔（`sector_rotation_
   state.py:166-175`）。README自身が「31回vs想定20.8回」と約49%多いリバランス頻度を
   自己開示済み（既知の問題として記録はされている）。

**推奨対応**: 優先度は中。09-08レビューで本番配線を検討する前に、(a) `min_members`
の実装漏れを直す、(b) t+1約定+コスト込みのtradeable backtestで再判定、を先に実施
するのが望ましい。

---

## 🟡 Medium: shadow→本番配線の判断基準が未定量化（R13-D・R14共通）

R14 dip-buy・R13-D sector rotationいずれも、shadowログには生シグナルデータしか
記録されておらず（`dip_buy_meanreversion_strategy.py:188-225`、
`log_sector_rotation_shadow.py:241-256`）、「何件・どのPF/precision・どの乖離幅なら
昇格するか」という定量基準がロードマップに存在しない。09-08レビューは「日程」として
予定されているのみで、判断ロジックが曖昧なまま先送りされている。

**推奨対応**: 09-08レビュー前に、最低限「最小サンプル数」「forward win/loss proxy
の許容範囲」を明文化しておくことを推奨（判断自体はユーザー承認が必要という原則は
維持しつつ、判断材料の定量化）。

---

## 🟢 Low: check_quarantine_trend.pyのロジックバグ（今回のクリーンアップで顕在化）

`scripts/check_quarantine_trend.py`を実行したところ、本日実施したquarantine
クリーンアップ（102件→6件、実損失ではない重複削除）の直後に**誤って"GROWING"（増加）
と判定**された。

```
Current quarantine count: 6
Status: GROWING
⚠️ Quarantine count changed: 101 -> 6 (delta=-95)...
```

**原因**（`evaluate_trend()`関数、95-119行目）: 件数が減少した場合でも、残存する
quarantineの中に前回スナップショットより新しい`entry_time`のものが1件でもあれば
（今回は08-11のCRWDが該当）`new_quarantine_detected=True`となり、
`if count_delta > 0 or new_quarantine_detected:` の条件式が`count_delta < 0`より
優先されて評価されるため、大幅減少中でも"growing"と誤判定される。

**実害**: 軽微（今回のケースでは実際に問題なし、単なる誤警告）。ただし今後同様の
台帳クリーンアップ作業をする度に誤警告が出る可能性がある。

**推奨対応**: `count_delta < 0`のチェックを`new_quarantine_detected`より先に評価する
よう条件分岐の順序を修正（低優先度、影響は表示上の誤警告のみ）。

---

## ✅ 検証済み・問題なし

### Shadow実装の安全性
R13 sector rotation、R14 dip-buy、JP overnight spillover、R9 Plan B/C/D/E診断は
いずれも`paper_demo.py`の発注経路（entry_signals/all_signals/actionable）に
一切追加されておらず、standalone scriptまたはログ専用ブロックに隔離されている
ことをコード実読で確認。production state file（pnl_state.json等）への誤書き込み、
broker payloadのmutateも確認されず。

**重要な構造的注記**: 安全性は汎用的な`shadow_only`キルスイッチによる強制遮断では
なく、「発注経路に配線されていない」という構造そのもので担保されている。将来
`paper_demo.py`に1行の配線を追加するミスがあれば、下流で自動的に拒否する仕組みは
存在しない。今後shadow戦略を配線する際は、逆に「非shadow戦略が誤って混入していない
か」のテストではなく、「配線ミスを検知する統合テスト」を追加することが望ましい。

### R13-C v3/v4・R14のlook-ahead bias排除
pending queueによるt+1約定が正しく実装されており、同一バー内の未来情報参照は
排除されている（`r11_backtest_engine_v3.py:251-271`、`r14_dip_buy_meanreversion_
phase1.py:200-219`等）。

---

## 総括

現行ロードマップ（R0-v2〜R14）は全体として堅実に運用されており、致命的な安全上の
欠陥は見つからなかった（shadow実装の分離、t+1約定の徹底等は良好）。ただし:

1. **R11-Cの「見送り」判定は、その後確立されたより厳密な検証手法（R13-C）で
   再検証されておらず、結論の信頼性に疑問符が残る**（最優先で対応推奨）
2. **Go/No-Goの直接ブロッカーの一つ（attribution_coverage_pct）に、既に実行可能な
   解決策が存在するのに未実施のまま放置されている**（次点で対応推奨）
3. 新規戦略（R13-D/R14）の検証は概ね誠実だが、frictionless proxy依存・promotion
   基準の未定量化など、「feasibility checkとしては妥当だが、まだtradeable backtest
   ではない」という限界が複数箇所にある

これらは全て**致命的なバグではなく、判断の確度を上げるための改善余地**という位置
づけ。09-15 Go/No-Go判定までに、特に上記🔴High 2件への対応を検討することを推奨する。
