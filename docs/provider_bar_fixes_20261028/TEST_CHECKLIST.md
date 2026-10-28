# 実装チェックリスト

- [x] 新public helperの正常・境界・無効interval、disabled zero-storage、実provider HTTP fixture。
- [x] 欠落blob・改変blob・壊れたresponse・保存path破損を拒否。正常fallbackも同一要求interval。
- [x] 既存recorderのimmutable retry・競合・中断・seal・post-seal拒否をstorage45ケースで再確認。取引state machineは未変更。
- [x] CLI flag → Hybrid/Massive/Broker → Canonical → persisted run/normal reader。console renderer対象なし。
- [x] 実CLIで記録OFF/ON比較・欠落入力・保存拒否。main戻り値とdriver exitを区別。
- [x] Regression: provider_bar_contract_audit_20261023の5Min→日足、base8909e79。旧同6ケース5失敗、候補6成功。
- [x] 全体はrepository selector `python -m pytest --tb=short -q`。外部通信denyの2,718＋localhost限定1、3skip。重点90を合算しない。
- [x] import origin、SDK46 file、完全source閉包と199 source pin、manifestのpath/hash/modeを確認して追試。
- [x] 取引ルール・時刻修正・PF制約・console別件更新を保持。本番source/config/記録ON/原本/定期処理は未変更。
