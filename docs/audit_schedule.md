# Trade Audit Schedule

## Purpose
定期的に取引データを監査し、Alpaca API のバグによる異常価格を早期検出する。

## Audit Scripts

### 1. audit_trades_with_market_data.py
**機能**: Yahoo Finance で過去の市場価格を取得し、全取引の Entry/Exit 価格を検証

**使用方法**:
```bash
cd ~/stock_swing
source venv/bin/activate
python scripts/audit_trades_with_market_data.py --recent-days 10
```

**検出内容**:
- Entry price が市場範囲外（30%以上乖離）
- Exit price が市場範囲外（30%以上乖離）

**出力**:
- 異常検出時: exit code 1 + 詳細レポート
- 正常時: exit code 0 + サマリー

---

### 2. reconcile_buy_orders.py
**機能**: BUY 注文の filled_avg_price を現在の市場価格と比較

**使用方法**:
```bash
cd ~/stock_swing
source venv/bin/activate
python -m stock_swing.cli.reconcile_buy_orders
```

**制限**:
- Alpaca Paper Trading API で quote が取得できない場合がある
- リアルタイム検証のため、古い注文には使えない

**代替**: `audit_trades_with_market_data.py` の方が信頼性が高い

---

## 推奨スケジュール

### Daily Audit (毎日)
```bash
# 毎日 06:00 JST に直近10日間の取引を監査
0 6 * * * cd ~/stock_swing && source venv/bin/activate && python scripts/audit_trades_with_market_data.py --recent-days 10 >> logs/audit_$(date +\%Y\%m\%d).log 2>&1
```

### Weekly Full Audit (毎週)
```bash
# 毎週月曜 07:00 JST に全取引を監査
0 7 * * 1 cd ~/stock_swing && source venv/bin/activate && python scripts/audit_trades_with_market_data.py >> logs/audit_full_$(date +\%Y\%m\%d).log 2>&1
```

---

## Alert Policy

### 異常検出時のアクション

1. **即座に確認**
   - 監査ログを確認
   - 異常取引の詳細を確認

2. **バックアップ作成**
   ```bash
   cd ~/stock_swing/data/tracking
   cp pnl_state.json pnl_state_backup_$(date +%Y%m%d_%H%M%S).json
   ```

3. **異常取引の削除**
   - Cleanup スクリプトを作成
   - PnL Tracker から異常取引を削除

4. **コンソール再起動**
   ```bash
   cd ~/stock_swing
   ./console/manage.sh restart
   ```

5. **Alpaca に報告**
   - 異常価格の事例をまとめて報告
   - API バグの修正を依頼

---

## Maintenance

### Log Cleanup
```bash
# 30日以上前のログを削除
find ~/stock_swing/logs -name "audit_*.log" -mtime +30 -delete
```

### Monthly Review
- 月末に監査ログをレビュー
- 異常検出の傾向を分析
- 必要に応じて閾値を調整

---

## Notes

- **Yahoo Finance API の制限**: 1分あたり約60リクエストまで（非公式）
- **監査時間**: 全108取引で約10-20秒
- **ネットワーク依存**: Yahoo Finance が利用不可の場合、監査は失敗する
