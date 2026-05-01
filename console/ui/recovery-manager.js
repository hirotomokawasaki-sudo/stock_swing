/**
 * Stock Swing Console - Recovery Manager
 * Handles automatic recovery from failures
 */

/**
 * リカバリーマネージャークラス
 */
class RecoveryManager {
  constructor() {
    this.recoveryStrategies = new Map();
    this.recoveryHistory = [];
    this.maxHistory = 50;
    this.cache = new Map();
    this.cacheMaxAge = 300000; // 5分
    
    // デフォルトのリカバリー設定
    this.defaultConfig = {
      maxRetries: 3,
      retryDelay: [1000, 2000, 4000], // 指数バックオフ
      fallbackToCache: true,
      notifyUser: true
    };
  }
  
  /**
   * リカバリー戦略を登録
   * @param {string} name - 戦略名
   * @param {Object} config - 設定
   */
  registerStrategy(name, config = {}) {
    this.recoveryStrategies.set(name, {
      ...this.defaultConfig,
      ...config
    });
    
    console.log(`✅ Recovery strategy registered: ${name}`);
  }
  
  /**
   * データをキャッシュ
   * @param {string} key - キーfunction
   * @param {*} data - データ
   */
  cacheData(key, data) {
    this.cache.set(key, {
      data: data,
      timestamp: Date.now()
    });
  }
  
  /**
   * キャッシュからデータを取得
   * @param {string} key - キー
   * @param {number} maxAge - 最大有効期限（ミリ秒）
   * @returns {*} データまたはnull
   */
  getCachedData(key, maxAge = this.cacheMaxAge) {
    const cached = this.cache.get(key);
    
    if (!cached) {
      return null;
    }
    
    const age = Date.now() - cached.timestamp;
    
    if (age > maxAge) {
      this.cache.delete(key);
      return null;
    }
    
    return cached.data;
  }
  
  /**
   * 操作をリトライ実行
   * @param {Function} operation - 実行する操作
   * @param {Object} options - オプション
   * @returns {Promise<*>} 結果
   */
  async retryOperation(operation, options = {}) {
    const config = {
      ...this.defaultConfig,
      ...options
    };
    
    let lastError = null;
    
    for (let attempt = 0; attempt <= config.maxRetries; attempt++) {
      try {
        const result = await operation();
        
        // 成功した場合
        if (attempt > 0) {
          console.log(`✅ Recovery successful after ${attempt} retries`);
          this.recordRecovery({
            type: 'retry_success',
            attempts: attempt,
            timestamp: Date.now()
          });
        }
        
        return result;
        
      } catch (error) {
        lastError = error;
        
        // 最後の試行でなければリトライ
        if (attempt < config.maxRetries) {
          const delay = config.retryDelay[Math.min(attempt, config.retryDelay.length - 1)];
          
          console.warn(`⚠️ Attempt ${attempt + 1} failed, retrying in ${delay}ms...`);
          
          if (config.notifyUser && typeof errorHandler !== 'undefined') {
            errorHandler.showInfo(`再試行中... (${attempt + 1}/${config.maxRetries + 1})`);
          }
          
          await this.delay(delay);
        }
      }
    }
    
    // すべての試行が失敗
    console.error(`❌ All retry attempts failed (${config.maxRetries + 1} attempts)`);
    
    this.recordRecovery({
      type: 'retry_failed',
      attempts: config.maxRetries + 1,
      error: lastError.message,
      timestamp: Date.now()
    });
    
    throw lastError;
  }
  
  /**
   * キャッシュフォールバック付きで操作を実行
   * @param {string} cacheKey - キャッシュキー
   * @param {Function} operation - 実行する操作
   * @param {Object} options - オプション
   * @returns {Promise<Object>} 結果
   */
  async executeWithFallback(cacheKey, operation, options = {}) {
    const config = {
      ...this.defaultConfig,
      ...options
    };
    
    try {
      // リトライ付きで実行
      const result = await this.retryOperation(operation, config);
      
      // 成功したらキャッシュ
      if (config.fallbackToCache) {
        this.cacheData(cacheKey, result);
      }
      
      return {
        success: true,
        data: result,
        source: 'live',
        timestamp: new Date()
      };
      
    } catch (error) {
      // すべて失敗した場合、キャッシュにフォールバック
      if (config.fallbackToCache) {
        const cached = this.getCachedData(cacheKey);
        
        if (cached) {
          console.warn(`⚠️ Using cached data (age: ${this.getCacheAge(cacheKey)}ms)`);
          
          if (config.notifyUser && typeof errorHandler !== 'undefined') {
            errorHandler.showWarning('最新データを取得できません。キャッシュを表示しています。');
          }
          
          this.recordRecovery({
            type: 'cache_fallback',
            cacheAge: this.getCacheAge(cacheKey),
            timestamp: Date.now()
          });
          
          return {
            success: true,
            data: cached,
            source: 'cache',
            cacheAge: this.getCacheAge(cacheKey),
            timestamp: new Date()
          };
        }
      }
      
      // キャッシュも利用できない場合
      if (config.notifyUser && typeof errorHandler !== 'undefined') {
        errorHandler.showError(`データを取得できませんでした: ${error.message}`);
      }
      
      return {
        success: false,
        error: error.message,
        timestamp: new Date()
      };
    }
  }
  
