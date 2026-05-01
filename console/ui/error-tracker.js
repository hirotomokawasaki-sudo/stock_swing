/**
 * Stock Swing Console - Error Tracker
 * Tracks and analyzes errors
 */

/**
 * エラー追跡クラス
 */
class ErrorTracker {
  constructor() {
    this.errors = [];
    this.maxErrors = 200; // 最大200エラー保持
    this.enabled = true;
    
    // グローバルエラーハンドラーを設定
    this.setupGlobalHandlers();
  }
  
  /**
   * グローバルエラーハンドラーを設定
   */
  setupGlobalHandlers() {
    // JavaScript実行エラー
    window.addEventListener('error', (event) => {
      this.trackError({
        type: 'javascript',
        message: event.message,
        filename: event.filename,
        line: event.lineno,
        column: event.colno,
        stack: event.error?.stack,
        timestamp: Date.now()
      });
    });
    
    // Promise rejection
    window.addEventListener('unhandledrejection', (event) => {
      this.trackError({
        type: 'promise',
        message: event.reason?.message || String(event.reason),
        stack: event.reason?.stack,
        timestamp: Date.now()
      });
    });
  }
  
  /**
   * エラーを追跡
   * @param {Object} error - エラー情報
   */
  trackError(error) {
    if (!this.enabled) return;
    
    const enrichedError = {
      ...error,
      id: this.generateId(),
      timestamp: error.timestamp || Date.now(),
      url: window.location.href,
      userAgent: navigator.userAgent
    };
    
    this.errors.push(enrichedError);
    
    // エラー数制限
    if (this.errors.length > this.maxErrors) {
      this.errors.shift();
    }
    
    // コンソールに出力
    console.error('🚨 Error tracked:', enrichedError);
    
    return enrichedError;
  }
  
  /**
   * API エラーを追跡
   * @param {string} endpoint - APIエンドポイント
   * @param {number} status - HTTPステータスコード
   * @param {string} message - エラーメッセージ
   */
  trackAPIError(endpoint, status, message) {
    return this.trackError({
      type: 'api',
      endpoint: endpoint,
      status: status,
      message: message,
      timestamp: Date.now()
    });
  }
  
  /**
   * レンダリングエラーを追跡
   * @param {string} component - コンポーネント名
   * @param {string} message - エラーメッセージ
   */
  trackRenderError(component, message) {
    return this.trackError({
      type: 'render',
      component: component,
      message: message,
      timestamp: Date.now()
    });
  }
  
  /**
   * データエラーを追跡
   * @param {string} field - フィールド名
   * @param {string} message - エラーメッセージ
   */
  trackDataError(field, message) {
    return this.trackError({
      type: 'data',
      field: field,
      message: message,
      timestamp: Date.now()
    });
  }
  
