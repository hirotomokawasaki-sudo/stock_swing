/**
 * Stock Swing Console - Report Generator
 * Automatic report generation for performance and error metrics
 */

/**
 * レポート生成クラス
 */
class ReportGenerator {
  constructor() {
    this.reports = [];
    this.maxReports = 52; // 1年分（週次）
    this.reportInterval = null;
  }
  
  /**
   * 週次レポートを生成
   * @returns {Object} レポート
   */
  generateWeeklyReport() {
    const now = new Date();
    const weekStart = new Date(now);
    weekStart.setDate(now.getDate() - 7);
    
    const report = {
      id: this.generateReportId(),
      type: 'weekly',
      period: {
        start: weekStart.toISOString(),
        end: now.toISOString(),
        label: `${weekStart.toLocaleDateString('ja-JP')} - ${now.toLocaleDateString('ja-JP')}`
      },
      generated: now.toISOString(),
      sections: {}
    };
    
    // パフォーマンスセクション
    if (typeof performanceMonitor !== 'undefined') {
      const perfSummary = performanceMonitor.getSummary();
      
      report.sections.performance = {
        pageLoad: {
          count: perfSummary.pageLoad.count,
          avg: perfSummary.pageLoad.avg,
          p50: perfSummary.pageLoad.p50,
          p95: perfSummary.pageLoad.p95,
          status: this.getPerformanceStatus(perfSummary.pageLoad.avg, 3000)
        },
        apiCalls: {
          count: perfSummary.apiCalls.count,
          avg: perfSummary.apiCalls.avg,
          p50: perfSummary.apiCalls.p50,
          p95: perfSummary.apiCalls.p95,
          successRate: (perfSummary.apiSuccessRate * 100).toFixed(2) + '%',
          status: this.getPerformanceStatus(perfSummary.apiCalls.avg, 1000)
        },
        renders: {
          count: perfSummary.renders.count,
          avg: perfSummary.renders.avg,
          p50: perfSummary.renders.p50,
          p95: perfSummary.renders.p95,
          status: this.getPerformanceStatus(perfSummary.renders.avg, 500)
        }
      };
    }
    
    // エラーセクション
    if (typeof errorTracker !== 'undefined') {
      const errorStats = errorTracker.getStats(7 * 24 * 60 * 60 * 1000); // 7日分
      
      report.sections.errors = {
        total: errorStats.total,
        errorRate: (errorStats.errorRate * 100).toFixed(2) + '%',
        byType: errorStats.byType,
        topMessages: errorStats.topMessages.slice(0, 3),
        status: this.getErrorStatus(errorStats.errorRate)
      };
    }
    
    // ヘルスセクション
    if (typeof healthMonitor !== 'undefined') {
      const healthSummary = healthMonitor.getSummary();
      
      report.sections.health = {
        overall: healthSummary.overall,
        checks: Object.entries(healthSummary.checks).map(([name, check]) => ({
          name,
          status: check.status,
          lastCheck: check.lastCheck
        }))
      };
    }
    
    // リカバリーセクション
    if (typeof recoveryManager !== 'undefined') {
      const recoveryStats = recoveryManager.getStats(7 * 24 * 60 * 60 * 1000);
      
      report.sections.recovery = {
        total: recoveryStats.total,
        successRate: (recoveryStats.successRate * 100).toFixed(2) + '%',
        byType: recoveryStats.byType
      };
    }
    
    // 改善提案を生成
    report.recommendations = this.generateRecommendations(report);
    
    // 総合評価
    report.overallScore = this.calculateOverallScore(report);
    
    // レポートを保存
    this.saveReport(report);
    
    return report;
  }
  
  /**
   * パフォーマンスステータスを取得
   * @param {number} value - 値（ミリ秒）
   * @param {number} threshold - しきい値
   * @returns {string} ステータス
   */
  getPerformanceStatus(value, threshold) {
    if (value === 0) return 'no_data';
    if (value < threshold * 0.5) return 'excellent';
    if (value < threshold) return 'good';
    if (value < threshold * 1.5) return 'warning';
    return 'critical';
  }
  
  /**
   * エラーステータスを取得
   * @param {number} errorRate - エラー率（0-1）
   * @returns {string} ステータス
   */
  getErrorStatus(errorRate) {
    if (errorRate === 0) return 'excellent';
    if (errorRate < 0.01) return 'good';
    if (errorRate < 0.05) return 'warning';
    return 'critical';
  }
  
