# Earnings proximity shadow（2026-09-14 事前登録）

## 発端と確定した原因

2026-09-03 13:35 UTC の通常モメンタムBUYで、PATH（同日AMC決算）と
SNOW（前日AMC決算）が約定し、その後の損失集中に寄与した。

- PATH: Finnhubの取得済み行に `date=2026-09-03, hour=amc` が存在したが、
  normalizerが日付を00:00 UTCとしていたため、米国市場中には「過去イベント」と
  誤認された。
- SNOW: 決算発表翌日の急騰に対する通常モメンタム追随で、post-event chaseだった。
- 既存R18-Bの全履歴検証では、深いstop 29件中、保有中の決算またぎは1件のみ。
  したがって決算近接を全銘柄へ即時ブロックする根拠は不足している。

## 今回の変更範囲

1. Finnhubの `hour=bmo/amc` をAmerica/New_Yorkの08:00/16:00としてUTCへ正規化する。
   hour不明は保守的に16:00 ETとして、同日イベントを早期に過去扱いしない。
2. 収集期間に過去2日を含め、決算直後の通常エントリーも観測可能にする。
3. 通常BUY候補について、決算7日前から発表時刻までを `pre_event`、発表後2日を
   `post_event` として `data/earnings_proximity_shadow_log.jsonl` に記録する。
4. `event_swing_v1` は意図的なイベント戦略なので記録対象だが、would_block=Falseとする。

**発注、サイジング、EntryFilter、戦略設定は変更しない。**

## 前向き評価基準

- 最低観測量: 通常戦略BUY候補30件以上、うちpre/post-event該当10件以上。
- 評価対象: shadow開始後に発生した候補のみ。開始前PATH/SNOWは原因再現であり、
  効果推定の標本には混ぜない。
- 比較: 該当候補と非該当候補の5/10営業日リターン、stop_loss率、PF、expectancy。
- 昇格検討条件: 該当群のcost-adjusted PF<1かつexpectancy<0、非該当群との差が
  同方向で、paper A/Bの事前固定条件を新たに作成できること。
- 本番反映には `docs/promotion_governance.md` の全条件（事前登録、paper A/B、
  R13-C後OOS再検証）を必須とする。shadow結果だけでは昇格しない。
