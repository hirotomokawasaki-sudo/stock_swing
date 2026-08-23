# Strategy Review Validation Packet — 2026-08-23

この資料は、2026-08-23に実施した`stock_swing`投資戦略・改善計画レビューを、
Claude等の別モデルが**結論を前提にせず独立検証**するためのパケットです。

## 固定した対象

- Git commit: `cf6bc75a1d3cb5e8eff5e3168cf89de74f8fd774`
- 台帳: パケット生成時の`data/tracking/pnl_state.json`
- closed trades: 252件
- attributableの定義: `decision_id`、`run_id`、`experiment_id`が全て存在
- 直近cohortの定義: attributableかつ`exit_time >= 2026-08-14`
- 個人・ブローカー識別情報: 除去済み

`evidence/closed_trades_sanitized.json`には、銘柄、損益、時刻、exit reason、
signal strength等、レビューの再計算に必要な最小限の項目だけを収録しています。
account ID、order ID、fill ID、trade IDは含みません。

## Claudeでの使い方

1. このディレクトリ全体、または`strategy_review_claude_validation_20260823.zip`を渡す。
2. 最初の指示として`CLAUDE_PROMPT.md`を貼る。
3. Claudeに以下を実行・確認させる。

```bash
python reproduce_review_metrics.py
sh verify_bundle.sh
```

4. `CLAIMS_MATRIX.md`の各claimについて、`SUPPORTED / PARTIALLY_SUPPORTED /
NOT_SUPPORTED / NOT_TESTABLE`の判定を要求する。

## 構成

- `CLAUDE_PROMPT.md`: バイアスを抑えた独立検証プロンプト
- `CLAIMS_MATRIX.md`: 主張・証拠・反証条件・留保
- `IMPLEMENTATION_VALUE.md`: 実装価値を判断するための優先順位案
- `SOURCES.md`: 外部一次資料と、その資料が支持しない範囲
- `reproduce_review_metrics.py`: stdlibのみの数値再計算器
- `verify_bundle.sh`: SHA-256と数値の検証
- `evidence/`: 匿名化取引スナップショット、計算結果、既存レポート
- `source_files/`: 検証に必要なコード・設定・計画書の固定コピー
- `MANIFEST.sha256`: パケット全ファイルのハッシュ

## 重要な区別

このレビューには3種類の記述があります。

1. **コード・データ上の事実**
   - 例: R11が当日barを含めてsignalを計算し、同日のcloseでentryする。
2. **事実からの推論**
   - 例: 上記は現在の運用時系列では約定バイアスになる可能性が高い。
3. **ガバナンス上の提案**
   - 例: attributable 100件、bootstrap 90%下限、DD 5%という昇格基準。

3は法令・学術上の必須値ではありません。Claudeには、この数値をそのまま承認
するのではなく、資金規模、損失許容度、取引頻度に対して妥当か再評価させてください。

## 既知の留保

- IID bootstrapは取引間の時系列依存や同時保有の相関を保存しません。
- 会話中の速報値はPF 90%区間を約`0.568–2.157`、正の標本を約`58.7%`と報告しました。
  パケットの固定seed・実装によるcanonical再計算は`0.564–2.125`、`58.29%`です。
  差はbootstrap乱数・丸めによる範囲で、結論は変わりません。Claudeにはパケット値を
  再現基準として使わせてください。
- attributable 49件は小標本です。
- signal-strength decile reportの110件と、厳格なattributable 49件は母集団が異なります。
- 「同日close約定」が必ず不可能とは限りません。MOC注文を最終価格確定前に出す設計なら
  実現可能性があります。しかし現R11は確定した当日closeをsignal入力とentry価格の両方に
  使うため、少なくともその時系列整合性を別途証明する必要があります。
- SEC/FINRA資料は統制・仮想成績の扱いを比較する参考資料です。この個人運用へそのまま
  法的義務を課すという主張ではありません。

## このパケットが意図的に含めないもの

- APIキー、broker credential、account ID
- 生のorder/fill ledger
- Claudeに修正実装を許可する指示
- 元レビューの結論を正解として扱う採点基準
