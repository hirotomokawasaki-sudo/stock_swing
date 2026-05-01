# GW緊急実装計画：リスク管理機能

**期間:** 2026年5月2日（金）- 5月7日（水）  
**目標:** Tier 1-2（タスク1-7）完全実装 + ドライランテスト

---

## 📋 実装タスク一覧

### ✅ Day 1: 5/2（金）- Kill Switch基盤

#### Task 1.1: RiskMonitorクラス実装 ⏰ 4h
**Status:** ✅ 完了

**成果物:**
- `src/stock_swing/risk/risk_monitor.py` (12KB, 380行)
- `src/stock_swing/risk/__init__.py`
- `test/test_risk_monitor.py` (テストコード, 150行)

**機能:**
- Drawdown計算（ピークからの下落率）
- Kill Switch（-12% DDで自動発動）
- Warning Alert（-8% DD）
- Daily Loss Limit（-3%/日）
- State persistence（状態保存・復元）

**テスト:**
```bash
cd ~/stock_swing
source venv/bin/activate
pytest test/test_risk_monitor.py -v

# 期待結果: 10 tests passed
```

---

#### Task 1.2: paper_demo.pyへの統合 ⏰ 3h
**Status:** 🔄 次のステップ

**実装箇所:**
```python
# paper_demo.py の構造

def main():
    # 1. Runtime Mode check
    # 2. Kill Switch check
    # 3. Market Hours check
    # 4. Broker connection
    
    # >>> 🚨 ここにRiskMonitor追加
    
    # 5. Data Collection
    # 6. Feature Engineering
    # 7. Strategy Signals
    # 8. Decision Engine
    # 9. Order Submission
    
    # >>> 🚨 ここで再度Drawdown確認
```

**実装内容:**
```python
# Step 1: Import
from stock_swing.risk.risk_monitor import RiskMonitor

# Step 2: Initialize (main関数の最初)
def main():
    # ... existing code ...
    
    # === Risk Monitor Initialization ===
    account = broker.fetch_account()
    equity = float(account['equity'])
    
    risk_monitor = RiskMonitor(
        equity_start=equity,
        kill_switch_threshold=-0.12,
        warning_threshold=-0.08,
        daily_loss_limit=-0.03
    )
    
    # Check drawdown BEFORE trading
    status = risk_monitor.check_drawdown(equity)
    
    if status == 'KILL_SWITCH_ACTIVATED':
        print("🚨 KILL SWITCH ACTIVATED - Trading disabled")
        # Liquidate all positions
        liquidate_all_positions(broker)
        sys.exit(1)
    
    if status == 'DAILY_LOSS_LIMIT_EXCEEDED':
        print("❌ Daily loss limit exceeded - Skipping today")
        sys.exit(0)
    
    if status == 'WARNING':
        print("⚠️ Drawdown warning - Proceeding with caution")
    
    # ... continue with normal trading ...
```

**Liquidation機能:**
```python
def liquidate_all_positions(broker):
    """Liquidate all positions immediately (market orders)."""
    try:
        positions = broker.fetch_positions()
        if not positions or len(positions) == 0:
            logger.info("No positions to liquidate")
            return
        
        logger.critical(f"Liquidating {len(positions)} positions...")
        
        for pos in positions:
            symbol = pos.get('symbol')
            qty = int(float(pos.get('qty', 0)))
            
            if qty > 0:
                # Long position: sell
                broker.submit_order(
                    symbol=symbol,
                    side='sell',
                    order_type='market',
                    qty=qty,
                    time_in_force='day'
                )
                logger.critical(f"  SELL {qty} {symbol} (market)")
            elif qty < 0:
                # Short position: buy to close
                broker.submit_order(
                    symbol=symbol,
                    side='buy',
                    order_type='market',
                    qty=abs(qty),
                    time_in_force='day'
                )
                logger.critical(f"  BUY {abs(qty)} {symbol} to close short")
        
        logger.critical("All liquidation orders submitted")
    except Exception as e:
        logger.error(f"Failed to liquidate positions: {e}")
```

---

#### Task 1.3: Kill Switchテスト ⏰ 2h
**Status:** ⏳ Pending

**テストシナリオ:**

**Test 1: 通常運用（OK）**
```bash
# Scenario: Equity at $1,000,000
# Expected: Trading proceeds normally

cd ~/stock_swing
source venv/bin/activate
python src/stock_swing/cli/paper_demo.py --dry-run
```

**Test 2: Warning Alert（-8%）**
```bash
# Scenario: Manually set equity to $920,000 (-8%)
# Expected: Warning logged, trading continues

# Modify test script to simulate:
equity_test = 920_000  # -8% DD
```

**Test 3: Kill Switch（-12%）**
```bash
# Scenario: Manually set equity to $880,000 (-12%)
# Expected: Kill switch activates, all positions liquidated

equity_test = 880_000  # -12% DD
```