  /**
   * ヘルス問題を処理
   * @param {Object} healthResults - ヘルスチェック結果
   */
  handleHealthIssue(healthResults) {
    if (healthResults.status === 'error') {
      console.error('🚨 Critical health issue detected:', healthResults);
      
      // 深刻な問題の場合、自動リカバリーを試みる
      this.attemptAutoRecovery(healthResults);
      
    } else if (healthResults.status === 'warning') {
      console.warn('⚠️ Health warning detected:', healthResults);
      
      // 警告レベルの場合は監視のみ
      this.recordRecovery({
        type: 'health_warning',
        details: healthResults,
        timestamp: Date.now()
      });
    }
  }
  
  /**
   * 自動リカバリーを試みる
   * @param {Object} healthResults - ヘルスチェック結果
   */
  async attemptAutoRecovery(healthResults) {
    console.log('🔧 Attempting auto-recovery...');
    
    const recoveryActions = [];
    
    // エラー状態のチェックを特定
    Object.entries(healthResults.checks).forEach(([name, check]) => {
      if (check.status === 'error') {
        recoveryActions.push({ check: name, action: 'retry' });
      }
    });
    
    // リカバリーアクションを実行
    for (const action of recoveryActions) {
      try {
        await this.executeRecoveryAction(action);
        
        this.recordRecovery({
          type: 'auto_recovery_success',
          action: action,
          timestamp: Date.now()
        });
        
      } catch (error) {
        console.error(`❌ Auto-recovery failed for ${action.check}:`, error);
        
        this.recordRecovery({
          type: 'auto_recovery_failed',
          action: action,
          error: error.message,
          timestamp: Date.now()
        });
      }
    }
  }
  
  /**
   * リカバリーアクションを実行
   * @param {Object} action - アクション
   */
  async executeRecoveryAction(action) {
    console.log(`🔧 Executing recovery action: ${action.check}`);
    
    // ここで具体的なリカバリー処理を実装
    // 例: データの再取得、接続の再確立など
    
    await this.delay(1000);
  }
  
  /**
   * キャッシュの経過時間を取得
   * @param {string} key - キー
   * @returns {number} 経過時間（ミリ秒）
   */
  getCacheAge(key) {
    const cached = this.cache.get(key);
    if (!cached) return Infinity;
    return Date.now() - cached.timestamp;
  }
  
  /**
   * リカバリーを記録
   * @param {Object} recovery - リカバリー情報
   */
  recordRecovery(recovery) {
    this.recoveryHistory.push(recovery);
    
    if (this.recoveryHistory.length > this.maxHistory) {
      this.recoveryHistory.shift();
    }
  }
  
  /**
   * リカバリー統計を取得
   * @param {number} timeWindow - 時間窓（ミリ秒）
   * @returns {Object} 統計情報
   */
  getStats(timeWindow = 3600000) {
    const now = Date.now();
    const recent = this.recoveryHistory.filter(r => now - r.timestamp < timeWindow);
    
    const byType = {};
    recent.forEach(r => {
      byType[r.type] = (byType[r.type] || 0) + 1;
    });
    
    return {
      total: recent.length,
      byType: byType,
      successRate: this.calculateSuccessRate(recent),
      timeWindow: timeWindow,
      timestamp: new Date().toISOString()
    };
  }
  
  /**
   * 成功率を計算
   * @param {Array} recoveries - リカバリー履歴
   * @returns {number} 成功率（0-1）
   */
  calculateSuccessRate(recoveries) {
    if (recoveries.length === 0) return 1.0;
    
    const attempts = recoveries.filter(r =>
      r.type === 'retry_success' || r.type === 'retry_failed'
    );
    
    if (attempts.length === 0) return 1.0;
    
    const successes = recoveries.filter(r => r.type === 'retry_success').length;
    return successes / attempts.length;
  }
  
  /**
   * 遅延
   * @param {number} ms - ミリ秒
   * @returns {Promise}
   */
  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
  
  /**
   * キャッシュをクリア
   */
  clearCache() {
    this.cache.clear();
    console.log('🔧 Recovery cache cleared');
  }
  
  /**
   * 履歴をクリア
   */
  clearHistory() {
    this.recoveryHistory = [];
    console.log('🔧 Recovery history cleared');
  }
  
  /**
   * レポートを出力
   * @param {number} timeWindow - 時間窓（ミリ秒）
   */
  printReport(timeWindow = 3600000) {
    const stats = this.getStats(timeWindow);
    const windowHours = timeWindow / 3600000;
    
    console.log('\n🔧 ===== Recovery Report =====');
    console.log(`Time Window: Past ${windowHours}h`);
    console.log(`Generated: ${new Date().toLocaleString('ja-JP')}\n`);
    
    console.log(`Total Recoveries: ${stats.total}`);
    console.log(`Success Rate: ${(stats.successRate * 100).toFixed(2)}%\n`);
    
    if (Object.keys(stats.byType).length > 0) {
      console.log('By Type:');
      Object.entries(stats.byType)
        .sort((a, b) => b[1] - a[1])
        .forEach(([type, count]) => {
          console.log(`  ${type}: ${count}`);
        });
      console.log('');
    }
    
    console.log(`Cache Entries: ${this.cache.size}`);
    console.log('================================\n');
    
    return stats;
  }
}

// グローバルインスタンス
const recoveryManager = new RecoveryManager();

console.log('✅ recovery-manager.js loaded successfully');
