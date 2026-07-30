/**
 * Stock Swing Console - Performance Monitor
 * Measures and tracks performance metrics
 */

/**
 * パフォーマンス測定クラス
 */
class PerformanceMonitor {
  constructor() {
    this.metrics = {
      pageLoad: [],
      apiCalls: [],
      renders: [],
      interactions: []
    };
    this.maxSamples = 100; // 最大100サンプル保持
    this.enabled = true;
  }
  
  /**
   * ページロード時間を測定
   */
  measurePageLoad() {
    if (!this.enabled || !window.performance) return;
    
    try {
      const perfData = window.performance.timing;
      const loadTime = perfData.loadEventEnd - perfData.navigationStart;
      const domReady = perfData.domContentLoadedEventEnd - perfData.navigationStart;
      const firstPaint = perfData.responseEnd - perfData.navigationStart;
      
      const metric = {
        timestamp: Date.now(),
        total: loadTime,
        domReady: domReady,
        firstPaint: firstPaint,
        dns: perfData.domainLookupEnd - perfData.domainLookupStart,
        tcp: perfData.connectEnd - perfData.connectStart,
        request: perfData.responseStart - perfData.requestStart,
        response: perfData.responseEnd - perfData.responseStart,
        domProcessing: perfData.domComplete - perfData.domLoading
      };
      
      this.addMetric('pageLoad', metric);
      console.log('📊 Page load metrics:', metric);
      
      return metric;
    } catch (error) {
      console.error('Failed to measure page load:', error);
      return null;
    }
  }
  
  /**
   * API呼び出しを測定
   * @param {string} endpoint - APIエンドポイント
   * @param {number} startTime - 開始時刻
   * @param {number} endTime - 終了時刻
   * @param {boolean} success - 成功/失敗
   */
  measureAPICall(endpoint, startTime, endTime, success = true) {
    if (!this.enabled) return;
    
    const duration = endTime - startTime;
    
    const metric = {
      timestamp: Date.now(),
      endpoint: endpoint,
      duration: duration,
      success: success
    };
    
    this.addMetric('apiCalls', metric);
    
    // 警告レベルのチェック
    if (duration > 2000) {
      console.warn(`⚠️ Slow API call: ${endpoint} took ${duration}ms`);
    }
    
    return metric;
  }
  
  /**
   * レンダリング時間を測定
   * @param {string} component - コンポーネント名
   * @param {number} startTime - 開始時刻
   * @param {number} endTime - 終了時刻
   */
  measureRender(component, startTime, endTime) {
    if (!this.enabled) return;
    
    const duration = endTime - startTime;
    
    const metric = {
      timestamp: Date.now(),
      component: component,
      duration: duration
    };
    
    this.addMetric('renders', metric);
    
    if (duration > 1000) {
      console.warn(`⚠️ Slow render: ${component} took ${duration}ms`);
    }
    
    return metric;
  }
  
  /**
   * ユーザー操作のレイテンシを測定
   * @param {string} action - 操作名
   * @param {number} startTime - 開始時刻
   * @param {number} endTime - 終了時刻
   */
  measureInteraction(action, startTime, endTime) {
    if (!this.enabled) return;
    
    const duration = endTime - startTime;
    
    const metric = {
      timestamp: Date.now(),
      action: action,
      duration: duration
    };
    
    this.addMetric('interactions', metric);
    
    if (duration > 500) {
      console.warn(`⚠️ Slow interaction: ${action} took ${duration}ms`);
    }
    
    return metric;
  }
  
  /**
   * メトリクスを追加
   * @param {string} category - カテゴリ
   * @param {Object} metric - メトリクスデータ
   */
  addMetric(category, metric) {
    if (!this.metrics[category]) {
      this.metrics[category] = [];
    }
    
    this.metrics[category].push(metric);
    
    // サンプル数制限
    if (this.metrics[category].length > this.maxSamples) {
      this.metrics[category].shift();
    }
  }
  
