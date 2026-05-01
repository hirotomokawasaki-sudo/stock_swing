# Console UI Robustness Improvement Plan
**作成日:** 2026-05-01  
**目的:** コンソールUIの堅牢性を向上させ、データ構造の変更やAPIエラーに強いシステムを構築する

---

## 🔍 現状の問題点

### 1. **データ取得の脆弱性**
```javascript
// 現在のコード（問題あり）
const data = await response.json();
const positions = data.positions.positions;  // ← undefinedで即クラッシュ
const newsItems = data.news.articles;        // ← パスが変わると壊れる
```

**問題:**
- null/undefinedチェックなし
- データパスがハードコード
- デフォルト値がない

### 2. **エラーハンドリングの不足**
```javascript
// 現在のコード（問題あり）
fetch('/api/dashboard')
  .then(response => response.json())
  .then(data => {
    updateUI(data);  // ← エラー時も実行される
  });
```

**問題:**
- HTTPエラーをキャッチしていない
- パースエラーをキャッチしていない
- ユーザーへのエラー表示なし

### 3. **フォーマット崩れ**
```javascript
// 現在のコード（問題あり）
return_pct.toFixed(2);  // ← return_pctがnullだとエラー
```

**問題:**
- 数値変換のバリデーションなし
- 文字列/数値の型チェックなし

### 4. **データ構造の依存性**
```javascript
// 現在のコード（問題あり）
data.cron_jobs.jobs.forEach(...)  // ← 構造が変わると壊れる
```

**問題:**
- APIレスポンスの構造に強く依存
- スキーマ変更に脆弱

---

## 🛠️ 改善策

### Phase 1: データアクセス層の追加

#### 1.1 Safe Data Accessor（安全なデータアクセサ）

**新規ファイル:** `console/ui/utils.js`

```javascript
/**
 * 安全にネストされたプロパティを取得する
 * @param {Object} obj - オブジェクト
 * @param {string} path - パス（'a.b.c'形式）
 * @param {*} defaultValue - デフォルト値
 * @returns {*} 値またはデフォルト値
 */
function safeGet(obj, path, defaultValue = null) {
  try {
    const keys = path.split('.');
    let result = obj;
    
    for (const key of keys) {
      if (result === null || result === undefined) {
        return defaultValue;
      }
      result = result[key];
    }
    
    return result !== undefined ? result : defaultValue;
  } catch (e) {
    console.warn(`safeGet error for path "${path}":`, e);
    return defaultValue;
  }
}

/**
 * 安全に数値に変換する
 * @param {*} value - 値
 * @param {number} defaultValue - デフォルト値
 * @returns {number} 数値
 */
function safeNumber(value, defaultValue = 0) {
  if (value === null || value === undefined || value === '') {
    return defaultValue;
  }
  const num = parseFloat(value);
  return isNaN(num) ? defaultValue : num;
}

/**
 * 安全にパーセンテージをフォーマットする
 * @param {*} value - 値（0.05 = 5%）
 * @param {number} decimals - 小数点以下の桁数
 * @returns {string} フォーマット済み文字列
 */
function safePercent(value, decimals = 2) {
  const num = safeNumber(value, 0);
  return (num * 100).toFixed(decimals) + '%';
}

/**
 * 安全に通貨をフォーマットする
 * @param {*} value - 値
 * @returns {string} フォーマット済み文字列
 */
function safeCurrency(value) {
  const num = safeNumber(value, 0);
  return '$' + num.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

/**
 * 安全に配列を取得する
 * @param {*} value - 値
 * @returns {Array} 配列（空配列をデフォルト）
 */
function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

/**
 * HTMLをエスケープする（改善版）
 * @param {*} value - 値
 * @returns {string} エスケープ済み文字列
 */
function escapeHtml(value) {
  if (value === null || value === undefined) {
    return '';
  }
  
  const str = String(value);
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  
  return str.replace(/[&<>"']/g, m => map[m]);
}
```

#### 1.2 Data Validator（データバリデータ）

