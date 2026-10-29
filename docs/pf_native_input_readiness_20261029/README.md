# PF比較のnative接続・入力資格点検 — 公開投影版（2026-10-29）

元の封印済み私有packetではありません。[公開範囲と除外](PUBLIC_SCOPE.json)を参照。

- 既存ComparisonBookを再利用し、独立cash/lot/pending/予約/PF履歴、原子的イベント、部分約定、出来高容量、bid/ask・execution/arrival時計・TIF・再起動を研究用adapterへ接続。
- Aは原EntryFilterEngine、BはPF成績Gate3/4だけを除去し、購入禁止・出来高・HALT・口座不明・SELL・既存数量/Exitを維持。原filterのdisabled=False。
- 引け前execution/引け後arrivalのTIF境界を修正。明示失効後の遅延通知は未認定として拒否。
- 私有原本からの過去検証は全体3,530成功/2skip。重点47はその部分集合で合算しない。[元時点の検証集計](VALIDATION.json)のPush:falseは過去の状態。
- 公開版の追試は重点47・入力監査合成契約11・実CLI27対照・同作者別算術10checkpointのみ。私有履歴の再監査、全体3,530件、経済的A/B比較を再現したとは主張しない。CLIのHTTPは合成transportで外部通信をしない。
- 入力点検は判断4,532/価格33,501日次行の集計のみ。無信号分母、適格bid/ask・直前1分volume・利用可能時刻・企業行動・seedの経済資格は不足。未来11/2〜5の予定480検査は未観測で、記録事故/独立標本ではない。[集計](INPUT_AUDIT.json)。私有入力を除外したためこの集計の再計算は不可。
- A/B利益batch0/1、P4/S1/S2全体未完、T0未設定/F1未開始。10/30・11/06・11/13各18:00 JST、11/06不足込み一次結論を維持。

## 公開版追試

既存依存を持つPythonで `python -I -B verify_public.py --restore-modes --output /tmp/pf-public-replay.json`。全inventory/hashを確認した後、Gitで失われる0600/0700等のmodeをこの公開packet内に限り復元し、一時コピー上で技術追試する。macOS sandbox-execで外部通信と元稼働repositoryへの書込を拒否。`--check-only`はbytes/mode照合のみ。

`code/`は未配備候補の技術互換snapshotであり、rootへのコピー/適用指示ではない。個人口座・原台帳・生判断・価格入力・旧実観測を含めない。本番適用・記録ON・注文/取消・PF解除・main統合・CI完了なし。元の封印済み成果・main/indexは不変。
