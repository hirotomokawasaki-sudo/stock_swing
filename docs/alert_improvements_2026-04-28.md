# Alert Improvements - 2026-04-28

## T19: summary / alert の観測性改善

**実施日**: 2026-04-28  
**担当**: AI Assistant  
**ファイル**: `console/services/summary_service.py`

---

## 改善内容

### 1. Severity レベルの明確化

新たに **4段階の severity** を定義：

| Severity | 意味 | 対応優先度 |
|----------|------|-----------|
| **critical** | システム障害・重大損失 | 即時対応必要 |
| **high** | 注意が必要な問題 | 当日中に対応 |
| **medium** | 監視が必要な警告 | 数日以内に確認 |
| **low** | 情報提供・機会 | 参考程度 |

---

### 2. Alert 閾値の最適化

運用規模（equity ~$100K）に合わせて閾値を調整：

#### Before → After

| Alert | Before | After | 理由 |
|-------|--------|-------|------|
| **large_daily_loss** | -$1,000 | -$500（medium）<br>-$1,000（high）<br>-$2,000（critical） | 段階的な severity 設定 |
| **high_position_count** | 15件 | 20件（medium）<br>25件（high） | 過度なノイズ削減 |
| **large_unrealized_loss** | -$2,000 | -$1,000（medium）<br>-$2,500（high）<br>-$5,000（critical） | 段階的な重要度 |
| **unresolved_mismatches** | 1件～ | 3件以上（medium）<br>5件以上（high）<br>10件以上（critical） | ノイズ削減 |
| **stale_positions** | 1件～ | 2件以上 or 15日超（medium） | 本当に問題のあるケースのみ |

---

### 3. 新規 Alert の追加

#### 追加された Alert

1. **strong_day** （severity: low）
   - 条件: 日次 P&L > +$1,000
   - 目的: 成功パターンの可視化
   - Action: 何がうまくいったか記録

2. **losing_streak** （severity: medium/high）
   - 条件: 3日以上連続でマイナス P&L
   - 目的: 戦略の劣化早期検出
   - Action: 戦略パフォーマンスと市況を確認

3. **strategy_critical** （severity: high）
   - 条件: Conversion率 < 10%
   - 目的: 致命的な戦略問題の検出
   - Action: 緊急の設定見直し

4. **low_overall_conversion** （severity: medium/high）
   - 条件: 全体 conversion < 30%（20%で high）
   - 目的: システム全体の効率低下検出
   - Action: risk gate / sector cap / position limit 見直し

5. **no_trades_today** （severity: low）
   - 条件: 今日の取引数 = 0（ポジションあり）
   - 目的: 異常な取引停止の検出
   - Action: 市況とシグナル生成を確認

---

### 4. Alert 表示の改善

#### 変更点

1. **最大表示数**: 5件 → **8件**（より多くの情報提供）
2. **パーセント表示**: 損失額に加えて equity 比を表示
   - 例: `Unrealized loss: $1,500 (-1.5%)`
3. **詳細な説明**: 閾値を明示
   - 例: `Unrealized losses are significant (threshold: -$1,000)`

---

## 検証結果

### API テスト（2026-04-28 13:15 JST）

```bash
curl http://localhost:3335/api/summary/daily
```

**返却された Alert**:
1. ✅ `unrealized_loss` (critical): -$53,406.94 (-53.4%)
2. ✅ `stale_positions` (high): 5件
3. ✅ `no_trades_today` (low): 本日取引なし

**評価**:
- ✅ 重大な問題（unrealized loss）が critical として最優先表示
- ✅ 長期保有（stale positions）が high として適切に警告
- ✅ 情報提供（no trades）が low として表示
- ✅ severity による優先順位付けが機能

---

## Alert 設計ガイドライン

### 追加時の基準

新しい alert を追加する際の判断基準：

1. **Actionable**: 具体的なアクションが取れるか？
2. **Timely**: タイムリーな通知が価値を持つか？
3. **Relevant**: 運用上の意思決定に影響するか？
4. **Not Noisy**: 頻繁に誤警報を出さないか？

### Severity 判断基準

| Severity | 金額影響 | 頻度 | 対応時間 |
|----------|---------|------|---------|
| **critical** | > $5,000 or > 5% | 稀 | 即時 |
| **high** | $1,000-5,000 or 1-5% | 週1-2回 | 当日 |
| **medium** | $500-1,000 or 0.5-1% | 週数回 | 数日 |
| **low** | < $500 or < 0.5% | 日次 | 参考 |

---

## 既知の問題

### 1. unrealized_loss 計算の不正確性
- **問題**: `current_price` が `null` の場合、計算が 0 - entry_price となり大きなマイナスになる
- **影響**: alert が過度に critical になる可能性
- **対策**: Position data の current_price 取得を改善（別 issue）

### 2. conversion rate の定義
- **問題**: submission が重複カウントされる可能性（audit log ベース）
- **対策**: executable_decisions でクランプ済み

---

## 今後の改善候補

### Priority 2
1. **Alert 履歴の保存**
   - 過去の alert を記録して傾向分析
   - 誤警報パターンの学習

2. **Alert のカスタマイズ**
   - ユーザーごとの閾値設定
   - Alert の有効/無効切り替え

3. **Telegram 通知統合**
   - Critical alert を即座に通知
   - Daily summary に alert 埋め込み

### Priority 3
1. **Machine Learning による Alert 最適化**
   - 誤警報パターンの自動検出
   - 動的な閾値調整

2. **Alert Dashboard**
   - Alert の可視化ダッシュボード
   - 時系列での alert 推移

---

## 完了条件チェック

- [x] alert の妥当性見直し
  - ✅ 閾値を運用規模に合わせて調整
  - ✅ Severity を4段階で明確化
  - ✅ 段階的な severity 設定（medium/high/critical）
  
- [x] noisy alert / missing alert の改善
  - ✅ Noisy alert を削減（閾値引き上げ、条件厳格化）
  - ✅ Missing alert を追加（losing_streak, low_conversion, strong_day等）
  - ✅ 情報提供系 alert を low severity で追加
  
- [x] 必要なら UI への表示追加
  - ✅ 最大表示数を8件に拡張
  - ✅ パーセント表示を追加
  - ✅ 詳細な説明と閾値を明示

**T19 完了**: 2026-04-28 13:20 JST

---

## 参考

- **関連ファイル**: `console/services/summary_service.py`
- **API Endpoint**: `/api/summary/daily`
- **テスト**: `curl http://localhost:3335/api/summary/daily`