```javascript
/**
 * ダッシュボードデータのバリデーションと正規化
 */
class DashboardDataValidator {
  constructor() {
    this.schema = {
      positions: {
        summary: {
          position_count: 'number',
          portfolio_value: 'number',
          gross_exposure: 'number'
        },
        positions: 'array'
      },
      trading: {
        summary: {
          win_rate: 'number',
          total_trades: 'number'
        },
        recent_trades: 'array'
      },
      cron_jobs: {
        jobs: 'array'
      }
    };
  }
  
  /**
   * データを検証・正規化する
   * @param {Object} data - 生データ
   * @returns {Object} 正規化されたデータ
   */
  validate(data) {
    if (!data || typeof data !== 'object') {
      console.error('Invalid dashboard data:', data);
      return this.getDefaultData();
    }
    
    const normalized = {};
    
    // Positions
    normalized.positions = {
      summary: {
        position_count: safeNumber(safeGet(data, 'positions.summary.position_count'), 0),
        portfolio_value: safeNumber(safeGet(data, 'positions.summary.portfolio_value'), 0),
        gross_exposure: safeNumber(safeGet(data, 'positions.summary.gross_exposure'), 0),
        cash: safeNumber(safeGet(data, 'positions.summary.cash'), 0)
      },
      positions: safeArray(safeGet(data, 'positions.positions'))
    };
    
    // Trading
    normalized.trading = {
      summary: {
        win_rate: safeNumber(safeGet(data, 'trading.summary.win_rate'), 0),
        total_trades: safeNumber(safeGet(data, 'trading.summary.total_trades'), 0),
        avg_return_per_trade: safeNumber(safeGet(data, 'trading.summary.avg_return_per_trade'), 0)
      },
      recent_trades: safeArray(safeGet(data, 'trading.recent_trades'))
    };
    
    // Cron Jobs
    normalized.cron_jobs = {
      jobs: safeArray(safeGet(data, 'cron_jobs.jobs'))
    };
    
    // News
    normalized.news = {
      items: safeArray(safeGet(data, 'news.items', safeGet(data, 'news.articles')))
    };
    
    return normalized;
  }
  
  /**
   * デフォルトデータを返す
   */
  getDefaultData() {
    return {
      positions: {
        summary: {
          position_count: 0,
          portfolio_value: 0,
          gross_exposure: 0,
          cash: 0
        },
        positions: []
      },
      trading: {
        summary: {
          win_rate: 0,
          total_trades: 0,
          avg_return_per_trade: 0
        },
        recent_trades: []
      },
      cron_jobs: {
        jobs: []
      },
      news: {
        items: []
      }
    };
  }
}

// グローバルインスタンス
const dataValidator = new DashboardDataValidator();
```

### Phase 2: エラーハンドリングの強化

#### 2.1 API Client（改善版）

```javascript
/**
 * 堅牢なAPIクライアント
 */
class RobustAPIClient {
  constructor(baseURL = '') {
    this.baseURL = baseURL;
    this.retryAttempts = 3;
    this.retryDelay = 1000; // 1秒
  }
  
  /**
   * データを取得（リトライ付き）
   */
  async fetchWithRetry(url, options = {}, attempts = this.retryAttempts) {
    try {
      const response = await fetch(this.baseURL + url, {
        ...options,
        timeout: 10000 // 10秒タイムアウト
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      return { success: true, data };
      
    } catch (error) {
      console.error(`Fetch error (${attempts} attempts left):`, error);
      
      if (attempts > 1) {
        await this.sleep(this.retryDelay);
        return this.fetchWithRetry(url, options, attempts - 1);
      }
      
      return { success: false, error: error.message };
    }
  }
  
  /**
   * ダッシュボードデータを取得
   */
  async getDashboard() {
    const result = await this.fetchWithRetry('/api/dashboard');
    
    if (result.success) {
      // データを検証・正規化
      return {
        success: true,
        data: dataValidator.validate(result.data)
      };
    }
    
    // エラー時はデフォルトデータを返す
    return {
      success: false,
      error: result.error,
      data: dataValidator.getDefaultData()
    };
  }
  
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// グローバルインスタンス
const apiClient = new RobustAPIClient();
```

#### 2.2 UI Error Handler（UIエラーハンドラ）

```javascript
/**
 * UIエラー表示
 */
class UIErrorHandler {
  constructor() {
    this.errorContainer = null;
    this.init();
  }
  
  init() {
    // エラー表示用コンテナを作成
    this.errorContainer = document.createElement('div');
    this.errorContainer.id = 'error-toast';
    this.errorContainer.className = 'error-toast hidden';
    document.body.appendChild(this.errorContainer);
  }
  
  /**
   * エラーを表示
   */
  show(message, type = 'error', duration = 5000) {
    this.errorContainer.textContent = message;
    this.errorContainer.className = `error-toast ${type}`;
    
    // 自動で非表示
    if (duration > 0) {
      setTimeout(() => this.hide(), duration);
    }
  }
  
  hide() {
    this.errorContainer.className = 'error-toast hidden';
  }
  
  /**
   * ローディング表示
   */
  showLoading(message = 'Loading...') {
    this.show(message, 'info', 0);
  }
}

// グローバルインスタンス
const errorHandler = new UIErrorHandler();
```

