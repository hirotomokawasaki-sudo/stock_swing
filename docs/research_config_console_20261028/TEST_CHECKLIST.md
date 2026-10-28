# 受入チェック

- [x] 5sessionの翌session入口・休場/週末・欠測を圧縮しない・不正OHLCV・右打切り・score同点/境界を確認（24件）
- [x] 全decisionのcoverage分割、1901event/19010算術セル/16区分の日先行集計を独立照合
- [x] EntryFilter/losing guard正常・生成失敗・fallback・拒否値・alias/list終点変更、file欠損/書込不能
- [x] 既存helper defaultと明示configの整合、暗黙fallbackの境界を文書化
- [x] runtime→receipt→summary JSON→text renderer、broker→service→JSON→実JS
- [x] 取消依頼/完了/partial/404を分離、再実行DELETE増加なし
- [x] audit小数/欠測qty回帰、正しい整数の互換性
- [x] 全体3156/2skip、既存warning1、重点・CLI・研究を重複加算しない
- [x] 実Chromeのタブ往復/reload/モバイル、文書stale・未知と稼働境界を保持
- [x] patch適用/逆適用・原本非変更・成果物inventory/byte/modeを確認
- [ ] 本番適用/実broker/真正定期実行、前向き資格・経済性：今回対象外/未認定

新たな状態遷移/注文政策は追加しない。コンストラクタの元例外/元fallbackを保持し、既存取消状態機械の受入を同じコピーで実施した。