  /**
   * 改善提案を生成
   * @param {Object} report - レポート
   * @returns {Array} 提案リスト
   */
  generateRecommendations(report) {
    const recommendations = [];
    
    // パフォーマンス関連
    if (report.sections.performance) {
      const perf = report.sections.performance;
      
      if (perf.apiCalls.status === 'warning' || perf.apiCalls.status === 'critical') {
        recommendations.push({
          priority: 'high',
          category: 'performance',
          title: 'API レスポンス時間の改善',
          description: `API平均応答時間が${perf.apiCalls.avg}msです。キャッシュ戦略の見直しやクエリの最適化を検討してください。`,
          expectedImpact: '-30-50% response time'
        });
      }
      
      if (perf.renders.status === 'warning' || perf.renders.status === 'critical') {
        recommendations.push({
          priority: 'medium',
          category: 'performance',
          title: 'レンダリング最適化',
          description: `レンダリング時間が${perf.renders.avg}msです。仮想化やレイジーロードの導入を検討してください。`,
          expectedImpact: '-40-60% render time'
        });
      }
    }
    
    // エラー関連
    if (report.sections.errors && report.sections.errors.status !== 'excellent') {
      const errors = report.sections.errors;
      
      if (errors.total > 10) {
        recommendations.push({
          priority: 'high',
          category: 'reliability',
          title: 'エラー率の削減',
          description: `週次エラー数: ${errors.total}件。頻出エラーの根本原因を調査してください。`,
          expectedImpact: '-70-90% error count'
        });
      }
    }
    
    // ヘルス関連
    if (report.sections.health && report.sections.health.overall !== 'healthy') {
      recommendations.push({
        priority: 'high',
        category: 'reliability',
        title: 'ヘルス状態の改善',
        description: 'システムヘルスが正常ではありません。ヘルスレポートを確認してください。',
        expectedImpact: 'Improved stability'
      });
    }
    
    // 優先度順にソート
    recommendations.sort((a, b) => {
      const priorityOrder = { high: 0, medium: 1, low: 2 };
      return priorityOrder[a.priority] - priorityOrder[b.priority];
    });
    
    return recommendations;
  }
  
  /**
   * 総合スコアを計算（0-100）
   * @param {Object} report - レポート
   * @returns {number} スコア
   */
  calculateOverallScore(report) {
    let score = 100;
    
    // パフォーマンススコア（最大-30点）
    if (report.sections.performance) {
      const perf = report.sections.performance;
      
      if (perf.apiCalls.status === 'critical') score -= 15;
      else if (perf.apiCalls.status === 'warning') score -= 8;
      
      if (perf.renders.status === 'critical') score -= 10;
      else if (perf.renders.status === 'warning') score -= 5;
      
      if (perf.pageLoad.status === 'critical') score -= 5;
      else if (perf.pageLoad.status === 'warning') score -= 2;
    }
    
    // エラースコア（最大-40点）
    if (report.sections.errors) {
      const errors = report.sections.errors;
      
      if (errors.status === 'critical') score -= 40;
      else if (errors.status === 'warning') score -= 20;
      else if (errors.status === 'good') score -= 5;
    }
    
    // ヘルススコア（最大-20点）
    if (report.sections.health) {
      const health = report.sections.health;
      
      if (health.overall === 'error') score -= 20;
      else if (health.overall === 'warning') score -= 10;
    }
    
    // リカバリースコア（最大-10点）
    if (report.sections.recovery) {
      const recovery = report.sections.recovery;
      const successRate = parseFloat(recovery.successRate);
      
      if (successRate < 50) score -= 10;
      else if (successRate < 80) score -= 5;
    }
    
    return Math.max(0, score);
  }
  
  /**
   * レポートを保存
   * @param {Object} report - レポート
   */
  saveReport(report) {
    this.reports.push(report);
    
    // 最大数を超えたら古いものを削除
    if (this.reports.length > this.maxReports) {
      this.reports.shift();
    }
    
    // LocalStorageに保存
    try {
      localStorage.setItem('console_reports', JSON.stringify(this.reports));
      console.log(`✅ Report saved: ${report.id}`);
    } catch (error) {
      console.error('Failed to save report:', error);
    }
  }
  
  /**
   * 保存されたレポートを読み込み
   */
  loadReports() {
    try {
      const stored = localStorage.getItem('console_reports');
      if (stored) {
        this.reports = JSON.parse(stored);
        console.log(`✅ Loaded ${this.reports.length} reports`);
      }
    } catch (error) {
      console.error('Failed to load reports:', error);
      this.reports = [];
    }
  }
  
