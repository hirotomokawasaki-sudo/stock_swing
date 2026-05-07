# T22 cautious regime 向け具体改善案（ARM / DELL / CIEN）

## 背景
本日の集計では、BUY-origin closed trades のうち `stop_loss` 偏重は signal / confidence の低さでは十分に説明できなかった。
特に `cautious` regime で以下の組み合わせが悪化している。

- ARM × cautious
- DELL × cautious
- CIEN × cautious

### 観測要点
- `neutral` regime の stop_loss: 22件, avg_signal 0.947, avg_confidence 0.805, avg_pnl $395.78, Win率 50.0%
- `cautious` regime の stop_loss: 17件, avg_signal 0.900, avg_confidence 0.765, avg_pnl -$1.30, Win率 29.4%
- 特に
  - `ARM × cautious`: 3件, avg_pnl -$1,073.06, Win率 0%
  - `DELL × cautious`: 3件, avg_pnl -$259.61, Win率 0%
  - `CIEN × cautious`: 5件, avg_pnl -$45.03, Win率 40%

## 判断
`cautious` regime では、ARM / DELL / CIEN を通常ルールで通すのは期待値が悪い可能性が高い。
したがって、まずは **entry を厳格化** し、それでも通したポジションに対して **exit を早める** のが順当。

---

## 改善案（優先順）

### Priority 1: cautious regime の symbol別 entry gate
#### 目的
悪化しやすい symbol を `cautious` 中だけ絞る。

#### 具体案
- ARM
  - `market_regime == "cautious"` のときは **新規 entry を原則禁止**
  - 例外を作るなら `signal_strength == 1.0` かつ `momentum >= 0.30` のときのみ許可
- DELL
  - `market_regime == "cautious"` のときは **新規 entry を原則禁止**
  - 例外を作るなら `signal_strength == 1.0` かつ `momentum >= 0.20` のときのみ許可
- CIEN
  - `market_regime == "cautious"` のときは完全禁止ではなく **閾値引き上げ**
  - `min_signal_strength >= 0.95`
  - `confidence >= 0.80`
  - `momentum >= 0.15`

#### ねらい
- ARM / DELL は stop_loss 偏重が強いのでまず遮断
- CIEN は cautious でも一部残す余地あり

---

### Priority 2: cautious regime の symbol別 size reduction
#### 目的
禁止しきらない場合でも損失インパクトを抑える。

#### 具体案
`market_regime == "cautious"` かつ `symbol in {ARM, DELL, CIEN}` のとき:
- position size multiplier を **0.5x**
- symbol position limit も通常の **50%** に縮小

#### 実装イメージ
- sizing 前に symbol / regime 条件で risk budget を半減
- もしくは `final_shares = floor(final_shares * 0.5)`

#### ねらい
- 完全 deny せずに観測継続しつつ損失を縮小

---

### Priority 3: cautious regime entry 向け早期 exit ルール
#### 目的
通した cautious entry を長く持ちすぎない。

#### 具体案
`market_regime == "cautious"` で入った ARM / DELL / CIEN に限定して:
- 初期 stop を **-7% → -5%** に厳格化
- trailing activation を **+5% → +3%** に前倒し
- trailing stop を **3% → 2.5%** に厳格化
- `hold_days >= 3` で含み益が小さい場合は time exit を許可
  - 条件例: `hold_days >= 3 and return_pct < 0.02`

#### ねらい
- cautious でのダラつく保有を防ぐ
- 小さく取って逃げる方向に寄せる

---

## 実装方針のおすすめ
### Phase A（最小変更）
1. ARM / DELL の cautious entry を deny
2. CIEN の cautious entry だけ閾値引き上げ
3. 1週間観測

### Phase B（必要時のみ）
4. まだ cautious で stop_loss が残るなら size 0.5x を追加
5. さらに悪ければ cautious-origin position 専用 early exit を追加

### 理由
- まず entry 側で抑える方が構造が単純
- exit だけで救おうとするとルールが複雑化しやすい
- 影響範囲を ARM / DELL / CIEN に限定すれば副作用を観測しやすい

---

## 実装候補箇所
- `src/stock_swing/strategy_engine/breakout_momentum_strategy.py`
  - symbol / regime 条件による gate 追加
- `src/stock_swing/cli/paper_demo.py`
  - regime 情報を使った symbol別 gate / size multiplier の注入
- `src/stock_swing/strategy_engine/simple_exit_v2_strategy.py`
  - cautious-origin position 向けの早期 exit 条件追加

---

## 次の実装優先順位
1. cautious regime での ARM / DELL deny
2. cautious regime での CIEN threshold 強化
3. 再観測
4. 必要なら size 0.5x
5. 必要なら cautious-origin 専用 early exit
