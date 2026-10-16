# 10/14損失取引とshock-aware exit検証（2026-10-16）

## 結論

10月14日のAMAT、CRDO、CIENの全量損切りを調査した。3銘柄を一律に
「一時的な急落への狼狽売り」と扱う根拠はなく、単純な損切り延期は採用しない。
ライブ売買は変更せず、次の2案をshadow-onlyで計測する。

1. 通常stopかつhard cap未到達の場合だけ、初回に3分の1を退出し、残りを
   1セッション確認するshock-aware staged exit
2. 既存ポジションが-3%以下の銘柄への買い増しを記録するlosing-position add guard

同時に、反実仮想の前提を壊していたセッション日付・価格鮮度・保有日数・exit分類を
修正した。いずれのshadowも注文やactionable decisionを変更しない。

## 10/14の再構成

| 銘柄 | 実績 | 判定 |
|---|---:|---|
| AMAT | 144株、平均exit約$453.23、損失約-$9.6K | 09:25 ET付近ではSMH/SOXXの下落は約-2.1%/-2.4%。その時点で観測できる情報ではsector shockではなく`soft_stop` |
| CRDO | 371株、損失-$14,923.91 | 約-18%で相対弱さ・hard cap領域。全量退出維持 |
| CIEN | 189株、損失-$13,344.30 | -16.73%のemergency stop。全量退出維持。ただし前日に既存ロットが約-10%の状態で69株を追加しており、買い増し側に改善余地 |

10/14終値まで見るとSMH/SOXXは-3.98%/-4.50%となるが、これはexit時点では
未知の情報である。日中exitを終値で再分類するとlook-ahead biasになるため、
回帰テストはexit時点のquoteと10/13確定終値だけを使う。

## 反実仮想

AMATを`soft_stop`として3分の1（48株）だけ約$453.23で退出し、残り96株を
翌10/15終値$430.01まで保有する反実仮想では、全量退出より損益が約$2,229悪化する。
CRDOとCIENはhard cap/emergency判定のため、staged treatmentでも全量退出のまま。

したがって10/14の1例は「待てば回復する」仮説を支持しない。段階退出は、
急落後の反発を拾えるケースと損失を拡大するケースをforward shadowで分離してから
paper A/B昇格を判断する。デフォルトのshadow hard capは-15%で感度分析用であり、
-12%にするとAMATも全量退出になる。

## 実装

- `session_return_snapshot.py`
  - current sessionはlive broker quoteと直前の確定市場終値を比較
  - 完了セッションは同一日付のdaily returnだけを使用
  - stale/missing/corruptデータは`insufficient_data`としてbaseline exitを維持
- `sector_shock_hold.py`
  - `signal_strength`を価格returnの代用品にする経路を廃止
  - benchmark平均による半導体shockの希釈を避け、閾値超過数とbreadthで判定
  - 実際の`hold_days`を使用
- `shock_aware_staged_exit.py`
  - `soft_stop`/`sector_shock_hold`かつhard cap未到達だけを段階退出候補にする
  - 欠損、relative weakness、emergency、hard capは全量退出
  - baselineとtreatmentの反実仮想を未来情報なしで再生
- `losing_position_add_guard.py`
  - 既存含み損が-3%以下の銘柄へのBUYをshadowで記録
  - CIENの10/13追加はwould_blockになる
- `paper_demo.py`
  - emergency stopを`stop_loss`として正規分類
  - 両shadowを非dry-run時だけ記録し、売買判断は変更しない

## 昇格条件

現時点ではactive化しない。少なくとも以下を満たした後にpaper A/Bを検討する。

- セッション整合済みのforward eventを十分に蓄積
- staged treatmentの合算損益、MFE/MAE、hard-cap発火率がbaselineを上回る
- 特定1銘柄・1イベント依存でない
- missing data時にbaseline exitが維持される
- losing-position add guardはブロック対象と非対象の事後損益を分離評価する

## 検証

- 10/14のAMAT as-of-exit回帰
- CRDO relative weakness、CIEN emergency stop回帰
- 翌日価格によるAMAT反実仮想
- no-lookahead、missing/stale/corrupt data、hard-cap感度、JSONL記録
- 関連テスト115件PASS