  /**
   * レポートIDを生成
   * @returns {string} レポートID
   */
  generateReportId() {
    return `report_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
  
  /**
   * レポートを取得
   * @param {number} count - 取得数
   * @returns {Array} レポートリスト
   */
  getReports(count = 10) {
    return this.reports.slice(-count).reverse();
  }
  
  /**
   * 最新のレポートを取得
   * @returns {Object|null} レポート
   */
  getLatestReport() {
    return this.reports.length > 0 ? this.reports[this.reports.length - 1] : null;
  }
  
  /**
   * レポートをHTML形式で出力
   * @param {Object} report - レポート
   * @returns {string} HTML
   */
  formatReportHTML(report) {
    const scoreColor = report.overallScore >= 80 ? '#10b981' : 
                       report.overallScore >= 60 ? '#f59e0b' : '#ef4444';
    
    let html = `
      <div class="report-card">
        <div class="report-header">
          <h2>📊 週次パフォーマンスレポート</h2>
          <div class="report-period">${report.period.label}</div>
          <div class="report-score" style="color: ${scoreColor}">
            総合スコア: ${report.overallScore}/100
          </div>
        </div>
    `;
    
    // パフォーマンスセクション
    if (report.sections.performance) {
      html += `
        <div class="report-section">
          <h3>⚡ パフォーマンス</h3>
          <div class="metrics-grid">
            <div class="metric-card">
              <div class="metric-label">API呼び出し</div>
              <div class="metric-value">${report.sections.performance.apiCalls.avg}ms</div>
              <div class="metric-detail">p95: ${report.sections.performance.apiCalls.p95}ms</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">レンダリング</div>
              <div class="metric-value">${report.sections.performance.renders.avg}ms</div>
              <div class="metric-detail">p95: ${report.sections.performance.renders.p95}ms</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">成功率</div>
              <div class="metric-value">${report.sections.performance.apiCalls.successRate}</div>
              <div class="metric-detail">${report.sections.performance.apiCalls.count} calls</div>
            </div>
          </div>
        </div>
      `;
    }
    
    // エラーセクション
    if (report.sections.errors) {
      html += `
        <div class="report-section">
          <h3>🚨 エラー</h3>
          <div class="metrics-grid">
            <div class="metric-card">
              <div class="metric-label">総エラー数</div>
              <div class="metric-value">${report.sections.errors.total}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">エラー率</div>
              <div class="metric-value">${report.sections.errors.errorRate}</div>
            </div>
          </div>
      `;
      
      if (report.sections.errors.topMessages.length > 0) {
        html += `<div class="top-errors"><strong>頻出エラー:</strong><ul>`;
        report.sections.errors.topMessages.forEach(item => {
          html += `<li>${item.message.substring(0, 80)}... (${item.count}件)</li>`;
        });
        html += `</ul></div>`;
      }
      
      html += `</div>`;
    }
    
    // 改善提案
    if (report.recommendations.length > 0) {
      html += `
        <div class="report-section">
          <h3>💡 改善提案</h3>
          <ul class="recommendations-list">
      `;
      
      report.recommendations.forEach(rec => {
        const priorityColor = rec.priority === 'high' ? '#ef4444' : 
                               rec.priority === 'medium' ? '#f59e0b' : '#6b7280';
        html += `
          <li>
            <span class="priority-badge" style="background: ${priorityColor}">${rec.priority}</span>
            <strong>${rec.title}</strong>
            <p>${rec.description}</p>
            <small>期待される効果: ${rec.expectedImpact}</small>
          </li>
        `;
      });
      
      html += `</ul></div>`;
    }
    
    html += `
        <div class="report-footer">
          <small>生成日時: ${new Date(report.generated).toLocaleString('ja-JP')}</small>
        </div>
      </div>
    `;
    
    return html;
  }
  
  /**
   * 自動レポート生成を開始（毎週月曜日9:00）
   */
  startAutoReporting() {
    // 毎日チェック（1日1回）
    this.reportInterval = setInterval(() => {
      const now = new Date();
      const dayOfWeek = now.getDay(); // 0=日曜日, 1=月曜日
      const hour = now.getHours();
      
      // 月曜日の9:00-10:00の間
      if (dayOfWeek === 1 && hour === 9) {
        console.log('🕒 Generating weekly report...');
        const report = this.generateWeeklyReport();
        
        // 通知
        if (typeof errorHandler !== 'undefined') {
          errorHandler.showSuccess('週次レポートが生成されました！');
        }
        
        console.log('📊 Weekly report generated:', report);
      }
    }, 3600000); // 1時間ごとにチェック
    
    console.log('✅ Auto-reporting started (Monday 9:00)');
  }
  
  /**
   * 自動レポート生成を停止
   */
  stopAutoReporting() {
    if (this.reportInterval) {
      clearInterval(this.reportInterval);
      this.reportInterval = null;
      console.log('⏸️  Auto-reporting stopped');
    }
  }
  
  /**
   * レポートをクリア
   */
  clearReports() {
    this.reports = [];
    localStorage.removeItem('console_reports');
    console.log('🗑️  Reports cleared');
  }
}

// グローバルインスタンス
const reportGenerator = new ReportGenerator();

// ページロード時に保存されたレポートを読み込み
reportGenerator.loadReports();

console.log('✅ report-generator.js loaded successfully');
