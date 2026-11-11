/**
 * Stock Swing Console - Health Monitor
 * Monitors system health and triggers recovery
 */

/**
 * ヘルスモニタークラス
 */
class HealthMonitor {
  constructor() {
    this.checks = new Map();
    this.history = [];
    this.maxHistory = 100;
    this.monitoringInterval = null;
    this.enabled = false;
    
    // デフォルトのヘルスチェック設定
    this.defaultThresholds = {
      responseTime: 5000,  // 5秒以上で警告
      errorRate: 0.1,      // 10%以上で警告
      dataAge: 300000      // 5分以上古いと警告
    };
  }
  
  /**
   * ヘルスチェックを登録
   * @param {string} name - チェック名
   * @param {Function} checkFn - チェック関数
   * @param {Object} options - オプション
   */
  registerCheck(name, checkFn, options = {}) {
    this.checks.set(name, {
      name: name,
      checkFn: checkFn,
      interval: options.interval || 30000, // デフォルト30秒
      thresholds: { ...this.defaultThresholds, ...options.thresholds },
      lastCheck: null,
      lastResult: null
    });
    
    console.log(`✅ Health check registered: ${name}`);
  }
  
  /**
   * 単一のヘルスチェックを実行
   * @param {string} name - チェック名
   * @returns {Promise<Object>} チェック結果
   */
  async runCheck(name) {
    const check = this.checks.get(name);
    if (!check) {
      return {
        name: name,
        status: 'unknown',
        error: 'Check not found',
        timestamp: Date.now()
      };
    }
    
    const startTime = Date.now();
    
    try {
      const result = await check.checkFn();
      const duration = Date.now() - startTime;
      
      // しきい値チェック
      let status = 'healthy';
      const warnings = [];
      if (!result || typeof result !== 'object' || result.success !== true) {
        status = result?.success === false ? 'error' : 'unknown';
        warnings.push(result?.success === false ? 'API acquisition failed' : 'Acquisition result unconfirmed');
      } else if (result.source === 'cache') {
        status = 'warning';
        warnings.push('Saved cache fallback, not a fresh acquisition');
      }
      const validAge = typeof result?.dataAge === 'number' && Number.isFinite(result.dataAge) && result.dataAge >= 0;
      const validRate = typeof result?.errorRate === 'number' && Number.isFinite(result.errorRate) && result.errorRate >= 0 && result.errorRate <= 1;
      if ((!validAge || !validRate) && status !== 'error') {
        status = 'unknown';
        warnings.push('Data age/error-rate measurement unconfirmed');
      }
      
      if (duration > check.thresholds.responseTime) {
        if (status === 'healthy') status = 'warning';
        warnings.push(`Response time ${duration}ms exceeds threshold ${check.thresholds.responseTime}ms`);
      }
      
      if (validRate && result.errorRate > check.thresholds.errorRate) {
        if (status === 'healthy') status = 'warning';
        warnings.push(`Error rate ${(result.errorRate * 100).toFixed(2)}% exceeds threshold ${(check.thresholds.errorRate * 100).toFixed(2)}%`);
      }
      
      if (validAge && result.dataAge > check.thresholds.dataAge) {
        if (status === 'healthy') status = 'warning';
        warnings.push(`Data age ${Math.round(result.dataAge / 1000)}s exceeds threshold ${Math.round(check.thresholds.dataAge / 1000)}s`);
      }
      
      const checkResult = {
        name: name,
        status: status,
        duration: duration,
        warnings: warnings,
        data: result,
        timestamp: Date.now()
      };
      
      check.lastCheck = Date.now();
      check.lastResult = checkResult;
      
      this.addHistory(checkResult);
      
      return checkResult;
      
    } catch (error) {
      const checkResult = {
        name: name,
        status: 'error',
        error: error.message,
        stack: error.stack,
        timestamp: Date.now()
      };
      
      check.lastCheck = Date.now();
      check.lastResult = checkResult;
      
      this.addHistory(checkResult);
      
      return checkResult;
    }
  }
  
  /**
   * すべてのヘルスチェックを実行
   * @returns {Promise<Object>} 全チェック結果
   */
  async runAllChecks() {
    const results = {};
    
    for (const [name, check] of this.checks) {
      results[name] = await this.runCheck(name);
    }
    
    const overallStatus = this.calculateOverallStatus(results);
    
    return {
      status: overallStatus,
      checks: results,
      timestamp: new Date().toISOString()
    };
  }
  
