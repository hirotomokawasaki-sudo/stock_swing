# testing_standards対応

- [x] public helper/結果モデル/出力：正常・数量境界・人no・flat/反対方向、main結果を実scriptで検証。
- [x] 欠損/破損：runtime/position qty/open order・journal/marker/部分行/不正遷移・symlink。空/0へfallbackしない。
- [x] 状態/永続性：prepared→unknown/accepted/rejected、strict restart読込、既記録非再送・qty変化/逆遷移拒否。新しいポジション世代は未認定として保留。
- [x] fsync境界：初期化/prepare（送信前）/outcome（送信後）。出力成功と耐久成功を混同しない。
- [x] レイヤー：Result state/数量/理由→dict→人/JSON→exit。未観測はnull、失敗時の無条件完了なし。
- [x] Acceptance/Regression：test_ac_命名。HEAD8909e79のACK喪失再実行を修正前2失敗で確認し候補で成功。
- [x] 外部I/Oだけ代替。実BrokerClient/guard/journal/flockを使用。実プロセス並行・受付後killも確認。
- [x] 既存provider/記録/上限/競合/設定/分類の重点295を保持。新規60と合わせ355。
- [x] 全体2,959成功/3skip/localhost1deselect、分離localhost1成功。重複なし計2,960。既存collection warning1を保存。
- [x] 通常CLI40の凍結結果一致、直接script148対照＋並行4、sandboxで外向き通信・本番書込を拒否。
- [ ] 本番適用/実口座・実provider意味/全caller閉包/新世代自動認定/電源断/全履歴消失は対象外・未認定。

全体回帰の私有fixture2つはpinのみ。packet-onlyの全体回帰再実行と偽らず、重点と実入口の追試を別結果として記載する。commit/pushやservice restartは実行していない。