**Test 4: Daily Loss Limit（-3%）**
```bash
# Scenario: Day starts at $1M, drops to $970K
# Expected: Trading stopped for the day

equity_day_start = 1_000_000
equity_current = 970_000  # -3%
```

**成功基準:**
- ✅ Kill switch確実に発動（-12%）
- ✅ Warning alert表示（-8%）
- ✅ Daily loss limit機能（-3%/日）
- ✅ Liquidation orders送信確認

---

### 📅 Day 2: 5/3（土）- Email通知システム

#### Task 2.1: AlertManagerクラス実装 ⏰ 4h

**ファイル:** `src/stock_swing/notifications/alert_manager.py`

**機能:**
```python
class AlertManager:
    """Email/Slack notification system."""
    
    def __init__(self, smtp_config: dict):
        # SMTP設定（Gmail, SendGrid, etc.）
        pass
    
    def send_warning(self, subject: str, body: str):
        """Send warning-level alert."""
        pass
    
    def send_critical(self, subject: str, body: str):
        """Send critical-level alert."""
        pass
    
    def send_daily_summary(self, summary: dict):
        """Send daily trading summary."""
        pass
```

**SMTP設定例（.env）:**
```bash
# Email notifications
ALERT_EMAIL_TO=user@example.com
ALERT_EMAIL_FROM=stockswing@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
```

---

#### Task 2.2: RiskMonitorへの通知統合 ⏰ 2h

**実装:**
```python
# RiskMonitor.__init__に追加
from stock_swing.notifications.alert_manager import AlertManager

class RiskMonitor:
    def __init__(self, ..., alert_manager: Optional[AlertManager] = None):
        self.alert_manager = alert_manager
    
    def send_warning_alert(self, equity, drawdown):
        if self.alert_manager:
            self.alert_manager.send_warning(
                subject="⚠️ [Stock Swing] Drawdown Warning",
                body=self._format_warning_email(equity, drawdown)
            )
    
    def send_critical_alert(self, equity, drawdown):
        if self.alert_manager:
            self.alert_manager.send_critical(
                subject="🚨 [Stock Swing] KILL SWITCH ACTIVATED",
                body=self._format_critical_email(equity, drawdown)
            )
```

---

#### Task 2.3: Email通知テスト ⏰ 2h

**Test 1: Warning Email**
```bash
# Send test warning
python -c "
from stock_swing.notifications.alert_manager import AlertManager
am = AlertManager()
am.send_warning('Test Warning', 'This is a test')
"
```

**Test 2: Critical Email**
```bash
# Send test critical
python -c "
from stock_swing.notifications.alert_manager import AlertManager
am = AlertManager()
am.send_critical('Test Critical', 'Kill switch test')
"
```

**成功基準:**
- ✅ Warning email受信確認
- ✅ Critical email受信確認
- ✅ 件名・本文正しい

---

### 📅 Day 3: 5/4（日）- Position Limit強制

#### Task 4.1: Position Limit強制チェック実装 ⏰ 3h

**実装箇所:** `paper_demo.py` の注文送信前

```python
# Before order submission
MAX_POSITION_PER_SYMBOL_PCT = 0.08
MAX_POSITION_PER_ETF_PCT = 0.15

for decision in actionable:
    symbol = decision.symbol
    proposed_qty = decision.proposed_order.qty
    price = decision.proposed_order.price  # or current market price
    
    # Get existing position value
    existing_position = current_positions_full.get(symbol, {})
    existing_value = float(existing_position.get('market_value', 0))
    
    # Calculate new total value
    estimated_order_value = proposed_qty * price
    total_value = existing_value + estimated_order_value
    
    # Determine limit
    is_etf = symbol in ETF_SYMBOLS
    limit_pct = MAX_POSITION_PER_ETF_PCT if is_etf else MAX_POSITION_PER_SYMBOL_PCT
    max_position_value = equity * limit_pct
    
    # Enforce limit
    if total_value > max_position_value:
        asset_type = "ETF" if is_etf else "Stock"
        print(f"⚠️ SKIP {symbol}: Position limit exceeded")
        print(f"   Existing: ${existing_value:,.0f}")
        print(f"   Proposed: ${estimated_order_value:,.0f}")
        print(f"   Total: ${total_value:,.0f}")
        print(f"   Limit: ${max_position_value:,.0f} ({limit_pct:.0%} {asset_type})")
        continue  # Skip this order
    
    # Proceed with order
    # ...
```

---

#### Task 4.2: Position Limitテスト ⏰ 2h

