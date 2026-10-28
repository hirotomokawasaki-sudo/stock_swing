# 実装テスト基準

- [x] public timing helpers: 正常/祝日/DST/early close/範囲外/aware/不正/未来。実selectorでHTTPのみ置換、DELETE/POST/理由保持確認。
- [x] 境界70時刻ケース。追加設定5契約：construct失敗、not_reached/再finalize no-op、値変更/秘密拒否、書込不能時も元例外維持。
- [x] 状態遷移：attempt→observed/construction_failed、finalize→not_reached/changed/unavailable、finalize冪等。取消journal全遷移は既存37契約と38対照を保持。
- [x] config→recorder耐久event→実CLI summary JSON→renderer。33CLIで生envを記録せず、optional/mandatory error・dry-run分岐・warning/終了コードを確認。
- [x] 旧版75契約43fail/32pass、候補75pass。incident名/日/HEADをtest docstringへ明記。
- [x] 全体3089pass/3skip＋localhost1pass、正常CLI40。重点/コピー追試は全体件数に重複加算しない。
- [x] 本番未適用、raw金融fixtureはpinsのみ。全設定/全caller/実broker/利益価値の証明ではない。