  /**
   * 全体ステータスを計算
   * @param {Object} results - チェック結果
   * @returns {string} ステータス
   */
  calculateOverallStatus(results) {
    const statuses = Object.values(results).map(r => r.status);
    if (!statuses.length) return 'unknown';
    
    if (statuses.some(s => s === 'error')) {
      return 'error';
    }
    if (statuses.some(s => !['healthy', 'warning', 'error'].includes(s))) return 'unknown';
    if (statuses.some(s => s === 'warning')) {
      return 'warning';
    }
    if (statuses.every(s => s === 'healthy')) {
      return 'healthy';
    }
    return 'unknown';
  }
  
  /**
   * 履歴に追加
   * @param {Object} result - チェック結果
   */
  addHistory(result) {
    this.history.push(result);
    
    if (this.history.length > this.maxHistory) {
      this.history.shift();
    }
  }
  
  /**
   * モニタリングを開始
   * @param {number} interval - チェック間隔（ミリ秒）
   */
  startMonitoring(interval = 60000) {
    if (this.monitoringInterval) {
      console.warn('⚠️ Monitoring already running');
      return;
    }
    
    this.enabled = true;
    
    // 即座に1回実行
    this.runAllChecks().then(results => {
      console.log('🏥 Initial health check:', results);
    });
    
    // 定期実行
    const nextDelay = () => typeof interval === 'function' ? interval() : interval;
    const tick = async () => {
      if (!this.enabled) return;
      
      const results = await this.runAllChecks();
      
      // 問題がある場合は警告
      if (results.status === 'error' || results.status === 'warning') {
        console.warn(`⚠️ Health check ${results.status}:`, results);
        
        // リカバリーマネージャーが利用可能なら通知
        if (typeof recoveryManager !== 'undefined') {
          recoveryManager.handleHealthIssue(results);
        }
      }
      if (this.enabled) this.monitoringInterval = setTimeout(tick, nextDelay());
    };
    this.monitoringInterval = setTimeout(tick, nextDelay());
    
    console.log(`🏥 Health monitoring started (interval: ${interval}ms)`);
  }
  
  /**
   * モニタリングを停止
   */
  stopMonitoring() {
    if (this.monitoringInterval) {
      clearTimeout(this.monitoringInterval);
      this.monitoringInterval = null;
      this.enabled = false;
      console.log('🏥 Health monitoring stopped');
    }
  }
  
  /**
   * ステータスサマリーを取得
   * @returns {Object} サマリー
   */
  getSummary() {
    const summary = {
      overall: 'unknown',
      checks: {},
      timestamp: new Date().toISOString()
    };
    
    const statuses = [];
    
    for (const [name, check] of this.checks) {
      if (check.lastResult) {
        summary.checks[name] = {
          status: check.lastResult.status,
          lastCheck: new Date(check.lastCheck).toISOString(),
          duration: check.lastResult.duration,
          warnings: check.lastResult.warnings || []
        };
        statuses.push(check.lastResult.status);
      } else {
        summary.checks[name] = {
          status: 'never_run',
          lastCheck: null
        };
      }
    }
    
    summary.overall = this.calculateOverallStatus(
      Object.fromEntries(
        Array.from(this.checks.entries())
          .filter(([_, check]) => check.lastResult)
          .map(([name, check]) => [name, check.lastResult])
      )
    );
    
    return summary;
  }
  
  /**
   * レポートを出力
   */
  printReport() {
    const summary = this.getSummary();
    
    console.log('\n🏥 ===== Health Report =====');
    console.log(`Overall Status: ${summary.overall.toUpperCase()}`);
    console.log(`Generated: ${new Date().toLocaleString('ja-JP')}\n`);
    
    Object.entries(summary.checks).forEach(([name, check]) => {
      const statusIcon = {
        healthy: '✅',
        warning: '⚠️',
        error: '❌',
        never_run: '⏸️',
        unknown: '❓'
      }[check.status] || '❓';
      
      console.log(`${statusIcon} ${name}: ${check.status}`);
      
      if (check.duration) {
        console.log(`   Response: ${check.duration}ms`);
      }
      
      if (check.warnings && check.warnings.length > 0) {
        check.warnings.forEach(w => {
          console.log(`   ⚠️  ${w}`);
        });
      }
      
      console.log('');
    });
    
    console.log('================================\n');
    
    return summary;
  }
  
  /**
   * 履歴をクリア
   */
  clearHistory() {
    this.history = [];
    console.log('🏥 Health history cleared');
  }
}

// グローバルインスタンス
const healthMonitor = new HealthMonitor();

console.log('✅ health-monitor.js loaded successfully');
