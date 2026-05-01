/**
 * Stock Swing Console - Data Validators
 * Validate and normalize dashboard data
 */

/**
 * ダッシュボードデータのバリデーションと正規化
 */
class DashboardDataValidator {
  constructor() {
    this.lastValidData = null;
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
    
    try {
      const normalized = {
        // Overview
        overview: this.validateOverview(data),
        
        // Positions
        positions: this.validatePositions(data),
        
        // Trading
        trading: this.validateTrading(data),
        
        // Cron Jobs
        cron_jobs: this.validateCronJobs(data),
        
        // News
        news: this.validateNews(data),
        
        // Logs
        logs: this.validateLogs(data),
        
        // Pipeline
        pipeline: this.validatePipeline(data),
        
        // Performance (Analysis tab)
        performance: this.validatePerformance(data),
        
        // System
        system: this.validateSystem(data)
      };
      
      // 検証成功時、最後の有効なデータとして保存
      this.lastValidData = normalized;
      
      return normalized;
      
    } catch (error) {
      console.error('Data validation error:', error);
      
      // エラー時は最後の有効なデータまたはデフォルトデータを返す
      return this.lastValidData || this.getDefaultData();
    }
  }
  
  /**
   * Overviewデータを検証
   */
  validateOverview(data) {
    return {
      account: {
        equity: safeNumber(safeGet(data, 'overview.account.equity'), 0),
        cash: safeNumber(safeGet(data, 'overview.account.cash'), 0),
        buying_power: safeNumber(safeGet(data, 'overview.account.buying_power'), 0),
        portfolio_value: safeNumber(safeGet(data, 'overview.account.portfolio_value'), 0),
        long_market_value: safeNumber(safeGet(data, 'overview.account.long_market_value'), 0)
      },
      deltas: {
        equity_vs_prev_snapshot: safeNumber(safeGet(data, 'overview.deltas.equity_vs_prev_snapshot'), 0),
        equity_vs_prev_day: safeNumber(safeGet(data, 'overview.deltas.equity_vs_prev_day'), 0),
        unrealized_pnl: safeNumber(safeGet(data, 'overview.deltas.unrealized_pnl'), 0)
      }
    };
  }
  
  /**
   * Positionsデータを検証
   */
  validatePositions(data) {
    return {
      summary: {
        position_count: safeNumber(safeGet(data, 'positions.summary.position_count'), 0),
        portfolio_value: safeNumber(safeGet(data, 'positions.summary.portfolio_value'), 0),
        gross_exposure: safeNumber(safeGet(data, 'positions.summary.gross_exposure'), 0),
        cash: safeNumber(safeGet(data, 'positions.summary.cash'), 0),
        long_count: safeNumber(safeGet(data, 'positions.summary.long_count'), 0),
        short_count: safeNumber(safeGet(data, 'positions.summary.short_count'), 0)
      },
      positions: safeArray(safeGet(data, 'positions.positions')).map(pos => ({
        symbol: escapeHtml(safeGet(pos, 'symbol', 'N/A')),
        qty: safeNumber(safeGet(pos, 'qty'), 0),
        market_value: safeNumber(safeGet(pos, 'market_value'), 0),
        avg_entry_price: safeNumber(safeGet(pos, 'avg_entry_price'), 0),
        current_price: safeNumber(safeGet(pos, 'current_price'), 0),
        unrealized_pnl: safeNumber(safeGet(pos, 'unrealized_pnl'), 0),
        unrealized_pnl_pct: safeNumber(safeGet(pos, 'unrealized_pnl_pct'), 0),
        portfolio_weight: safeNumber(safeGet(pos, 'portfolio_weight'), 0),
        holding_days: safeGet(pos, 'holding_days', null)
      }))
    };
  }
  
  /**
   * Tradingデータを検証
   */
  validateTrading(data) {
    return {
      summary: {
        win_rate: safeNumber(safeGet(data, 'trading.summary.win_rate'), 0),
        total_trades: safeNumber(safeGet(data, 'trading.summary.total_trades'), 0),
        closed_trades: safeNumber(safeGet(data, 'trading.summary.closed_trades'), 0),
        avg_return_per_trade: safeNumber(safeGet(data, 'trading.summary.avg_return_per_trade'), 0),
        cumulative_realized_pnl: safeNumber(safeGet(data, 'trading.summary.cumulative_realized_pnl'), 0),
        max_drawdown_pct: safeNumber(safeGet(data, 'trading.summary.max_drawdown_pct'), 0)
      },
      recent_trades: safeArray(safeGet(data, 'trading.recent_trades')).map(trade => ({
        symbol: escapeHtml(safeGet(trade, 'symbol', 'N/A')),
        side: escapeHtml(safeGet(trade, 'side', 'N/A')),
        qty: safeNumber(safeGet(trade, 'qty'), 0),
        entry_price: safeNumber(safeGet(trade, 'entry_price'), 0),
        exit_price: safeNumber(safeGet(trade, 'exit_price'), 0),
        entry_time: safeGet(trade, 'entry_time', null),
        exit_time: safeGet(trade, 'exit_time', null),
        realized_pnl: safeNumber(safeGet(trade, 'realized_pnl'), 0),
        return_pct: safeNumber(safeGet(trade, 'return_pct'), 0),
        status: escapeHtml(safeGet(trade, 'status', 'unknown'))
      })),
      daily_snapshots: safeArray(safeGet(data, 'trading.daily_snapshots'))
    };
  }
  
