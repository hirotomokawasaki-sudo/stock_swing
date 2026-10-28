# テスト基準対応

- 正常/上限/非有限/不正schema/欠損history/記録不能：test_cancellation_safetyとtest_config_instance_receipts。
- 遷移：prepared→requested/unknown/terminal、再起動再照会、終端逆転→unknown、重複DELETE禁止。全provider状態の安全認定ではない。
- 実入口：実selector3経路、manual preview/execute、reconcile mainの完了件数/終了、異常/再起動42 process。外部HTTPだけfixture化。
- 設定レイヤー：9クラスfrom_env→許可値複写→append/fsync→実CLI summary JSON→renderer。6条件18ケースとconfig_layer_checks.json。
- 不変：対象SELL/注文数量/判断、前回通常CLI40、全体3,015成功/3skip（localhost分離）。
- 実コード未配備、金銭/利益/全caller/実brokerの認定は対象外。private fixture未同梱。保存先427重点/取消38/設定18/通常40を別集計。
