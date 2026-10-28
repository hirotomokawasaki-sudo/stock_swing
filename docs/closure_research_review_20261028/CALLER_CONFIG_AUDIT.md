# 発注・設定の閉包点検と最小差分案

## 対象・限界

稼働checkout HEAD `8909e79c1a83e04d508715b132575625454b7856`。`src/`・`scripts/`・`console/`のPython344ファイルを`ast.parse`し、submit/cancel系12候補を抽出、HTTP/fetchの8境界を補った。[全件・行・hash](static_inventory.json)、[参照版](source_pins.json)。既知の呼出本文と[前回隔離候補](../emergency_corrections_20261028/README.md)の該当接続を読取照合した。全344ファイルを逐行レビューしたという意味ではない。

20境界の内訳：発注/委譲6、取消caller4、adapter mutation2、HTTP transport2、注文読取3、並列タスク3。layer間の同じ注文が複数回現れるので20件を20独立経路と数えない。alias代入・`__getattr__`委譲は本文を追跡したが、動的import、外部端末、shell生成、既存実行中プロセス等の完全性は未認定。最新scheduler状態は照会せず、静的呼出可能性を実行済みと扱わない。

## 実入口と適用境界

| 元sourceの境界 | 稼働側／最新隔離候補 | 受入不足・既存項目 |
|---|---|---|
| `cli/paper_demo.py:2844` → PaperExecutor | 稼働側は直接broker。候補は同ファイル2666付近でSubmissionGuardを渡し、executor内のaliasでsubmit_intentへ進む | 同じdecision IDの保護と、別runで生まれた異なるdecisionが同一経済意図かは別。後者は未認定／CMP-C01,K02 |
| `execution/paper_executor.py:231` → broker | 候補でも通常brokerを渡せる。SubmissionGuard型の場合だけ分岐する | 全constructorを安全と呼ばない。新たな実入口を追加する前にaccount/route/runtime/意図IDを受入／CMP-C01 |
| `scripts/emergency_sell.py:46`、`close_hpe_short.py:57` | 稼働sourceは未修正。候補は固定手動意図の記録/照会/lockと数量検査あり | 新しい保有世代・全外部発注者の協調は未認定。候補完成を稼働済みと混同しない／K14,K15 |
| `live_guarded_executor.py:277`、`production_executor.py:224` → 親submit | 承認/kill/auditを重ねる定義あり。344ファイル内に両classを生成する実運用factoryは見つからず、import/exportと定義を確認 | 稼働live経路として数えず、起動・同一性・retry/unknown・precomputed伝播は未受入のまま。mode変更しない／移行受入 |
| `cli/reconcile_orders.py:583,655,733` → cancel_order | plain broker。取消API後にcancelled登録/Cancelled表示、SELL733の直後734でexit reason削除。該当block内で終端注文再照会なし | cancel requested/unknown/pending_cancel/canceled/filledを区別。理由・予約枠を取消依頼だけで解放しない契約が必要／CMP-C01,C02,K14,K15 |
| `scripts/cancel_broker_orders.py:132` → fetch DELETE | previewが既定、`--execute`時のみ直接DELETE。表示はCANCEL_REQUESTEDで、既存表示を誤って「完了バグ」と呼ばない | 共通lock/取消記録の外。future guarded callerとの競合は未受入。今回はpreviewも実行しない／CMP-C01,K14 |
| `sources/broker_client.py:488,533,572,574` | cancel/submitと最終HTTP transport。候補ではPOST/DELETE mutation retryを停止 | adapterの1送信と別runの意図重複は別。adapterだけで同時操作・全caller・実broker exactly-onceを保証しない |
| `broker_client.py:369,420,468` | 注文一覧/単一注文の読取 | 発注件数から除外。page上限・鮮度・矛盾/404を別途資格化 |
| `paper_demo.py:956,1303`、`console/adapters/system_adapter.py:598` | ThreadPoolExecutorのタスクsubmit | 金融注文でないため発注coverageから除外 |

