# paper_demo 確認チェックリスト（2026-05-11 夜）

## 🎯 確認目的
1. 2026-05-07 実施の軽量化効果測定
2. telegram_notifier 改善効果測定（特に midday）
3. T15 完了判定の材料収集

---

## ⏰ 確認タイミング

| Job | 実行時刻 | 確認開始時刻 | 期待実行時間 |
|-----|---------|-------------|------------|
| premarket | 23:00 | 23:30 | ~30分 |
| market_open | 23:05 | 23:35 | ~30分 |
| midday | 翌 02:00 | 翌 02:30 | ~25分 |
| market_close | 翌 05:55 | 翌 06:25 | ~20分 |

---

## 📋 確認項目

### 1. premarket (23:00 JST)

#### A. 基本ステータス
- [ ] `status` = ok / error
- [ ] `deliveryStatus` = delivered / unknown
- [ ] `durationMs` の記録

#### B. 実行時間確認
- [ ] 前回（27.8分）より短縮されているか？
- [ ] 目標: **20分以内**
- [ ] 実績: ______ 秒（______ 分）

#### C. エラー有無
- [ ] SIGTERM 発生有無
- [ ] Telegram 送信成功確認
- [ ] 注文処理完了確認

#### D. Summary 内容
- [ ] Decision count
- [ ] Actionable count
- [ ] Submitted order count

---

### 2. market_open (23:05 JST)

#### A. 基本ステータス
- [ ] `status` = ok / error
- [ ] `deliveryStatus` = delivered / unknown
- [ ] `durationMs` の記録

#### B. 実行時間確認
- [ ] 前回（33.5分）より短縮されているか？
- [ ] 目標: **20分以内**
- [ ] 実績: ______ 秒（______ 分）

#### C. エラー有無
- [ ] SIGTERM 発生有無
- [ ] Telegram 送信成功確認
- [ ] 注文処理完了確認

#### D. Summary 内容
- [ ] Decision count
- [ ] Actionable count
- [ ] Submitted order count

---

### 3. midday (翌 02:00 JST) **最重要**

#### A. 基本ステータス
- [ ] `status` = ok / error
- [ ] `deliveryStatus` = delivered / unknown
- [ ] `durationMs` の記録

#### B. Telegram 送信確認 🔥
- [ ] 前回の `HttpError: sendMessage failed!` が解消されているか？
- [ ] リトライログの有無確認
- [ ] 送信成功確認

#### C. 実行時間確認
- [ ] 前回（33.6分）より短縮されているか？
- [ ] 目標: **20分以内**
- [ ] 実績: ______ 秒（______ 分）

#### D. エラーログ確認
```bash
# Cron runs でエラー確認
openclaw cron runs --job midday --limit 3

# Session logs で詳細確認（必要なら）
openclaw sessions history <session-key> --include-tools
```

---

### 4. market_close (翌 05:55 JST)

#### A. 基本ステータス
- [ ] `status` = ok / error
- [ ] `deliveryStatus` = delivered / unknown
- [ ] `durationMs` の記録

#### B. 実行時間確認
- [ ] 前回（23.2分）より短縮されているか？
- [ ] 前々回の異常な速さ（1.2分）の再現有無
- [ ] 実績: ______ 秒（______ 分）

#### C. エラー有無
- [ ] SIGTERM 発生有無
- [ ] Telegram 送信成功確認

---

## 🎯 T15 完了判定基準

### ケースA: 完了 ✅
以下の**すべて**を満たす場合:
- [ ] 4ジョブすべて `status=ok`
- [ ] 4ジョブすべて `deliveryStatus=delivered`
- [ ] premarket / market_open の実行時間が **25分以内**
- [ ] midday の Telegram 送信成功

→ **T15 を「完了」としてマーク**  
→ T20 は観測継続のみ

### ケースB: 部分完了 🟡
以下のいずれかに該当:
- [ ] 4ジョブすべて `status=ok` だが実行時間が依然長い（30分超）
- [ ] midday の Telegram 送信が再度失敗

→ **T15 を「部分完了」としてマーク**  
→ T20 の軽量設定分離を検討

### ケースC: 未完了 ❌
以下のいずれかに該当:
- [ ] いずれかのジョブで `status=error`（SIGTERM 以外）
- [ ] 複数ジョブで連続 timeout

→ **T15 を「未完了」として継続対応**  
→ 根本原因の再調査

---

## 📊 確認コマンド

### 全ジョブの最新実行確認
```bash
# premarket
openclaw cron runs --job d4fb64ec-6b22-4985-8945-552f986eec2b --limit 1

# market_open
openclaw cron runs --job 6eda856d-915a-4605-9428-8d5d13553176 --limit 1

# midday
openclaw cron runs --job a2986600-6e6a-4712-afa1-0ac8062e90fd --limit 1

# market_close
openclaw cron runs --job fc5f2185-2117-4413-9684-da79ac428869 --limit 1
```

### 実行時間の計算
```bash
# durationMs を秒・分に変換
# 例: 1665189 ms → 1665秒 → 27.8分
```

### エラーログ確認
```bash
# 最新のエラーがある場合
openclaw sessions history <session-key> --include-tools
```

---

## 📝 記録テンプレート

```markdown
### 2026-05-11 夜の実行結果

**premarket (23:00)**
- Status: ok / error
- Duration: ____ 秒 (____ 分)
- Delivery: delivered / unknown
- Notes: 

**market_open (23:05)**
- Status: ok / error
- Duration: ____ 秒 (____ 分)
- Delivery: delivered / unknown
- Notes:

**midday (02:00)**
- Status: ok / error
- Duration: ____ 秒 (____ 分)
- Delivery: delivered / unknown
- Telegram送信: 成功 / 失敗
- Notes:

**market_close (05:55)**
- Status: ok / error
- Duration: ____ 秒 (____ 分)
- Delivery: delivered / unknown
- Notes:

**総合評価**: ケースA / ケースB / ケースC
**T15判定**: 完了 / 部分完了 / 未完了
**T20判定**: 観測継続 / 軽量設定分離検討
```

---

**作成日**: 2026-05-11 09:52 JST  
**確認開始**: 2026-05-11 23:30 JST  
**最終判定**: 2026-05-12 06:30 JST