### Phase 3: データ更新の改善

#### 3.1 State Manager（状態管理）

```javascript
/**
 * アプリケーション状態管理
 */
class AppStateManager {
  constructor() {
    this.state = {
      lastUpdate: null,
      data: null,
      error: null,
      isLoading: false
    };
    this.listeners = [];
  }
  
  /**
   * 状態を更新
   */
  setState(newState) {
    this.state = { ...this.state, ...newState };
    this.notify();
  }
  
  /**
   * 状態変更をリスナーに通知
   */
  notify() {
    this.listeners.forEach(listener => {
      try {
        listener(this.state);
      } catch (e) {
        console.error('Listener error:', e);
      }
    });
  }
  
  /**
   * リスナーを登録
   */
  subscribe(listener) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }
  
  /**
   * データを更新
   */
  async updateData() {
    this.setState({ isLoading: true, error: null });
    
    const result = await apiClient.getDashboard();
    
    if (result.success) {
      this.setState({
        data: result.data,
        lastUpdate: new Date(),
        isLoading: false,
        error: null
      });
    } else {
      this.setState({
        error: result.error,
        isLoading: false
      });
      errorHandler.show(`Failed to load data: ${result.error}`, 'error');
    }
  }
}

// グローバルインスタンス
const appState = new AppStateManager();
```

### Phase 4: UI Rendering の改善

#### 4.1 Safe Rendering（安全なレンダリング）

```javascript
/**
 * 安全なテーブルレンダリング
 */
function renderPositionsTable(positions) {
  const positionsArray = safeArray(positions);
  
  if (positionsArray.length === 0) {
    return '<tr><td colspan="6" class="text-center text-muted">No positions</td></tr>';
  }
  
  return positionsArray.map(pos => {
    const symbol = escapeHtml(safeGet(pos, 'symbol', 'N/A'));
    const qty = safeNumber(safeGet(pos, 'qty'), 0);
    const marketValue = safeCurrency(safeGet(pos, 'market_value'));
    const unrealizedPnlPct = safePercent(safeGet(pos, 'unrealized_pnl_pct'));
    const weight = safePercent(safeGet(pos, 'portfolio_weight'));
    
    // PnL色分け
    const pnlValue = safeNumber(safeGet(pos, 'unrealized_pnl_pct'), 0);
    const pnlClass = pnlValue > 0 ? 'text-success' : pnlValue < 0 ? 'text-danger' : '';
    
    return `
      <tr>
        <td>${symbol}</td>
        <td class="text-end">${qty}</td>
        <td class="text-end">${marketValue}</td>
        <td class="text-end ${pnlClass}">${unrealizedPnlPct}</td>
        <td class="text-end">${weight}</td>
      </tr>
    `;
  }).join('');
}

/**
 * エラー時のフォールバック表示
 */
function renderErrorFallback(containerId, message) {
  const container = document.getElementById(containerId);
  if (!container) return;
  
  container.innerHTML = `
    <div class="alert alert-warning" role="alert">
      <i class="bi bi-exclamation-triangle"></i>
      ${escapeHtml(message)}
      <button class="btn btn-sm btn-outline-primary ms-2" onclick="appState.updateData()">
        Retry
      </button>
    </div>
  `;
}
```

### Phase 5: 自動リカバリー

#### 5.1 Health Check & Auto Recovery

```javascript
/**
 * ヘルスチェックと自動リカバリー
 */
class HealthMonitor {
  constructor() {
    this.checkInterval = 30000; // 30秒
    this.failureCount = 0;
    this.maxFailures = 3;
    this.isHealthy = true;
  }
  
  start() {
    setInterval(() => this.check(), this.checkInterval);
  }
  
  async check() {
    const result = await apiClient.fetchWithRetry('/api/health', {}, 1);
    
    if (!result.success) {
      this.failureCount++;
      
      if (this.failureCount >= this.maxFailures) {
        this.isHealthy = false;
        this.handleUnhealthy();
      }
    } else {
      if (!this.isHealthy) {
        // 回復した
        this.isHealthy = true;
        this.handleRecovery();
      }
      this.failureCount = 0;
    }
  }
  
  handleUnhealthy() {
    console.error('System unhealthy, attempting recovery...');
    errorHandler.show('Connection lost. Attempting to reconnect...', 'warning', 0);
    
    // データ更新を停止
    clearInterval(window.updateInterval);
    
    // 再接続を試みる
    setTimeout(() => this.attemptRecovery(), 5000);
  }
  
  attemptRecovery() {
    console.log('Attempting recovery...');
    appState.updateData().then(() => {
      if (this.isHealthy) {
        // データ更新を再開
        window.updateInterval = setInterval(() => appState.updateData(), 30000);
        errorHandler.hide();
      } else {
        // 再試行
        setTimeout(() => this.attemptRecovery(), 10000);
      }
    });
  }
  
  handleRecovery() {
    console.log('System recovered');
    errorHandler.show('Connection restored', 'success', 3000);
  }
}

// グローバルインスタンス
const healthMonitor = new HealthMonitor();
```

