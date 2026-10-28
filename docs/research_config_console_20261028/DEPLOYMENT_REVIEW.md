# 配備・切戻し（準備のみ）

1. 今回は稼働コード/Consoleへ適用しない。latest Consoleはコピーでの統合であり、追加audit数量fixの稼働反映ではない。
2. 配備する場合は現行HEAD/dirty/index・稼働source・実行writer/所有者を再確認し、本packetのcapture baseとの一致を点検。前回candidateやcombined/deltaを二重適用しない。
3. 今回追加のruntimeはpaper_demo、config_instance_specs、dashboard_serviceだけ。基準候補の取消/送信guardを保持し、record flagはdefault OFF。取得失敗を0/なしへ変更しない。
4. 主口座/台帳/注文journal・金融state・停止状態を巻き戻さず、まず追加差分だけコード逆適用を候補にする。前回の安全guardなしmainへ全面的に戻す手順ではない。record event schemaは変更なしで、旧recorder writerが新11familyを読む保証を主張しない（receiptはappend-only観測）。
5. コピーの適用/逆適用を検証済み。実scheduler停止/整合backup/コード反映/Console lifecycle/真正定期実行は未実施。既存launchd所有者を確認し、Gatewayや二重Consoleを起動しない。
6. 研究packetのproxyを過去台帳へ書き戻さず、スコア閾値やBUY制限を自動変更しない。独立研究と本番配備/経済gateは別。

詳細な既存手順は前回timing_config_readinessのDEPLOYMENT_REVIEWを参照。公開Push/PR/mergeは今回の範囲に含まない。
