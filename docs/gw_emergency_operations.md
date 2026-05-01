# GW期間中の緊急運用ガイド

**期間:** 2026年5月3日（土）- 5月6日（火）  
**対応:** 選択肢A（最低限の対策）

---

## 🎯 基本方針

**通常運用継続 + 最低限の監視**

- Cronジョブは通常通り稼働
- 1日1回（朝or夜）の簡易確認のみ
- 問題発生時はリモート緊急停止

---

## 📊 日次確認手順（1-2分/日）

### **方法1: ブラウザ確認（推奨）**

```bash
# URLを開く
http://localhost:3333/

# 確認項目:
1. Equity: $900K以上か？
   ✓ Yes → 問題なし
   ✗ No  → リモート停止を検討

2. Drawdown: -8%以内か？
   ✓ Yes → 問題なし
   ✗ No  → リモート停止を検討

3. Positions: 8-12銘柄程度か？
   ✓ Yes → 問題なし
   ✗ No  → 異常の可能性（要調査）
```

### **方法2: SSH確認（リモートから）**

```bash
# SSHでログイン
ssh user@server

# 最新のログ確認
tail -20 ~/stock_swing/logs/paper_demo_*.log

# Equity確認
curl -s http://localhost:3333/api/dashboard | jq '.summary.equity'

# Expected: 900000-1100000
```

---

## 🚨 緊急停止手順（問題発生時）

### **条件: 以下のいずれかに該当**

```
⚠️ Equity < $900K (-10%超の下落)
⚠️ Drawdown < -10%
⚠️ 異常な集中（1銘柄が20%超）
⚠️ システムエラーが頻発
```

### **手順1: リモートからKill Switch作成**

```bash
# SSHでサーバーにログイン
ssh user@server

# Manual Kill Switchファイルを作成
touch ~/stock_swing/data/kill_switch_manual.txt

# 確認
ls -l ~/stock_swing/data/kill_switch_manual.txt

# 次回のCron実行時（通常9:00前後）に自動停止
```

### **手順2: 即座に停止（緊急時）**

```bash
# Cronジョブを一時停止
crontab -e

# paper_demo実行行をコメントアウト
# 例: 0 9 * * * ... → # 0 9 * * * ...

# 保存して終了
:wq
```

### **手順3: 全ポジション手動決済（最終手段）**

```bash
# Alpacaウェブサイトにログイン
https://app.alpaca.markets/paper/dashboard

# Positions → Close All
```

---

## 🔄 再開手順（GW明け or 問題解決後）

### **Kill Switch解除**

```bash
# SSHでログイン
ssh user@server

# Kill Switchファイルを削除
rm ~/stock_swing/data/kill_switch_manual.txt

# 確認
ls ~/stock_swing/data/kill_switch_manual.txt
# Expected: "No such file or directory"
```

### **Cron再開（停止した場合）**

```bash
# Cronを再編集
crontab -e

# コメントアウトを解除
# 例: # 0 9 * * * ... → 0 9 * * * ...

# 保存
:wq

# 次回実行を確認
crontab -l | grep paper_demo
```

---

## 📅 GW期間の確認スケジュール

### **5/3（土）**
```
朝10:00: ブラウザで簡易確認
　→ Equity, Drawdown確認
　→ 問題なければ終了（所要時間: 1分）
```

### **5/4（日）**
```
夜20:00: ブラウザで簡易確認
　→ 同上
```

### **5/5（月）**
```
朝10:00: ブラウザで簡易確認
　→ 米国市場オープン日なので念のため確認
```

### **5/6（火）**
```
夜20:00: ブラウザで簡易確認
　→ 最終確認
```

### **5/7（水）**
```
朝09:00: GW明け初取引
　→ ログを詳細確認
　→ 問題なければ通常運用継続
```

---

## 🎯 想定シナリオと対応

### **シナリオ1: 正常稼働**

```
状態:
- Equity $980K-1,020K
- Drawdown -2% ~ +2%
- Positions 8-12銘柄

対応:
→ 何もしない
→ 毎日1分の確認のみ
```

### **シナリオ2: 小幅下落**

```
状態:
- Equity $920K-950K (-5% ~ -8%)
- Drawdown -5% ~ -8%

対応:
→ 監視継続
→ 確認頻度を1日2回に増やす
→ -10%到達でKill Switch検討
```

### **シナリオ3: 大幅下落**

```
状態:
- Equity < $900K (-10%超)
- Drawdown < -10%

対応:
→ リモートからKill Switch作成
→ 次回Cron実行時に自動停止
→ GW明けに詳細調査
```

### **シナリオ4: システムエラー**

```
状態:
- Cronが実行されていない
- Logファイルにエラー多数
- ブラウザでデータ表示されない

対応:
→ Cron一時停止
→ GW明けに詳細調査・修正
```

---

## 📝 実装済み機能

### **✅ Manual Kill Switch**

```python
# ファイル: paper_demo.py
# 実装箇所: main()関数の最初

if MANUAL_KILL_SWITCH_FILE.exists():
    print("🚨 MANUAL KILL SWITCH ACTIVATED")
    return 1  # 取引せず終了
```

**動作確認:**
```bash
# テスト
touch ~/stock_swing/data/kill_switch_manual.txt
cd ~/stock_swing && source venv/bin/activate
python src/stock_swing/cli/paper_demo.py --dry-run

# Expected: 🚨 MANUAL KILL SWITCH ACTIVATED

# 削除
rm ~/stock_swing/data/kill_switch_manual.txt
```

---

### **✅ Position Limit強制**

```python
# 既存実装確認済み

Stock: 8% max ($80K @ $1M)
ETF: 15% max ($150K @ $1M)

超過時: 自動スキップ + ログ記録
```

---

### **✅ RiskMonitorクラス**

```python
# ファイル: src/stock_swing/risk/risk_monitor.py
# 状態: 実装完了（paper_demo.pyへの統合は5/7以降）

機能:
- Drawdown計算
- Kill Switch (-12%)
- Warning Alert (-8%)
- Daily Loss Limit (-3%)
- State persistence
```

---

## ⚠️ 注意事項

### **1. Paper Trading環境**

```
✅ リアルマネーではない
✅ 2ヶ月中にリセット予定
→ リスクは限定的
```

### **2. GW中の監視は最低限**

```
✅ 1日1-2分の確認のみ
✅ 問題なければ何もしない
✅ リラックスして休暇を楽しむ
```

### **3. 5/7以降の本格実装**

```
GW明けに実装予定:
- Email通知システム
- 自動Kill Switch統合
- Health Check
- ログ強化
- etc.
```

---

## 📞 緊急連絡先（メモ用）

```
サーバー: _______________
SSH User: _______________
SSH Key:  _______________

Alpaca:
- Email: _______________
- URL: https://app.alpaca.markets/paper/dashboard
```

---

## ✅ チェックリスト

### **GW前（5/2完了）**

- [x] Manual Kill Switch実装
- [x] Position Limit確認
- [x] RiskMonitor unit test実行
- [x] 運用ガイド作成

### **GW中（5/3-5/6）**

- [ ] 5/3 朝: 簡易確認
- [ ] 5/4 夜: 簡易確認
- [ ] 5/5 朝: 簡易確認
- [ ] 5/6 夜: 簡易確認

### **GW明け（5/7）**

- [ ] 朝: 詳細ログ確認
- [ ] 本格実装再開準備

---

**作成日:** 2026年5月2日（金）  
**最終更新:** 2026年5月2日（金）  
**担当:** OpenClaw Assistant
