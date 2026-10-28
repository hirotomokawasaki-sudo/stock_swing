# 技術受入と未完範囲

## K03・今回の最小範囲

- [x] 正常値/確認済み空trades、既存thresholdとstop推定、明示overrideの計測済み範囲を維持。
- [x] 欠損/破損/非dict state/非list trades/不正status/不正open lot/equity/NaN/Infをunknownへ。
- [x] unknownでBUYだけを取り除きSELLを維持。unknown→有効stateへの回復も検証。
- [x] executorの不正保有schema/qty/price/NaN/Infで数量0、broker submit0。確認済み数量のSELLは維持。
- [x] service→JSON→rendererのnull/status/警告、実CLIでのrisk_budget_blocked stageとaudit event。
- [x] 旧sourceとの同一テスト対照、正常CLIの判断維持、全体回帰、保存copy追試、適用/逆適用のbyte照合。
- [ ] precomputed数量を直接受け取る全callerの入力資格/鮮度の検証。
- [ ] CLIの全上流不正broker応答/設定不正時に、必要なSELLとreportが継続できるかの全経路検証。
- [ ] 本番適用・正規scheduled run。技術テストを金融上の改善実証には使わない。

## K01・10/30に固める仕様

既存cap値を変えず、sizing後数量×有資格価格、保有/未約定/予約、同batch累積を同じ通貨/時点で集計する。ちょうど上限、超過、価格欠測、重複呼出し、部分約定/取消/拒否/再開、summary伝播を実入口で確認する。既存projected-band部品を優先し、汎用予約管理基盤を新設しない。今回の当該guard再現を全注文経路の不具合証明としない。

## K02・政策案（未採用・未実装）

- 同方向の複数意図を無条件に合算せず、銘柄単位の共通予算で選択・数量を決める。各戦略の根拠、採択/見送り、lot帰属を残す。
- BUY/SELL競合では、確認済み保有数量に対するリスク削減SELLを優先し、同runのBUYは保留する案をレビューへ出す。既存の市場時間/緊急SELL/数量確認は外さない。
- 上記は具体的なレビュー案であり、優先規則の承認済み表示や自動nettingはしない。複数戦略への配賦方法は未決として明示する。

## K04・最小是正仕様

CLI/設定/既定値の唯一の実効値と由来を表示し、未使用項目は未使用として扱う。YAML null/list/破損/型不正を入口で検証し、BUY停止・必要SELL/診断の継続条件を定める。欠損時fallbackと破損時挙動を混同しない。enabled/volume/filing/insider等を接続して新戦略に変えることは別のS3判断とし、今回ONにしない。