**Test Scenario:**
```bash
# Scenario 1: 通常注文（上限以下）
# NVDA: Existing $40K, New $30K → Total $70K < $80K (8%)
# Expected: Order proceeds

# Scenario 2: 上限超過
# NVDA: Existing $70K, New $20K → Total $90K > $80K (8%)
# Expected: Order skipped

# Scenario 3: ETF上限
# SOXX: Existing $120K, New $50K → Total $170K > $150K (15%)
# Expected: Order skipped
```

**成功基準:**
- ✅ 8%/15%上限を確実に守る
- ✅ 超過時にスキップ
- ✅ ログに明確な記録

---

### 📅 Day 4: 5/5（月）- Daily Loss Limit & Health Check

#### Task 5.1: Daily Loss Limit統合確認 ⏰ 2h

**実装確認:**
- RiskMonitor.check_drawdown()で既に実装済み
- paper_demo.pyでの処理確認
- テスト実施

**Test:**
```bash
# Scenario: Day starts at $1M, current $965K (-3.5%)
# Expected: Trading stopped for today
```

---

#### Task 6.1: HealthCheckクラス実装 ⏰ 3h

**ファイル:** `src/stock_swing/monitoring/health_check.py`

```python
class HealthCheck:
    """System health monitoring.
    
    Features:
    - Cron job execution monitoring
    - Broker API connection check
    - Last execution time check
    """
    
    def check_cron_health(self) -> bool:
        """Check if cron is running properly."""
        # Check last execution timestamp
        pass
    
    def check_broker_connection(self) -> bool:
        """Check Broker API connectivity."""
        pass
    
    def send_health_alert(self, issue: str):
        """Send health check alert."""
        pass
```

---

#### Task 6.2: daily_health_check.pyスクリプト ⏰ 2h

**ファイル:** `scripts/daily_health_check.py`

```bash
#!/usr/bin/env python3
"""
Daily health check script.

Run via cron: 0 8 * * * python ~/stock_swing/scripts/daily_health_check.py
"""

from stock_swing.monitoring.health_check import HealthCheck
from stock_swing.notifications.alert_manager import AlertManager

def main():
    hc = HealthCheck()
    am = AlertManager()
    
    # Check last execution
    if not hc.check_last_execution(max_hours=24):
        am.send_warning(
            subject="⚠️ [Stock Swing] Cron Job Failure",
            body="paper_demo.py has not run in 24+ hours"
        )
    
    # Check broker connection
    if not hc.check_broker_connection():
        am.send_warning(
            subject="⚠️ [Stock Swing] Broker Connection Failed",
            body="Unable to connect to Alpaca API"
        )
    
    print("Health check complete")

if __name__ == '__main__':
    main()
```

**Cron設定:**
```bash
# Add to crontab
0 8 * * * cd ~/stock_swing && source venv/bin/activate && python scripts/daily_health_check.py
```

---

### 📅 Day 5: 5/6（火）- ログ強化

#### Task 7.1: 詳細ログ設定 ⏰ 3h

**実装:**
```python
# paper_demo.py のログ設定強化

import logging
from datetime import datetime

# Detailed log file
log_file = f"logs/trading_detailed_{datetime.now():%Y%m%d}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# Log all decisions
for decision in decisions:
    logger.info(f"Decision: {decision.symbol} {decision.action} {decision.proposed_order}")

# Log drawdown checks
logger.info(f"Drawdown check: {drawdown:.2%} (status: {status})")

# Log order submissions
logger.info(f"Order submitted: {order.symbol} {order.side} {order.qty} @ {order.order_type}")
```

**ログ出力例:**
```
2026-05-06 09:30:15 | INFO  | === Stock Swing Paper Demo ===
2026-05-06 09:30:16 | INFO  | Account: $1,000,000.00
2026-05-06 09:30:17 | INFO  | Drawdown check: -2.3% (status: OK)
2026-05-06 09:30:18 | INFO  | Decision: NVDA buy 100 @ market
2026-05-06 09:30:19 | INFO  | Position limit check: NVDA OK ($70K < $80K)
2026-05-06 09:30:20 | INFO  | Order submitted: NVDA buy 100 @ market
```

---

#### Task 7.2: ログローテーション設定 ⏰ 1h

```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    'logs/trading.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=30  # Keep 30 days
)
```

---

### 📅 Day 6: 5/7（水）- リモート停止 & 統合テスト

#### Task 8.1: リモート停止機能 ⏰ 2h

**実装:**
```python
# paper_demo.py の最初

MANUAL_KILL_SWITCH_FILE = Path('data/kill_switch_manual.txt')

if MANUAL_KILL_SWITCH_FILE.exists():
    logger.critical("🚨 Manual kill switch detected - Trading disabled")
    logger.critical(f"Remove {MANUAL_KILL_SWITCH_FILE} to resume trading")
    sys.exit(1)
```

**使用方法:**
```bash
# リモートから停止
ssh user@server
touch ~/stock_swing/data/kill_switch_manual.txt

# 再開
rm ~/stock_swing/data/kill_switch_manual.txt
```

