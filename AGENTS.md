# AGENTS.md — stock_swing プロジェクト指示

このファイルは OpenClaw アシスタントが stock_swing で作業するときに
セッション開始時または作業開始前に読む指示書です。

---

## 必読ファイル（作業前に確認すること）

1. `docs/console_improvement_tasks.md` — **唯一の正式な改善計画**
   - R0-v2 が全ロードマップのブロッカー
   - 「やらないこと」セクションを必ず確認する

2. `RUNTIME_MODES.md` — runtime mode の定義と禁止事項

3. `docs/testing_standards.md` — **テスト品質基準（必読）**

---

## 実装時の絶対ルール

### コード変更
- `config/runtime/current_mode.yaml` の `mode` を `paper` 以外にしない
- `--preserve-attribution` なしで rebuild スクリプトを実行しない
- ETF-first / stock-shadow への恒久変更はユーザー承認なしに行わない

### テスト（最重要）
**`docs/testing_standards.md` のチェックリストを実装ごとに埋めること。**

具体的に毎回確認すること：
- [ ] 新しい public 関数に正常系 + ファイル欠損/破損フォールバックテスト
- [ ] ステートマシンの全遷移（中断遷移 + 逆方向ブロックを含む）
- [ ] 値のレイヤー伝播（config → service → summary → renderer）
- [ ] acceptance criteria に対応するテスト
- [ ] バグ修正の場合はバグ再現テスト（incident 名・commit を docstring に記載）
- [ ] `python -m pytest --tb=short -q` で全テスト PASS

「実装後に個別指示があればテストを強化する」ではなく、
**最初から基準を満たして commit すること。**

### コミット前
```
python -m pytest --tb=short -q
git add -A && git diff --cached --stat
git commit -m "<phase>: <1行の説明>\n\n<詳細>"
```

---

## 現在のフォーカス（2026-07-22）

```
R0-v2-A  ✅ 完了（2026-07-22 commit 2248eb2 + d764953）
R0-v2-B  🔲 次のアクション（ledger integrity: overlap 41件・reversed_chron 62件）
```

**07-31 Go/No-Go まで残り 9 日。R0-v2 完了が前提条件。**
