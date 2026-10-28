# 反映・切戻しレビュー（手順のみ／本番で実行しない）

## 準備済みの差分

- base HEAD8909e79からはcombined.patch（27runtime＋20test/fixture）。前回封印候補からだけならdelta.patch（5runtime＋2test）。両方を重ねて適用しない。
- mainは7commitの未公開祖先を含むため、そのままpublicへpushしない。公開用には既公開e2d98eeをbaseに、旧cancel_config packet・新packet・更新した4計画をallowlistコピー。実runtime src/config/dataを追加配備しない。
- 実行中タスク/協調writerと非協調caller、実口座route/最新snapshot/予約残を確認できるまで「全面ready」としない。未知を0にしない。記録flagはOFFのまま。

## 本番導入を別途行う場合の順序

1. 現時点のHEAD/dirty/index/実行環境と適用対象が検証baseに一致するか読み取り確認。不一致なら再base・再検証する。
2. 影響する実scheduler/長寿命reader/writerを棚卸しし、停止範囲・所有者・戻し条件を具体化。今回は止めない。
3. 同一時点のコード・config・journal/initialized marker・金融stateを整合したbackupとして保存/検証する。journal削除やunknownの新ID迂回を行わない。
4. 差分適用・非送信canary・consumer summary/rendererを確認し、旧値/未到達/生成失敗/終点変更を分離する。実APIで合格したことにはしない。
5. service所有者/既存hookを確認して二重restartを避ける。本番serviceを今回起動/再起動しない。真正定期実行が出るまでは実運用確認未完。

## 戻し先と状態互換性

- 取消安全guardをまだ持たない元mainではなく、まず前回の封印済み安全候補をコード上の戻し先にする。core runtime・口座状態を勝手に戻さない。
- 新旧guardのjournal schemaは今回変更なし。コピー3条件でpending/canceledを旧guardが読み、追加DELETE0。unknown404はcallerがjournal前に非ゼロ停止し、journal/金融JSONは不変（読取互換性の成功ケースに加算しない）。
- snapshot/金融state/journalを古いbackupで上書きしない。以後の正当な書込があれば元backupを拒否し、追加変更を保全する。全writer/OS死/電源断の原子的復旧は未認定。
- [コピー試験](rollback_rehearsal.json)は運用の停止/backup restore/再開を実施した証拠ではない。

## 公開の境界

公開用allowlistのステージングと秘密点検までを準備する。commit/Push/PR/merge/main反映は未実施。公開subsetは私有fixtureを含まず、Gitで0600を保持できない。最新の私有候補の受入と、既公開候補のclone追試を混同しない。