---

#### Task 9: 統合テスト（ドライラン） ⏰ 4h

**Test Suite:**

**Test 1: Normal Operation**
```bash
# Full dry-run with all features
cd ~/stock_swing
source venv/bin/activate
python src/stock_swing/cli/paper_demo.py --dry-run

# Expected:
# - Risk check: OK
# - Position limits enforced
# - Orders generated
# - Log file created
```

**Test 2: Warning Alert**
```bash
# Simulate -8% DD
# Modify state file: equity_peak = 1,100,000
# Run with equity = 1,012,000 (-8%)

# Expected:
# - Warning logged
# - Email sent
# - Trading continues
```

**Test 3: Kill Switch**
```bash
# Simulate -12% DD
# equity_peak = 1,100,000
# equity = 968,000 (-12%)

# Expected:
# - Kill switch activated
# - Liquidation orders generated
# - Trading stopped
# - Critical email sent
```

**Test 4: Position Limit**
```bash
# Create position with $75K NVDA
# Try to add $20K more

# Expected:
# - Order skipped
# - Log: Position limit exceeded
```

**Test 5: Daily Loss Limit**
```bash
# equity_day_start = 1,000,000
# equity_current = 965,000 (-3.5%)

# Expected:
# - Daily loss limit exceeded
# - Trading stopped
# - Alert sent
```

**Test 6: Manual Kill Switch**
```bash
# Create kill_switch_manual.txt
touch data/kill_switch_manual.txt

# Run paper_demo
# Expected: Immediate exit with message
```

**Test 7: Health Check**
```bash
# Run health check script
python scripts/daily_health_check.py

# Expected:
# - Cron status checked
# - Broker connection checked
# - Report generated
```

---

## 📊 完成チェックリスト

### Tier 1（必須）

- [ ] **1. Kill Switch**
  - [ ] RiskMonitorクラス実装
  - [ ] paper_demo.py統合
  - [ ] -12% DDで発動確認
  - [ ] Liquidation機能確認
  
- [ ] **2. Email通知**
  - [ ] AlertManagerクラス実装
  - [ ] SMTP設定
  - [ ] Warning email送信確認
  - [ ] Critical email送信確認
  
- [ ] **3. Health Check**
  - [ ] HealthCheckクラス実装
  - [ ] daily_health_check.py作成
  - [ ] Cron設定
  - [ ] 24h未実行検出確認

### Tier 2（強く推奨）

- [ ] **4. Position Limit強制**
  - [ ] 8%/15%チェック実装
  - [ ] 超過時スキップ確認
  - [ ] ログ記録確認
  
- [ ] **5. Daily Loss Limit**
  - [ ] -3%/日チェック実装
  - [ ] 停止機能確認
  - [ ] Alert送信確認
  
- [ ] **6. ログ強化**
  - [ ] 詳細ログ設定
  - [ ] ローテーション設定
  - [ ] 出力確認
  
- [ ] **7. リモート停止**
  - [ ] Manual kill switch実装
  - [ ] ファイル監視確認
  - [ ] SSH経由テスト

### 統合テスト

- [ ] **Dry-run Test Suite**
  - [ ] Test 1: Normal operation
  - [ ] Test 2: Warning alert (-8%)
  - [ ] Test 3: Kill switch (-12%)
  - [ ] Test 4: Position limit
  - [ ] Test 5: Daily loss limit
  - [ ] Test 6: Manual kill switch
  - [ ] Test 7: Health check

---

## 📅 本番稼働開始

**日時:** 2026年5月7日（水）13:00

**稼働確認:**
```bash
# 本番Cron実行
# 次回の自動実行を監視
tail -f logs/trading_detailed_20260507.log

# Expected:
# - Risk check実行
# - 通常取引継続
# - 日次サマリーEmail受信（18:00）
```

**GW期間の監視:**
- 5/7（水）13:00: 初回稼働確認
- 5/8（木）以降: 日次Email確認のみ
- 問題発生時: Email通知 → リモート対応

---

## 🎯 成功基準

### 機能面
✅ Kill Switch確実に発動（-12%）  
✅ Warning Alert確実に送信（-8%）  
✅ Position Limit確実に守る（8%/15%）  
✅ Daily Loss Limit機能（-3%/日）  
✅ Health Check稼働  
✅ ログ詳細記録  
✅ リモート停止可能

### テスト面
✅ 全7項目のドライランテスト成功  
✅ Email通知受信確認  
✅ Liquidation orders確認

### 運用面
✅ 5/7（水）13:00に本番稼働開始  
✅ GW中（5/3-5/6）無事故  
✅ 5/8（木）以降も安定稼働

---

**実装担当:** OpenClaw Assistant  
**作成日:** 2026年5月2日（金）
