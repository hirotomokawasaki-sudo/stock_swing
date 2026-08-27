# R13-D ETFセクターローテーション: min_members未実装の修正・正式再判定（2026-08-26）

## 経緯

1. 08-26午後のロードマップ監査で`run_rotation()`の`min_members`パラメータが
   定義済みだが本体で未使用と発見
2. 独立検証スクリプト（`r13d_min_members_check.py`）でheadline設定（top_n=2）
   に適用すると効果を実測: Sharpe 1.370→1.230、equal-weight baseline(1.255)
   を下回りNO-GOに転落
3. **本節**: 検証結果を受け、`r13d_etf_sector_rotation_phase1.py`本体
   （Phase1研究専用・本番未配線）に`min_members`を正式実装し、`--enforce-
   min-members`フラグで新旧両方の結果を比較可能にした上で公式な再判定を実施

## 実装内容

`run_rotation()`に`sector_members`引数を追加し、`min_members`未満のセクターを
ランキング対象から除外するロジックを実装。デフォルト（フラグなし）では
`sector_members=None`となり**旧挙動を完全に保持**（後方互換性を検証済み:
フラグなし実行でSharpe=1.370、既存headlineと完全一致）。`--enforce-min-
members`フラグを渡した場合のみ修正版ロジックが有効化される。

## 公式な再判定結果

### Headline設定（top_n=2, lookback=63d, hold=21d）

| | Sharpe | vs equal-weight(1.255) | vs SPY(0.967) | 判定 |
|---|---|---|---|---|
| 旧（min_members未適用） | 1.370 | 上回る | 上回る | GO |
| **新（min_members適用）** | **1.230** | **下回る** | 上回る | **MIXED（一方のみ上回る）** |

`main()`の`VERDICT`ロジック自体が新結果を「⚠️ MIXED — 片方のベースラインのみ
上回る。Phase2着手前にさらなる検討（lookback延長・レジーム分割）が必要」と
正しく判定した。

### パラメータ感度チェック（min_members適用状態、5パターン）

| 設定 | Sharpe | 判定（vs 両ベースライン） |
|---|---|---|
| top_n=1, lookback=63d, hold=21d | **1.473** | GO（既存robustness checkと一致） |
| **top_n=2, lookback=63d, hold=21d（headline）** | **1.230** | **MIXED** |
| top_n=3, lookback=63d, hold=21d | 1.196 | NO-GO |
| top_n=2, lookback=126d, hold=21d | 1.415 | GO |
| top_n=2, lookback=63d, hold=42d | 1.318 | GO |

**重要な発見**: min_members適用後もtop_n=1・lookback延長・hold延長の各設定は
依然両ベースラインを上回る。**NO-GO/MIXEDになるのはheadline設定
（top_n=2, lookback=63d, hold=21d）1点のみ**。

## 結論（改訂版）

当初「GO判定が覆る」と報告したが、より正確には**「headline設定固有の脆弱性」**
であり、戦略アイデア（セクターローテーション）自体の妥当性は、パラメータを
top_n=1にする、もしくはlookback/holdを若干延長するだけで依然支持される。

これは新しい種類の教訓: **単一のheadline設定にのみ依存したGO判定は、実装
バグ（min_members未適用）1つで簡単に覆りうる**。パラメータ感度チェック自体は
既存で実施されていたが、それは「バグを含んだ計算」の上でのチェックであり、
「バグ修正後も感度チェックの傾向は同じか」という2段階目の検証が必要だった。

## 推奨される次のアクション

1. **Phase1のheadline設定を`top_n=1`または`lookback=126d`に変更した上で、
   min_members修正込みの数値を新headlineとして採用する**（後付けの
   良い数値選びにならないよう、この2案のいずれかを選ぶ根拠を別途明文化
   すること——例えば「単一ETFノイズを最も安定して除去できるtop_n=1を
   採用する」等）
2. 09-08のR13-D本番配線判断レビューでは、修正済みの`--enforce-min-members`
   フラグ付き結果を正式な判断材料として使用すること
3. 本修正はPhase1研究スクリプトのみに適用（本番未配線のため影響なし）。
   フルテストスイート・関連テスト46件はPASS確認済み

## 再現方法

```bash
cd ~/stock_swing && source venv/bin/activate
# 旧結果（後方互換確認用）
python scripts/r13d_etf_sector_rotation_phase1.py
# 新結果（min_members修正込み、公式再判定）
python scripts/r13d_etf_sector_rotation_phase1.py --enforce-min-members --save
```

生データ: `reports/r13d_etf_sector_rotation_phase1_results.json`
（`--enforce-min-members`実行時に上書き保存）、
独立検証: `results.json`（`r13d_min_members_check.py`の出力）
