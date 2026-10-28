# 呼出境界のread-only棚卸し

2026-10-28、稼働HEAD8909e79の`src/`と`scripts/`に対し、`PaperExecutor(`、`.submit_order(`、設定loader名をliteral検索。動的呼出・外部ツール・稼働プロセスの網羅証明ではない。今回の候補は[累積差分](combined.patch)。

| 呼出元 | 今回の効果／対象外 |
|---|---|
| `src/stock_swing/cli/paper_demo.py` → PaperExecutor | account ID付きSubmissionGuardを配線した今回の対象。K03/K01/K02、設定receiptと分類gapの主受入 |
| `src/stock_swing/execution/paper_executor.py` → broker | wrapperが渡された時のみintent記録/照会。既存のdirect callerを勝手に資格化せず、通常broker引数の経路は維持。直接生成したexecutor全件にjournalがあるとはしない |
| `scripts/emergency_sell.py` → broker.submit_order | 既存BrokerClientの自動mutation retry停止の影響は受けるが、安定ID/journal/照会guardは未配線。緊急SELLの意味を変える追加実装は本日行わず、11/06の残callerへ |
| `scripts/close_hpe_short.py` → broker.submit_order | 同上。個別short解消scriptの経済意図・数量を今回のlong BUY/SELL例だけで認定しない |
| `risk/portfolio_allocator.py` → allocation/registry loader | 設定異常のissueをbandでBUY不許可へ。分類はcanonical registryをpreflightへ渡す。一般的な全資金/通貨・分類保証ではない |
| CLI import時 → allocation/registry loader | rootごとの固定設定を読む。receiptはhash/実効値/エラーを記録。プロセス中の同時設定書換えの原子性は未認定 |
| `scripts/rebuild_pnl_state_from_broker.py`、`scripts/log_sector_rotation_shadow.py`、sector momentum feature → registry | loader型/有限値等の変更は共有される。今回それぞれの業務契約を実入力で受入したものではない。空registryのfallback/診断は個別レビュー対象、原台帳再構築/rotationの実行はしていない |

## 残る有界レビュー

- 11/06 18:00 JST：上記direct scriptの停止時運用/安定IDに必要な入力を具体化。未配線を「安全な全caller」に数えない。緊急SELLを新規BUYの一律停止へ巻き込まない。
- 11/13 18:00 JST：配備対象を選ぶ場合、他の隔離provider/記録候補との一体閉包、初期化前の未知注文、snapshotの取得順・復帰、journal保持とコード復帰を技術受入へ含める。
- 今回のGET照会で過去unknownが解決しても、そのrunの旧positions snapshotから次BUYを送らない。wrapper内で無効化を維持。新しいwrapperの構築自体がfreshnessの証明になるわけではなく、callerの新規snapshot契約は実入力で別に資格化する。