  /**
   * Cron Jobsデータを検証
   */
  validateCronJobs(data) {
    return {
      jobs: safeArray(safeGet(data, 'cron_jobs.jobs')).map(job => ({
        name: escapeHtml(safeGet(job, 'name', 'N/A')),
        enabled: Boolean(safeGet(job, 'enabled', true)),
        last_run: safeGet(job, 'last_run', null),
        next_run: safeGet(job, 'next_run', null),
        last_duration_ms: safeNumber(safeGet(job, 'last_duration_ms'), 0),
        lag_seconds: safeNumber(safeGet(job, 'lag_seconds'), 0),
        schedule_display: escapeHtml(safeGet(job, 'schedule_display', 'N/A'))
      }))
    };
  }
  
  /**
   * Newsデータを検証
   */
  validateNews(data) {
    // Try both 'items' and 'articles' paths
    const newsItems = safeGet(data, 'news.items') || safeGet(data, 'news.articles', []);
    
    return {
      items: safeArray(newsItems).map(item => ({
        title: escapeHtml(safeGet(item, 'title', 'No title')),
        summary: escapeHtml(safeGet(item, 'summary', '')),
        source: escapeHtml(safeGet(item, 'source', 'Unknown')),
        published_at: safeGet(item, 'published_at', null),
        url: safeGet(item, 'url', '#'),
        sentiment: escapeHtml(safeGet(item, 'sentiment', 'neutral')),
        symbols: safeArray(safeGet(item, 'symbols'))
      }))
    };
  }
  
  /**
   * Logsデータを検証
   */
  validateLogs(data) {
    return {
      lines: safeArray(safeGet(data, 'logs.lines')).map(line => ({
        timestamp: safeGet(line, 'timestamp', null),
        level: escapeHtml(safeGet(line, 'level', 'INFO')),
        message: escapeHtml(safeGet(line, 'message', '')),
        category: escapeHtml(safeGet(line, 'category', 'system'))
      })),
      stats: {
        total_lines: safeNumber(safeGet(data, 'logs.stats.total_lines'), 0),
        error_count: safeNumber(safeGet(data, 'logs.stats.error_count'), 0),
        warning_count: safeNumber(safeGet(data, 'logs.stats.warning_count'), 0)
      }
    };
  }
  
  /**
   * Pipelineデータを検証
   */
  validatePipeline(data) {
    return {
      funnel: {
        raw: safeNumber(safeGet(data, 'pipeline.funnel.raw'), 0),
        normalized: safeNumber(safeGet(data, 'pipeline.funnel.normalized'), 0),
        features: safeNumber(safeGet(data, 'pipeline.funnel.features'), 0),
        signals: safeNumber(safeGet(data, 'pipeline.funnel.signals'), 0),
        decisions: safeNumber(safeGet(data, 'pipeline.funnel.decisions'), 0),
        orders_submitted: safeNumber(safeGet(data, 'pipeline.funnel.orders_submitted'), 0)
      },
      by_strategy: safeArray(safeGet(data, 'pipeline.by_strategy'))
    };
  }
  
  /**
   * Performanceデータを検証
   */
  validatePerformance(data) {
    return {
      sharpe: {
        sharpe_ratio: safeNumber(safeGet(data, 'performance.sharpe.sharpe_ratio'), 0),
        annual_return_pct: safeNumber(safeGet(data, 'performance.sharpe.annual_return_pct'), 0),
        annual_volatility_pct: safeNumber(safeGet(data, 'performance.sharpe.annual_volatility_pct'), 0)
      },
      alpha: {
        alpha: safeNumber(safeGet(data, 'performance.alpha.alpha'), 0)
      },
      beta: {
        beta: safeNumber(safeGet(data, 'performance.beta.beta'), 0)
      }
    };
  }
  
  /**
   * Systemデータを検証
   */
  validateSystem(data) {
    return {
      status: escapeHtml(safeGet(data, 'system.status', 'unknown')),
      uptime: safeNumber(safeGet(data, 'system.uptime'), 0),
      cpu_percent: safeNumber(safeGet(data, 'system.cpu_percent'), 0),
      memory_percent: safeNumber(safeGet(data, 'system.memory_percent'), 0)
    };
  }
  
  /**
   * デフォルトデータを返す
   */
  getDefaultData() {
    return {
      overview: {
        account: {
          equity: 0,
          cash: 0,
          buying_power: 0,
          portfolio_value: 0,
          long_market_value: 0
        },
        deltas: {
          equity_vs_prev_snapshot: 0,
          equity_vs_prev_day: 0,
          unrealized_pnl: 0
        }
      },
      positions: {
        summary: {
          position_count: 0,
          portfolio_value: 0,
          gross_exposure: 0,
          cash: 0,
          long_count: 0,
          short_count: 0
        },
        positions: []
      },
      trading: {
        summary: {
          win_rate: 0,
          total_trades: 0,
          closed_trades: 0,
          avg_return_per_trade: 0,
          cumulative_realized_pnl: 0,
          max_drawdown_pct: 0
        },
        recent_trades: [],
        daily_snapshots: []
      },
      cron_jobs: {
        jobs: []
      },
      news: {
        items: []
      },
      logs: {
        lines: [],
        stats: {
          total_lines: 0,
          error_count: 0,
          warning_count: 0
        }
      },
      pipeline: {
        funnel: {
          raw: 0,
          normalized: 0,
          features: 0,
          signals: 0,
          decisions: 0,
          orders_submitted: 0
        },
        by_strategy: []
      },
      performance: {
        sharpe: {
          sharpe_ratio: 0,
          annual_return_pct: 0,
          annual_volatility_pct: 0
        },
        alpha: {
          alpha: 0
        },
        beta: {
          beta: 0
        }
      },
      system: {
        status: 'unknown',
        uptime: 0,
        cpu_percent: 0,
        memory_percent: 0
      }
    };
  }
}

// グローバルインスタンス
const dataValidator = new DashboardDataValidator();

console.log('✅ validators.js loaded successfully');