  /**
   * エラーIDを生成
   * @returns {string} エラーID
   */
  generateId() {
    return `err_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
  
  /**
   * エラー統計を取得
   * @param {number} timeWindow - 時間窓（ミリ秒）
   * @returns {Object} 統計情報
   */
  getStats(timeWindow = 3600000) { // デフォルト1時間
    const now = Date.now();
    const recentErrors = this.errors.filter(e => now - e.timestamp < timeWindow);
    
    // タイプ別集計
    const byType = {};
    recentErrors.forEach(err => {
      const type = err.type || 'unknown';
      byType[type] = (byType[type] || 0) + 1;
    });
    
    // エンドポイント別集計（APIエラーのみ）
    const byEndpoint = {};
    recentErrors
      .filter(e => e.type === 'api')
      .forEach(err => {
        const endpoint = err.endpoint || 'unknown';
        byEndpoint[endpoint] = (byEndpoint[endpoint] || 0) + 1;
      });
    
    // 頻出エラーメッセージ
    const messageCount = {};
    recentErrors.forEach(err => {
      const msg = (err.message || 'unknown').substring(0, 100); // 最初の100文字
      messageCount[msg] = (messageCount[msg] || 0) + 1;
    });
    
    const topMessages = Object.entries(messageCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([msg, count]) => ({ message: msg, count }));
    
    return {
      total: recentErrors.length,
      byType: byType,
      byEndpoint: byEndpoint,
      topMessages: topMessages,
      errorRate: this.calculateErrorRate(timeWindow),
      timeWindow: timeWindow,
      timestamp: new Date().toISOString()
    };
  }
  
  /**
   * エラー率を計算（エラー数 / 総リクエスト数）
   * @param {number} timeWindow - 時間窓（ミリ秒）
   * @returns {number} エラー率（0-1）
   */
  calculateErrorRate(timeWindow = 3600000) {
    const now = Date.now();
    const recentErrors = this.errors.filter(e => now - e.timestamp < timeWindow);
    
    // performanceMonitorからAPI呼び出し数を取得
    if (typeof performanceMonitor !== 'undefined') {
      const apiMetrics = performanceMonitor.metrics.apiCalls || [];
      const recentCalls = apiMetrics.filter(m => now - m.timestamp < timeWindow);
      
      if (recentCalls.length === 0) {
        return 0;
      }
      
      const apiErrors = recentErrors.filter(e => e.type === 'api').length;
      return apiErrors / recentCalls.length;
    }
    
    return 0;
  }
  
  /**
   * エラーレポートを生成
   * @param {number} timeWindow - 時間窓（ミリ秒）
   * @returns {Object} レポート
   */
  generateReport(timeWindow = 3600000) {
    const stats = this.getStats(timeWindow);
    const windowHours = timeWindow / 3600000;
    
    return {
      summary: {
        total: stats.total,
        errorRate: (stats.errorRate * 100).toFixed(2) + '%',
        timeWindow: `${windowHours}h`
      },
      byType: stats.byType,
      byEndpoint: stats.byEndpoint,
      topMessages: stats.topMessages,
      timestamp: stats.timestamp
    };
  }
  
  /**
   * レポートをコンソールに出力
   * @param {number} timeWindow - 時間窓（ミリ秒）
   */
  printReport(timeWindow = 3600000) {
    const report = this.generateReport(timeWindow);
    const windowHours = timeWindow / 3600000;
    
    console.log('\n🚨 ===== Error Report =====');
    console.log(`Time Window: Past ${windowHours}h`);
    console.log(`Generated: ${new Date().toLocaleString('ja-JP')}\n`);
    
    console.log(`Total Errors: ${report.summary.total}`);
    console.log(`Error Rate: ${report.summary.errorRate}\n`);
    
    if (Object.keys(report.byType).length > 0) {
      console.log('By Type:');
      Object.entries(report.byType)
        .sort((a, b) => b[1] - a[1])
        .forEach(([type, count]) => {
          console.log(`  ${type}: ${count}`);
        });
      console.log('');
    }
    
    if (Object.keys(report.byEndpoint).length > 0) {
      console.log('By Endpoint (API errors):');
      Object.entries(report.byEndpoint)
        .sort((a, b) => b[1] - a[1])
        .forEach(([endpoint, count]) => {
          console.log(`  ${endpoint}: ${count}`);
        });
      console.log('');
    }
    
    if (report.topMessages.length > 0) {
      console.log('Top Error Messages:');
      report.topMessages.forEach((item, idx) => {
        console.log(`  ${idx + 1}. ${item.message} (${item.count}x)`);
      });
      console.log('');
    }
    
    console.log('================================\n');
    
    return report;
  }
  
  /**
   * エラーをクリア
   */
  clear() {
    this.errors = [];
    console.log('🚨 Error history cleared');
  }
  
  /**
   * 追跡を有効化/無効化
   * @param {boolean} enabled - 有効/無効
   */
  setEnabled(enabled) {
    this.enabled = enabled;
    console.log(`🚨 Error tracking ${enabled ? 'enabled' : 'disabled'}`);
  }
  
  /**
   * 最近のエラーを取得
   * @param {number} count - 取得数
   * @returns {Array} エラーリスト
   */
  getRecentErrors(count = 10) {
    return this.errors.slice(-count).reverse();
  }
}

// グローバルインスタンス
const errorTracker = new ErrorTracker();

console.log('✅ error-tracker.js loaded successfully');