`SubmissionGuard.__getattr__`は既存brokerへ透過委譲する。**wrapperを渡すだけではcancel_order/fetch DELETEが同じlockを取得するわけではない**。同account-routeの協調手順が必要。ただしlockはbroker外の端末や約定を止める原子性ではない。

## 設定の限定分母

[前回の設定記録coverage](../r22_config_provenance_20261022/CONFIG_COVERAGE.md)、[実効設定対応表](../functional_safety_20261028/CONFIG_INPUT_MAP.md)、[今回のクラス/呼出/宣言field](config_inventory.json)を結んだ。最新候補の4種類receiptはexit/allocation/registry/intraday。旧P1/P2の全設定記録候補を丸ごと統合済みとはしない。

| クラス | 宣言field数 | 稼働source内from_env呼出数 | 最小の確認点 |
|---|---:|---:|---|
| DipBuySignalConfig | 3 | 2 | CLIと暗黙constructor、shadowと実利用を区別 |
| LotLevelExitDiagnosticConfig | 2 | 2 | 診断helperの既定値、SELL判断の非変更 |
| SectorShockHoldConfig | 12 | 2 | CLI/strategyの上書き、missing/invalid、exit優先順 |
| ShockAwareStagedExitConfig | 4 | 1 | mode/部分解消率/確認session/上限、整数化との接続 |
| VolatilityGateConfig | 2 | 3 | CLI/暗黙helperのmodeと閾値 |
| DistanceFromHighConfig | 3 | 3 | 同上。既存shadow継続方針を保持 |
| NewsSentimentConfig | 6 | 2 | configとnews入力の欠損を区別 |
| RsiDiagnosticConfig | 3 | 2 | 診断記録とfilter採用を混同しない |
| NewsShockHoldConfig | 4 | 2 | held-symbol側の分岐、exit fallbackとの優先順 |
| **限定合計** | **39** | **19** | 9クラス。最新候補CLIにも各1箇所、計9のfrom_env呼出しが残る |

この39はdataclassの静的宣言数で、ユニーク環境変数数・記録済み数・実行済み数・全設定の分母ではない。現行process envは取得せず、`.env`の値や秘密は保存しない。追加の未閉包はPAPER_DEMO_*スイッチ、position_sizingの2環境設定、MarketCalendar、exit/intraday/cooldown/guardrail/experimentの下流default/override、CLI外helper。未使用entry YAMLを勝手に有効化しない。

## 最小差分・受入案（未実装、既存是正1バッチ内で適合を判断）

| 優先・既存項目 | 具体的な最小案 | 受入・保留条件 |
|---|---|---|
| 1／CMP-C01,C02,K14,K15 | 既存TradeEventStore/照会/account-route lockを再利用し、3取消blockとmanual DELETEの結果をrequested/unknown/terminalへ分離。SELL理由は終端整合前に消さない | DELETE受付→pending_cancel、受付後timeout、fillとcancel競合、部分約定後cancel、404、一覧上限、記録書込失敗、別process submitとの競合。POSTで代替解消しない。broker再照会が揃わなければ未完 |
| 2／CMP-C01,K02 | 使用する入口に限りguard資格を点検。別runのdecision IDを自動的に同じ/別意図と断定せず、発生源と正当な追加判断の契約を先に固定 | 同じ意図再実行0追加送信／正当な別意図は別判定／payload変更・ID不明は保留。live classの有効化はしない |
| 3／K04,K05 | 既存receipt方式で、まずCLIで実際に生成された9config instanceの適用値を消費時に記録する最小接続案。暗黙helperは別に残す | OFF時の注文/数量/SELL/出力不変、型/欠損/不正時の既存分岐と由来、JSON/summary/rendererへの伝播、secret拒否/記録失敗の明示。fieldを記録するだけで全reader閉包としない |

Agent：10/30 18:00 JSTに範囲/差分案と残閉包、11/06 18:00に既存是正枠適合・完了/未完、11/13 18:00に限定技術受入または不足。工数は上記受入範囲で見積もるため未確定。今回は実装着手や配備承認ではない。これら全完了を独立探索の一律前提に戻さない。