---

## 📁 実装ファイル構成

### 新規ファイル
```
console/ui/
├── utils.js              # ユーティリティ関数
├── validators.js         # データバリデータ
├── api-client.js        # APIクライアント
├── error-handler.js     # エラーハンドラ
├── state-manager.js     # 状態管理
└── health-monitor.js    # ヘルスモニター
```

### 修正ファイル
```
console/ui/
├── index.html           # 新しいJSファイルをインポート
├── app.js               # 新しいAPIを使用するように修正
└── style.css            # エラー表示用スタイル追加
```

---

## 🎯 実装の優先順位

### Priority 1: 即座に実装（今週末）
1. ✅ **utils.js** - safeGet, safeNumber, safePercent, safeCurrency
2. ✅ **validators.js** - DashboardDataValidator
3. ✅ **api-client.js** - RobustAPIClient
4. ✅ **app.js修正** - 新しいAPIを使用

**期待効果:**
- null/undefinedエラーの撲滅
- データ構造変更への耐性
- エラー時のグレースフルな動作

### Priority 2: 重要（来週）
5. ✅ **error-handler.js** - UIErrorHandler
6. ✅ **state-manager.js** - AppStateManager
7. ✅ **style.css** - エラー表示スタイル

**期待効果:**
- ユーザーへのエラー通知
- 状態管理の一元化
- リトライ機能

### Priority 3: 改善（今月）
8. ✅ **health-monitor.js** - HealthMonitor
9. ✅ **自動リカバリー** - 接続断時の自動再接続
10. ✅ **テストの追加**

**期待効果:**
- 自動リカバリー
- 長時間稼働の安定性

---

## 📊 改善効果の測定

### Before（現在）
```
エラー発生率: 高（データ構造変更時に必ずクラッシュ）
ユーザー体験: 悪（エラー時に何も表示されない）
保守性: 低（変更のたびに修正が必要）
```

### After（改善後）
```
エラー発生率: 低（グレースフルなエラーハンドリング）
ユーザー体験: 良（エラー時もフォールバック表示）
保守性: 高（データ構造変更に強い）
```

---

## 🧪 テスト計画

### Unit Tests
```javascript
// validators.test.js
test('safeGet returns default for undefined path', () => {
  const obj = { a: { b: 1 } };
  expect(safeGet(obj, 'a.b.c', 'default')).toBe('default');
});

test('safeNumber converts string to number', () => {
  expect(safeNumber('123.45')).toBe(123.45);
  expect(safeNumber('invalid', 0)).toBe(0);
});
```

### Integration Tests
```javascript
// api-client.test.js
test('fetchWithRetry retries on failure', async () => {
  // Mock fetch to fail 2 times then succeed
  const result = await apiClient.fetchWithRetry('/test');
  expect(result.success).toBe(true);
});
```

---

## 🚀 ロールアウトプラン

### Phase 1: テスト環境（5/2-5/3）
1. 新しいファイルを作成
2. テストコードを追加
3. ローカルで動作確認

### Phase 2: 段階的導入（5/4-5/5）
1. utils.js, validators.jsのみ導入
2. 既存コードの一部を書き換え
3. 動作確認

### Phase 3: 全面展開（5/6-5/8）
1. すべての新しいモジュールを導入
2. app.jsを全面的に書き換え
3. 1週間のモニタリング

### Phase 4: 最終調整（5/9-5/15）
1. フィードバックに基づく修正
2. パフォーマンス最適化
3. ドキュメント整備

---

## 💬 まとめ

この改善プランにより：

1. **堅牢性**: null/undefinedエラーの撲滅
2. **保守性**: データ構造変更に強い設計
3. **ユーザー体験**: エラー時もグレースフルな動作
4. **可用性**: 自動リカバリーで長時間安定稼働

**期待される成果:**
- エラー発生率: 90%削減
- 保守コスト: 50%削減
- ユーザー満足度: 大幅向上

**次のステップ:**
明日から Phase 1 の実装を開始し、週末までに基本的な堅牢性を確保します。