  /**
   * 統計情報を取得
   * @param {string} category - カテゴリ
   * @returns {Object} 統計情報
   */
  getStats(category) {
    const metrics = this.metrics[category] || [];
    
    if (metrics.length === 0) {
      return {
        count: 0,
        min: 0,
        max: 0,
        avg: 0,
        p50: 0,
        p95: 0,
        p99: 0
      };
    }
    
    // duration値を抽出（カテゴリによって異なるフィールド名に対応）
    const values = metrics.map(m => {
      if (category === 'pageLoad') return m.total;
      return m.duration;
    }).filter(v => v != null && !isNaN(v));
    
    if (values.length === 0) {
      return {
        count: metrics.length,
        min: 0,
        max: 0,
        avg: 0,
        p50: 0,
        p95: 0,
        p99: 0
      };
    }
    
    const sorted = values.slice().sort((a, b) => a - b);
    
    return {
      count: values.length,
      min: Math.round(sorted[0]),
      max: Math.round(sorted[sorted.length - 1]),
      avg: Math.round(values.reduce((a, b) => a + b, 0) / values.length),
      p50: Math.round(sorted[Math.floor(sorted.length * 0.5)]),
      p95: Math.round(sorted[Math.floor(sorted.length * 0.95)]),
      p99: Math.round(sorted[Math.floor(sorted.length * 0.99)])
    };
  }
  
  /**
   * API成功率を取得
   * @returns {number} 成功率（0-1）
   */
  getAPISuccessRate() {
    const apiCalls = this.metrics.apiCalls || [];
    
    if (apiCalls.length === 0) {
      return 1.0;
    }
    
    const successCount = apiCalls.filter(c => c.success).length;
    return successCount / apiCalls.length;
  }
  
  /**
   * サマリーレポートを生成
   * @returns {Object} サマリー
   */
  getSummary() {
    return {
      pageLoad: this.getStats('pageLoad'),
      apiCalls: this.getStats('apiCalls'),
      renders: this.getStats('renders'),
      interactions: this.getStats('interactions'),
      apiSuccessRate: this.getAPISuccessRate(),
      timestamp: new Date().toISOString()
    };
  }
  
  /**
   * レポートをコンソールに出力
   */
  printReport() {
    const summary = this.getSummary();
    
    console.log('\n📊 ===== Performance Report =====');
    console.log(`Generated: ${new Date().toLocaleString('ja-JP')}\n`);
    
    if (summary.pageLoad.count > 0) {
      console.log('Page Load:');
      console.log(`  Count: ${summary.pageLoad.count}`);
      console.log(`  Avg: ${summary.pageLoad.avg}ms`);
      console.log(`  p50: ${summary.pageLoad.p50}ms`);
      console.log(`  p95: ${summary.pageLoad.p95}ms`);
      console.log('');
    }
    
    if (summary.apiCalls.count > 0) {
      console.log('API Calls:');
      console.log(`  Count: ${summary.apiCalls.count}`);
      console.log(`  Success Rate: ${(summary.apiSuccessRate * 100).toFixed(2)}%`);
      console.log(`  Avg: ${summary.apiCalls.avg}ms`);
      console.log(`  p50: ${summary.apiCalls.p50}ms`);
      console.log(`  p95: ${summary.apiCalls.p95}ms`);
      console.log('');
    }
    
    if (summary.renders.count > 0) {
      console.log('Renders:');
      console.log(`  Count: ${summary.renders.count}`);
      console.log(`  Avg: ${summary.renders.avg}ms`);
      console.log(`  p50: ${summary.renders.p50}ms`);
      console.log(`  p95: ${summary.renders.p95}ms`);
      console.log('');
    }
    
    if (summary.interactions.count > 0) {
      console.log('User Interactions:');
      console.log(`  Count: ${summary.interactions.count}`);
      console.log(`  Avg: ${summary.interactions.avg}ms`);
      console.log(`  p50: ${summary.interactions.p50}ms`);
      console.log(`  p95: ${summary.interactions.p95}ms`);
      console.log('');
    }
    
    console.log('================================\n');
    
    return summary;
  }
  
  /**
   * メトリクスをクリア
   */
  clear() {
    this.metrics = {
      pageLoad: [],
      apiCalls: [],
      renders: [],
      interactions: []
    };
    console.log('📊 Performance metrics cleared');
  }
  
  /**
   * 測定を有効化/無効化
   * @param {boolean} enabled - 有効/無効
   */
  setEnabled(enabled) {
    this.enabled = enabled;
    console.log(`📊 Performance monitoring ${enabled ? 'enabled' : 'disabled'}`);
  }
}

// グローバルインスタンス
const performanceMonitor = new PerformanceMonitor();

// ページロード完了時に自動測定
if (document.readyState === 'complete') {
  performanceMonitor.measurePageLoad();
} else {
  window.addEventListener('load', () => {
    performanceMonitor.measurePageLoad();
  });
}

console.log('✅ performance-monitor.js loaded successfully');
