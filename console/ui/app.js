// Stock Swing Console Frontend
// Version: 2026-05-12-0938 (archive history view)
console.log('📊 Stock Swing Console v2026-05-12-0938 loaded');

// Format helpers (safe + compatible with original implementation)
const fmt = {
    usd: (v) => {
        if (v == null || v === undefined) return '—';
        const num = safeNumber(v, 0);
        return `$${num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    },
    pct: (v) => {
        if (v == null || v === undefined) return '—';
        const num = safeNumber(v, 0);
        return `${(num * 100).toFixed(2)}%`;
    },
    pctSigned: (v) => {
        if (v == null || v === undefined) return '—';
        const num = safeNumber(v, 0);
        return `${num >= 0 ? '+' : ''}${(num * 100).toFixed(2)}%`;
    },
    usdSigned: (v) => {
        if (v == null || v === undefined) return '—';
        const num = safeNumber(v, 0);
        return `${num >= 0 ? '+$' : '-$'}${Math.abs(num).toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    },
    dt: (iso) => iso ? new Date(iso).toLocaleString('ja-JP') : '—',
    badge: (label, cls) => `<span class="badge badge-${cls}">${label}</span>`,
};

class Console {
    constructor() {
        this.currentTab = 'overview';
        this.currentPeriod = localStorage.getItem('dashboardPeriod') || 'month';
        this._equityChartPeriod = localStorage.getItem('equityChartPeriod') || 'month';
        this._weeklyChartPeriod = localStorage.getItem('weeklyChartPeriod') || 'month';
        this.data = null;
        this.selectedNewsId = null;
        this.newsFilterUsed = localStorage.getItem('newsFilterUsed') === 'true';
        this.newsFilterTrackedOnly = localStorage.getItem('newsFilterTrackedOnly') !== 'false';
        this.newsFilterSentiment = localStorage.getItem('newsFilterSentiment') || 'all';
        this.newsFilterImpact = localStorage.getItem('newsFilterImpact') || 'all';
        this.newsFilterSymbol = localStorage.getItem('newsFilterSymbol') || '';
        this.newsSort = localStorage.getItem('newsSort') || 'published_at';
        this.init();
    }

    async init() {
        this.setupTabs();
        await this.loadData();
        this.render();
        this.startAutoRefresh();
    }

    setupTabs() {
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                console.log(`Tab clicked: ${e.target.dataset.tab}`);
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                e.target.classList.add('active');
                this.currentTab = e.target.dataset.tab;
                this.render();
            });
        });
    }

    async loadData() {
        const url = `/api/dashboard?period=${encodeURIComponent(this.currentPeriod)}`;
        const { data: jsonData, stale, error } = await _stableFetch(url);

        if (jsonData) {
            // Normalize first (before validation)
            this.normalizeData(jsonData);
            this.data = jsonData;
        } else if (!this.data) {
            // First load, no cache — show error state
            this.data = { error: error || 'Failed to load data' };
        }
        // else: keep previous data intact (stale, but visible)

        this.isStale = stale;
        if (stale && error) {
            console.warn(`[loadData] stale data: ${error}`);
        }
        this.updateStatusBar();
    }

    // Normalize API payload so UI rendering code can rely on consistent keys
    normalizeData(data) {
        if (!data) return;
        // charts: convert ts -> date for compatibility
        try {
            if (data.charts && data.charts.overview) {
                const cov = data.charts.overview;
                Object.keys(cov).forEach(k => {
                    if (Array.isArray(cov[k])) {
                        cov[k].forEach(item => {
                            if (item.ts && !item.date) item.date = item.ts;
                            // ensure value key exists for signals_orders entries
                            if (k === 'signals_orders') {
                                if (item.signals != null) item.signals_value = item.signals;
                                if (item.orders != null) item.orders_value = item.orders;
                            }
                        });
                    }
                });
            }
        } catch (e) { console.warn('normalizeData charts error', e); }

        // pipeline: map funnel -> top-level counts
        try {
            if (data.pipeline && data.pipeline.funnel) {
                const f = data.pipeline.funnel;
                data.pipeline.total_signals = f.signals || f.total_signals || 0;
                data.pipeline.total_orders = f.orders_submitted || f.orders || 0;
                data.pipeline.total_targets = f.positions_opened || 0;
                data.pipeline.total_confirmed = f.orders_filled || 0;
                data.pipeline.total_filled = f.orders_filled || 0;
            }
        } catch (e) { console.warn('normalizeData pipeline error', e); }

        // positions: ensure summary exists at data.positions.summary
        try {
            if (data.overview && data.overview.positions_summary && !data.positions) {
                data.positions = data.positions || {};
                data.positions.summary = data.overview.positions_summary;
            }
        } catch (e) { console.warn('normalizeData positions error', e); }
    }

    updateStatusBar() {
        if (!this.data) return;
        const systemStatus = document.getElementById('system-status');
        const lastUpdate = document.getElementById('last-update');
        const staleBadge = document.getElementById('stale-badge');
        if (this.data.system) {
            const status = this.data.system.status || 'unknown';
            const mode = this.data.system.runtime_mode || '?';
            systemStatus.innerHTML = `${fmt.badge(status.toUpperCase(), status)} <span style="color:#9ca3af;font-size:13px">モード: ${mode}</span>`;
        }
        if (this.data.time) {
            lastUpdate.textContent = `更新: ${fmt.dt(this.data.time)}`;
        }
        // Stale badge — 非ブロッキング表示
        if (staleBadge) {
            if (this.isStale) {
                staleBadge.style.display = 'inline-flex';
            } else {
                staleBadge.style.display = 'none';
            }
        }
    }

    render() {
        const startTime = Date.now();
        const content = document.getElementById('content');
        if (!this.data) { content.innerHTML = '<p class="muted">読み込み中...</p>'; return; }
        if (this.data.error) { content.innerHTML = `<div class="card"><p class="danger">エラー: ${this.data.error}</p></div>`; return; }
        
        try {
            switch (this.currentTab) {
                case 'overview':   content.innerHTML = this.renderOverview(); this.initOverviewCharts(); break;
                case 'weekly':     content.innerHTML = this.renderWeekly(); this.initWeeklyCharts(); break;
                case 'analysis':   content.innerHTML = this.renderAnalysis(); this.initAnalysisCharts(); break;
                case 'charts':     content.innerHTML = this.renderCharts(); this.initAllCharts(); break;
                case 'trading':    content.innerHTML = this.renderTrading(); break;
                case 'positions':  content.innerHTML = this.renderPositions(); break;
                case 'archives':   content.innerHTML = this.renderArchives(); break;
                case 'news':       content.innerHTML = this.renderNews(); break;
                case 'cron':       content.innerHTML = this.renderCronJobs(); break;
                case 'data':       content.innerHTML = this.renderDataStatus(); break;
                case 'logs':       content.innerHTML = this.renderLogs(); break;
                case 'metrics':    content.innerHTML = this.renderMetrics(); break;
            }
            this.setupPeriodSelectors();
            
            // Phase 3: パフォーマンス測定
            const endTime = Date.now();
            if (typeof performanceMonitor !== 'undefined') {
                performanceMonitor.measureRender(this.currentTab, startTime, endTime);
            }
            
        } catch (error) {
            // Phase 3: レンダリングエラー追跡
            console.error(`Render error in ${this.currentTab}:`, error);
            
            if (typeof errorTracker !== 'undefined') {
                errorTracker.trackRenderError(this.currentTab, error.message);
            }
            
            content.innerHTML = `
                <div class="card">
                    <h3>⚠️ レンダリングエラー</h3>
                    <p>タブの表示中にエラーが発生しました。</p>
                    <p class="danger">${error.message}</p>
                    <button onclick="location.reload()">ページを再読み込み</button>
                </div>
            `;
        }
    }

    renderMiniBarsWithDates(data, key, type) {
        if (!data || data.length === 0) return '<p class="muted">データなし</p>';
        // データを正規化: 最大値を100%として相対的な高さを計算
        const values = data.map(item => Math.abs(item[key] || 0));
        const maxValue = Math.max(...values, 1); // 0除算を防ぐため最小値1
        const normalizedData = data.map(item => {
            const value = Math.abs(item[key] || 0);
            const height = (value / maxValue) * 100;
            return { ...item, normalizedHeight: Math.max(height, 2) }; // 最小2%で視認性確保
        });
        return `
        <div class="mini-chart">
            <div class="mini-bars">
                ${normalizedData.map(item => `<div class="mini-bar" style="height:${item.normalizedHeight}%"></div>`).join('')}
            </div>
            <div class="mini-labels">
                <span>${fmt.dt(data[0]?.date)}</span>
                <span>${fmt.dt(data[data.length - 1]?.date)}</span>
            </div>
        </div>`;
    }

    renderOverview() {
        return `
        ${this.renderAlerts()}
        ${this.renderOverviewKpis()}
        ${this.renderOverviewCharts()}
        ${this.renderOverviewDiagnostics()}`;
    }

    renderOverviewCharts() {
        const charts = this.data?.charts?.overview || {};
        return `
        <div class="grid" style="margin-bottom: 16px;">
            <div class="card" style="grid-column: 1 / 3;">
                <h3>💰 Equity推移</h3>
                <canvas id="overviewEquityChart" height="60"></canvas>
            </div>
            <div class="card" style="grid-column: 3 / -1;">
                <h3>📉 Drawdown推移</h3>
                <canvas id="overviewDrawdownChart" height="60"></canvas>
            </div>
        </div>
        <div class="grid" style="margin-bottom: 16px;">
            <div class="card" style="grid-column: 1 / 3;">
                <h3>📊 Open Positions推移</h3>
                <canvas id="overviewPositionsChart" height="60"></canvas>
            </div>
            <div class="card" style="grid-column: 3 / -1;">
                <h3>📡 Signals / Orders推移</h3>
                <canvas id="overviewSignalsChart" height="60"></canvas>
            </div>
        </div>
        <div class="grid" style="margin-top:16px">
            <div class="card">
                <h3>Pending / Mismatched Orders</h3>
                ${this.renderPendingOrdersTable((this.data.reconciliation || {}).pending_orders || [])}
            </div>
            <div class="card">
                <h3>Reconciliation by Symbol</h3>
                ${this.renderReconciliationBySymbolTable((this.data.reconciliation || {}).by_symbol || [])}
            </div>
        </div>`;
    }

    // Signals / Orders mini renderer
    renderSignalsOrdersWithDates(data) {
        if (!data || data.length === 0) return '<p class="muted">データなし</p>';
        // 最大値を見つけて正規化
        const allValues = data.flatMap(d => [(d.signals||d.signals_value||0), (d.orders||d.orders_value||0)]);
        const maxValue = Math.max(...allValues, 1);
        const bars = data.map(d => {
            const signalHeight = Math.max(((d.signals||d.signals_value||0) / maxValue) * 60, 2); // 60px最大高
            const orderHeight = Math.max(((d.orders||d.orders_value||0) / maxValue) * 60, 2);
            return `<div style="display:flex;gap:4px;align-items:end"><div class="mini-bar" style="height:${signalHeight}px;background:#60a5fa;width:8px"></div><div class="mini-bar" style="height:${orderHeight}px;background:#34d399;width:8px"></div></div>`;
        }).join('');
        return `<div class="mini-chart"><div class="dual-bars">${bars}</div></div>`;
    }

    renderPendingOrdersTable(data) {
        if (!data || data.length === 0) return '<p class="muted">保留注文なし</p>';
        return `<div class="table-wrap"><table><thead><tr><th>時刻</th><th>シンボル</th><th>Side</th><th>Qty</th><th>Status</th></tr></thead><tbody>${data.map(o=>`<tr><td>${fmt.dt(o.ts)}</td><td>${this.escapeHtml(o.symbol)}</td><td>${this.escapeHtml(o.side)}</td><td>${o.qty}</td><td>${this.escapeHtml(o.status)}</td></tr>`).join('')}</tbody></table></div>`;
    }

    renderReconciliationBySymbolTable(data) {
        if (!data || data.length === 0) return '<p class="muted">整合性データなし</p>';
        return `<div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Submissions</th><th>Mismatches</th></tr></thead><tbody>${data.map(r=>`<tr><td>${this.escapeHtml(r.symbol)}</td><td>${r.submissions||0}</td><td>${r.mismatches||0}</td></tr>`).join('')}</tbody></table></div>`;
    }

    renderAlerts() {
        const alerts = this.data?.alerts || [];
        if (alerts.length === 0) {
            return `<div class="card"><h3>要対応アラート</h3><p class="muted">現在、重要なアラートはありません。</p></div>`;
        }
        return `
        <div class="card alerts-card" style="margin-bottom:16px">
            <h3>要対応アラート (${alerts.length}件)</h3>
            <div class="alerts-list">
                ${alerts.map(a => `
                    <div class="alert alert-${a.severity}">
                        <div class="alert-head">
                            ${this.renderSeverityBadge(a.severity)}
                            <strong>${this.escapeHtml(a.title || a.code)}</strong>
                        </div>
                        <div class="alert-message">${this.escapeHtml(a.message || '')}</div>
                        ${a.action_hint ? `<div class="muted small">対応: ${this.escapeHtml(a.action_hint)}</div>` : ''}
                    </div>`).join('')}
            </div>
        </div>`;
    }

    renderSeverityBadge(severity) {
        switch (severity) {
            case 'critical': return fmt.badge('CRITICAL', 'danger');
            case 'warning': return fmt.badge('WARNING', 'warn');
            case 'info': return fmt.badge('INFO', 'success');
            default: return fmt.badge('UNKNOWN', 'unknown');
        }
    }

    renderOverviewKpis() {
        const ov = this.data?.overview || {};
        const ts = ov.trading_summary || {};
        const deltas = ov.deltas || {};
        const ps = this.data?.positions?.summary || {};
        const account = ov.account || {};
        const latestEquity = account.equity || 0;
        const cash = account.cash || 0;
        const cashPct = latestEquity > 0 ? (cash / latestEquity) : 0;
        const positionPct = latestEquity > 0 ? ((latestEquity - cash) / latestEquity) : 0;
        const totalPnL = (ps.unrealized_pnl || 0) + (ts.cumulative_realized_pnl || 0);
        const winRate = ts.win_rate || 0;
        const maxDD = ts.max_drawdown_pct || 0;

        return `
        <div class="grid">
            <div class="card performance-card ${latestEquity > 100000 ? 'success-border' : 'warn-border'}">
                <h3>💰 資産総額</h3>
                <div class="metric big-metric">
                    <span class="value huge success">${fmt.usd(latestEquity)}</span>
                </div>
                <div class="metric"><span class="label">現金</span><span class="value">${fmt.usd(cash)}</span></div>
                <div class="metric"><span class="label">ポジション</span><span class="value">${fmt.usd(ps.gross_exposure)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">現金比率</div>
                    <div class="progress-bar">
                        <div class="progress-fill success" style="width: ${cashPct * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(cashPct)}</div>
                </div>
                ${this.renderDelta(deltas.equity_vs_prev_snapshot, 'usd')}
            </div>
            
            <div class="card performance-card ${totalPnL >= 0 ? 'success-border' : 'danger-border'}">
                <h3>📊 損益</h3>
                <div class="metric big-metric">
                    <span class="value huge ${totalPnL >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(totalPnL)}</span>
                </div>
                <div class="metric"><span class="label">含み損益</span><span class="value ${ps.unrealized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ps.unrealized_pnl)}</span></div>
                <div class="metric"><span class="label">確定損益</span><span class="value ${ts.cumulative_realized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ts.cumulative_realized_pnl)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">PnL比率 (vs Equity)</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${totalPnL >= 0 ? 'success' : 'danger'}" style="width: ${Math.min(Math.abs(totalPnL / latestEquity) * 100, 100)}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(totalPnL / latestEquity)}</div>
                </div>
            </div>
            
            <div class="card performance-card ${winRate >= 0.6 ? 'success-border' : 'warn-border'}">
                <h3>🎯 取引成績</h3>
                <div class="metric"><span class="label">総取引数</span><span class="value">${ts.total_trades ?? 0}</span></div>
                <div class="metric"><span class="label">オープン</span><span class="value">${ts.open_trades ?? 0}</span></div>
                <div class="metric"><span class="label">勝率</span><span class="value ${winRate >= 0.6 ? 'success' : 'warn'}">${fmt.pct(winRate)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">勝率</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${winRate >= 0.6 ? 'success' : 'warn'}" style="width: ${winRate * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(winRate)}</div>
                </div>
                ${this.renderDelta(deltas.open_trades_vs_prev_snapshot, 'count')}
            </div>
            
            <div class="card performance-card warn-border">
                <h3>⚠️ リスク</h3>
                <div class="metric"><span class="label">Gross Exposure</span><span class="value">${fmt.usd(ps.gross_exposure)}</span></div>
                <div class="metric"><span class="label">最大DD</span><span class="value ${maxDD > 0.05 ? 'danger' : 'success'}">${fmt.pct(maxDD)}</span></div>
                <div class="metric"><span class="label">Exposure比率</span><span class="value">${fmt.pct(positionPct)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">Drawdownレベル</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${maxDD > 0.05 ? 'danger' : 'success'}" style="width: ${maxDD * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(maxDD)}</div>
                </div>
            </div>
            
            <div class="card">
                <h3>📡 意思決定</h3>
                <div class="metric"><span class="label">Decisions</span><span class="value">${this.data?.data_status?.counts?.decisions ?? 0}</span></div>
                <div class="metric"><span class="label">Signals</span><span class="value">${this.data?.data_status?.counts?.signals ?? 0}</span></div>
                <div class="metric"><span class="label">Orders</span><span class="value">${this.data?.data_status?.counts?.orders ?? 0}</span></div>
                ${this.renderDelta(deltas.decisions_vs_prev_snapshot, 'count')}
            </div>
            
            <div class="card">
                <h3>📊 集中度</h3>
                <div class="metric"><span class="label">最大ポジション</span><span class="value">${fmt.pct(ps.largest_position_weight)}</span></div>
                <div class="metric"><span class="label">Top 5集中</span><span class="value">${fmt.pct(ps.top5_concentration)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">集中リスク</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${(ps.top5_concentration || 0) > 0.5 ? 'danger' : 'success'}" style="width: ${(ps.top5_concentration || 0) * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(ps.top5_concentration)}</div>
                </div>
            </div>
        </div>`;
    }

    renderOverviewDiagnostics() {
        const ov = this.data?.overview || {};
        const sys = this.data?.system || {};
        const cron = this.data?.cron_jobs || {};
        const dataStatus = this.data?.data_status || {};
        return `
        <div class="grid">
            <div class="card">
                <h3>システム</h3>
                <div class="metric"><span class="label">状態</span><span>${fmt.badge((sys.status||'unknown').toUpperCase(), sys.status||'unknown')}</span></div>
                <div class="metric"><span class="label">スコア</span><span class="value">${sys.score||0}/100</span></div>
                <div class="metric"><span class="label">実行モード</span><span class="value">${sys.runtime_mode||'?'}</span></div>
                <div class="metric"><span class="label">APIキー</span><span>${sys.api_keys_configured ? '✅ OK' : '❌ 未設定'}</span></div>
            </div>
            <div class="card">
                <h3>定期実行</h3>
                <div class="metric"><span class="label">有効</span><span class="value success">${ov.cron_jobs_active||0}</span></div>
                <div class="metric"><span class="label">合計</span><span class="value">${ov.cron_jobs_total||0}</span></div>
                <div class="metric"><span class="label">遅延ジョブ</span><span class="value ${(cron.jobs || []).some(j => (j.lag_seconds||0) > 0) ? 'danger' : 'success'}">${(cron.jobs || []).filter(j => (j.lag_seconds||0) > 0).length}</span></div>
            </div>
            <div class="card">
                <h3>Reconciliation</h3>
                ${this.renderReconciliationSummary(this.data.reconciliation || {})}
            </div>
            <div class="card">
                <h3>データファイル</h3>
                ${this.renderDataCountsCompact(ov.data_counts)}
            </div>
            ${this.renderDataIntegrityCard(dataStatus.integrity)}
        </div>`;
    }

    renderDataCountsCompact(counts) {
        if (!counts) return '<p class="muted">データなし</p>';
        return Object.entries(counts).map(([stage, count]) => 
            `<div class="metric"><span class="label">${stage}</span><span class="value ${count > 0 ? '' : 'muted'}">${count}</span></div>`
        ).join('');
    }

    renderReconciliationSummary(rec = {}) {
        return `
            <div class="metric"><span class="label">Recent Reconciliations</span><span class="value">${rec.recent_reconciliations ?? 0}</span></div>
            <div class="metric"><span class="label">Recent Submissions</span><span class="value">${rec.recent_submissions ?? 0}</span></div>
            <div class="metric"><span class="label">Pending/Mismatched</span><span class="value ${(rec.pending_or_mismatched || 0) > 0 ? 'danger' : 'success'}">${rec.pending_or_mismatched ?? 0}</span></div>
            <div class="metric"><span class="label">Last Run</span><span class="small muted">${rec.last_run ? fmt.dt(rec.last_run) : '—'}</span></div>
            <div class="metric"><span class="label">Last Success</span><span class="small muted">${rec.last_success ? fmt.dt(rec.last_success) : '—'}</span></div>
            ${(rec.discrepancy_types || []).slice(0, 3).map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.reason)}</span><span class="value">${r.count}</span></div>`).join('')}
        `;
    }

    renderDataIntegrityCard(integrity) {
        if (!integrity) return '<div class="card"><h3>整合性</h3><p class="muted">チェックなし</p></div>';
        return `
        <div class="card">
            <h3>整合性</h3>
            <div class="metric"><span class="label">状態</span><span>${fmt.badge((integrity.status || 'unknown').toUpperCase(), integrity.status || 'unknown')}</span></div>
            ${(integrity.checks || []).map(c => `
                <div class="metric">
                    <span class="label">${this.escapeHtml(c.name)}</span>
                    <span class="small ${c.status === 'fail' ? 'danger' : c.status === 'warn' ? 'warn' : 'success'}">${this.escapeHtml(c.message || '')}</span>
                </div>`).join('')}
        </div>`;
    }

    renderTrading() {
        const td = this.data.trading || {};
        const pipeline = this.data.pipeline || {};
        
        if (!td.available) {
            return `<div class="card"><p class="muted">取引データが利用できません。${td.error||''}</p></div>`;
        }
        
        const s = td.summary || {};
        const recent = td.recent_trades || [];
        const allClosedTrades = td.closed_trades || recent;
        const snaps = td.daily_snapshots || [];
        const tracking = s.tracking_context || {};
        const winRate = s.win_rate;
        const wr_cls = winRate >= 0.55 ? 'success' : winRate < 0.40 && s.closed_trades > 0 ? 'danger' : 'warn';
        const shortAccountId = tracking.broker_account_id ? `${tracking.broker_account_id.slice(0, 8)}…` : '—';
        const shortArchivedAccountId = tracking.archived_from_account_id ? `${tracking.archived_from_account_id.slice(0, 8)}…` : '—';
        
        // 戦略別パフォーマンスを計算
        const strategyPerf = this.calculateStrategyPerformance(pipeline.by_strategy || [], allClosedTrades);

        return `
        ${this.renderPipelineFunnel()}
        <div class="grid" style="margin-bottom:16px">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>📋 取引履歴</h3>
                <div class="small muted" style="margin-bottom:8px">直近48時間を優先表示。件数が少ない場合は直近50件まで補完。現在表示: ${recent.length}件</div>
                ${this.renderRecentTrades(recent)}
            </div>
        </div>
        <div class="grid">
            <div class="card">
                <h3>トラッキング範囲</h3>
                <div class="metric"><span class="label">スコープ</span><span class="value">${this.escapeHtml(tracking.performance_scope || 'current_account_since_baseline')}</span></div>
                <div class="metric"><span class="label">現アカウント</span><span class="value">${this.escapeHtml(shortAccountId)}</span></div>
                <div class="metric"><span class="label">基準日</span><span class="value">${tracking.baseline_date || '—'}</span></div>
                <div class="metric"><span class="label">開始資金</span><span class="value">${tracking.baseline_equity != null ? fmt.usd(tracking.baseline_equity) : '—'}</span></div>
                <div class="metric"><span class="label">ラベル</span><span class="small muted">${this.escapeHtml(tracking.tracking_label || '—')}</span></div>
            </div>
            <div class="card">
                <h3>旧成績アーカイブ</h3>
                <div class="metric"><span class="label">旧アカウント</span><span class="value">${this.escapeHtml(shortArchivedAccountId)}</span></div>
                <div class="metric"><span class="label">退避先</span><span class="small muted">${this.escapeHtml(tracking.archive_path || '—')}</span></div>
                <div class="metric"><span class="label">移行メモ</span><span class="small muted">${this.escapeHtml(tracking.migration_note_path || '—')}</span></div>
                <div class="small muted">旧成績は上記アーカイブ配下、新成績は 2026-05-12 基準で集計しています。</div>
            </div>
            <div class="card">
                <h3>パフォーマンス</h3>
                <div class="metric"><span class="label">取引数(open+closed)</span><span class="value">${s.total_trades||0}</span></div>
                <div class="metric"><span class="label">決済取引数</span><span class="value">${s.closed_trades||0}</span></div>
                <div class="metric"><span class="label">保有取引数</span><span class="value">${s.open_trades||0}</span></div>
                <div class="metric"><span class="label">reconciled removed</span><span class="value muted">${s.reconciled_removed_trades||0}</span></div>
                <div class="metric"><span class="label">勝 / 負 / 引分</span><span class="value">${s.winning_trades||0} / ${s.losing_trades||0} / ${s.flat_trades||0}</span></div>
                <div class="metric"><span class="label">勝率</span><span class="value ${wr_cls}">${fmt.pct(winRate)}</span></div>
                <div class="metric"><span class="label">平均リターン</span><span class="value ${(s.avg_return_per_trade ?? 0) >= 0 ? 'success':'danger'}">${s.avg_return_per_trade == null ? '—' : fmt.pctSigned(s.avg_return_per_trade)}</span></div>
                <div class="metric"><span class="label">有効return取引数</span><span class="value">${s.valid_return_trade_count||0}</span></div>
            </div>
            <div class="card">
                <h3>パフォーマンス推移</h3>
                ${this.renderDailySnapshots(snaps)}
            </div>
        </div>
        <div class="grid" style="margin-top:16px">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>🎯 戦略別パフォーマンス</h3>
                ${this.renderStrategyPerformanceTable(strategyPerf)}
            </div>
        </div>`;
    }

    formatStrategyLabel(value) {
        return this.escapeHtml((value || '').replace(/_/g, ' '));
    }

    calculateStrategyPerformance(pipelineData, trades) {
        const strategyStats = {};
        
        // Initialize from pipeline data
        pipelineData.forEach(s => {
            strategyStats[s.strategy_id] = {
                strategy_id: s.strategy_id,
                strategy_version_id: s.strategy_version_id || s.strategy_id,
                decisions: s.decisions || 0,
                buy: s.buy || 0,
                sell: s.sell || 0,
                deny: s.deny || 0,
                pass: s.pass || 0,
                reject: s.reject || 0,
                realized_pnl: s.realized_pnl || 0,
                open_positions: s.open_positions || 0,
                rejection_rate: s.rejection_rate || 0,
                conversion_rate: s.decisions ? ((s.buy + s.sell) / s.decisions) : 0,
                // Trade stats (will calculate from trades)
                closed_trades: 0,
                winning_trades: 0,
                losing_trades: 0,
                win_rate: 0,
                avg_pnl: 0,
                avg_return_pct: 0
            };
        });
        
        // Calculate trade stats from actual trades
        trades.forEach(trade => {
            const sid = trade.strategy_id || 'unknown';
            if (!strategyStats[sid]) {
                strategyStats[sid] = {
                    strategy_id: trade.original_strategy_id || sid,
                    strategy_version_id: trade.strategy_version_id || sid,
                    decisions: 0,
                    buy: 0,
                    sell: 0,
                    deny: 0,
                    pass: 0,
                    reject: 0,
                    realized_pnl: 0,
                    open_positions: 0,
                    rejection_rate: 0,
                    conversion_rate: 0,
                    closed_trades: 0,
                    winning_trades: 0,
                    losing_trades: 0,
                    win_rate: 0,
                    avg_pnl: 0,
                    avg_return_pct: 0
                };
            }
            
            if (trade.status === 'closed') {
                strategyStats[sid].closed_trades++;
                strategyStats[sid].realized_pnl = (strategyStats[sid].realized_pnl || 0) + (trade.pnl || 0);
                if ((trade.pnl || 0) > 0) {
                    strategyStats[sid].winning_trades++;
                } else if ((trade.pnl || 0) < 0) {
                    strategyStats[sid].losing_trades++;
                }
            }
        });
        
        // Calculate averages and win rates
        Object.keys(strategyStats).forEach(sid => {
            const s = strategyStats[sid];
            if (s.closed_trades > 0) {
                s.win_rate = s.winning_trades / s.closed_trades;
                s.avg_pnl = s.realized_pnl / s.closed_trades;
            }
        });
        
        return Object.values(strategyStats).sort((a, b) => b.realized_pnl - a.realized_pnl);
    }

    renderStrategyPerformanceTable(data) {
        if (!data || data.length === 0) return '<p class="muted">戦略データなし</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>戦略</th>
            <th>strategy_version_id</th>
            <th>決済取引</th>
            <th>勝率</th>
            <th>勝/負</th>
            <th>平均PnL</th>
            <th>累積実現PnL</th>
            <th>オープン</th>
            <th>意思決定</th>
            <th>submitted_decisions</th>
            <th>Buy</th>
            <th>Sell</th>
            <th>Deny</th>
            <th>却下率</th>
            <th>コンバージョン</th>
        </tr></thead><tbody>
        ${data.map(s => {
            const winRateClass = (s.win_rate || 0) >= 0.6 ? 'success' : (s.win_rate || 0) >= 0.4 ? 'warn' : 'danger';
            const pnlClass = (s.realized_pnl || 0) >= 0 ? 'success' : 'danger';
            const conversionRate = (s.conversion_rate || 0) > 1 ? (s.conversion_rate || 0) / 100 : (s.conversion_rate || 0);
            return `
            <tr>
                <td><strong>${this.formatStrategyLabel(s.strategy_id || '')}</strong></td>
                <td class="small">${this.formatStrategyLabel(s.strategy_version_id || s.strategy_id || '')}</td>
                <td>${s.closed_trades || 0}</td>
                <td class="${winRateClass}">${fmt.pct(s.win_rate || 0)}</td>
                <td>${s.winning_trades || 0} / ${s.losing_trades || 0}</td>
                <td class="${pnlClass}">${fmt.usdSigned(s.avg_pnl || 0)}</td>
                <td class="${pnlClass}"><strong>${fmt.usdSigned(s.realized_pnl || 0)}</strong></td>
                <td>${s.open_positions || 0}</td>
                <td>${s.decisions || 0}</td>
                <td>${s.submitted_decisions || 0}</td>
                <td class="success">${s.buy || 0}</td>
                <td class="warn">${s.sell || 0}</td>
                <td class="danger">${s.deny || 0}</td>
                <td>${fmt.pct((s.rejection_rate || 0) / 100)}</td>
                <td>${fmt.pct(conversionRate)}</td>
            </tr>`;
        }).join('')}
        </tbody></table></div>`;
    }

    renderStrategyOverviewTable(data) {
        if (!data || data.length === 0) return '<p class="muted">データなし</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>戦略</th><th>意思決定</th><th>Buy</th><th>Sell</th><th>Conversion</th>
        </tr></thead><tbody>
        ${data.map(strategy => `
            <tr><td>${this.escapeHtml(strategy.name)}</td>
                <td>${strategy.decisions}</td>
                <td>${strategy.buy}</td>
                <td>${strategy.sell}</td>
                <td>${fmt.pct(strategy.conversion_rate)}</td>
            </tr>`).join('')}
        </tbody></table></div>`;
    }

    renderPipelineFunnel() {
        const p = this.data.pipeline || {};
        const funnel = p.funnel || {};
        const normalizedReasons = p.rejection_breakdown || {};

        // ブロック理由の日本語マッピング
        const reasonLabels = {
            'position_size_limit_exceeded': '📊 ポジションサイズ上限',
            'position_size_limit':          '📊 ポジションサイズ上限',
            'confidence_below_minimum':     '🎯 Confidence 不足',
            'portfolio_cap':                '📊 ポートフォリオ上限',
            'guardrail_halt':               '🚨 Guardrail HALT',
            'guardrail_block_buys':         '🚨 Guardrail Block',
            'entry_filter':                 '🔍 エントリーフィルター',
            'rolling_pf_gate':              '🔍 PF ゲート',
            'stock_reduced_mode':           '🔍 Stock reduced',
            'volume_filter':                '🔍 出来高フィルター',
            'adr_filter':                   '🔍 ADR フィルター',
            'risk_budget':                  '💰 リスクバジェット',
            'risk_limit_exceeded':          '💰 リスク上限',
            'exposure_preflight':           '💰 Exposure制限',
            'deny_without_reason':          '⚠️ 理由不明',
        };

        const reasonsHtml = Object.keys(normalizedReasons).length > 0
            ? Object.entries(normalizedReasons)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => {
                    const label = reasonLabels[k] || k;
                    return `<div class="funnel-reason-row">
                        <span class="funnel-reason-label">${this.escapeHtml(label)}</span>
                        <span class="funnel-reason-count danger">${v}件</span>
                    </div>`;
                }).join('')
            : '<div class="muted small">ブロックなし</div>';

        return `
        <div class="grid funnel-grid">
            <div class="funnel-item"><div>
                <div class="perf-label">Decisions</div>
                <div class="perf-value">${funnel.decisions || p.total_signals || '0'}</div>
            </div></div>
            <div class="funnel-item"><div>
                <div class="perf-label">Denied</div>
                <div class="perf-value danger">${funnel.risk_rejected || '0'}</div>
            </div></div>
            <div class="funnel-item"><div>
                <div class="perf-label">Submitted</div>
                <div class="perf-value">${funnel.orders_submitted || p.total_orders || '0'}</div>
            </div></div>
            <div class="funnel-item"><div>
                <div class="perf-label">Filled</div>
                <div class="perf-value success">${funnel.orders_filled || p.total_filled || '0'}</div>
            </div></div>
        </div>
        ${funnel.risk_rejected > 0 ? `
        <div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">🚫 ブロック理由の内訳</h4>
            ${reasonsHtml}
        </div>` : ''}`;
    }

    renderRecentTrades(data) {
        if (!data || data.length === 0) return '<p class="muted">取引履歴なし</p>';
        // 最新の取引が上に来るようにソート
        const sortedData = [...data].sort((a, b) => {
            const dateA = new Date(a.exit_time || a.entry_time || 0);
            const dateB = new Date(b.exit_time || b.entry_time || 0);
            return dateB - dateA; // 降順（最新が上）
        });
        return `<div class="table-wrap"><table><thead><tr>
            <th>エントリー</th><th>エグジット</th><th>シンボル</th><th>数量</th><th>エントリー価格</th><th>エグジット価格</th><th>PnL</th><th>リターン</th><th>元戦略</th><th>strategy_version_id</th><th>ステータス</th>
        </tr></thead><tbody>
        ${sortedData.map(trade => `
            <tr>
                <td class="small">${fmt.dt(trade.entry_time)}</td>
                <td class="small">${trade.exit_time ? fmt.dt(trade.exit_time) : '—'}</td>
                <td><strong>${this.escapeHtml(trade.symbol)}</strong></td>
                <td>${trade.qty || trade.quantity || 0}</td>
                <td>${fmt.usd(trade.entry_price)}</td>
                <td>${trade.exit_price ? fmt.usd(trade.exit_price) : '—'}</td>
                <td class="${(trade.pnl || 0) >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(trade.pnl || 0)}</td>
                <td class="${(trade.return_pct || 0) >= 0 ? 'success' : 'danger'}">${fmt.pctSigned(trade.return_pct || 0)}</td>
                <td class="small">${this.formatStrategyLabel(trade.original_strategy_id || trade.strategy_id || '')}</td>
                <td class="small">${this.formatStrategyLabel(trade.strategy_version_id || trade.strategy_id || '')}</td>
                <td><span class="badge badge-${trade.status === 'closed' ? 'success' : trade.status === 'open' ? 'warn' : 'unknown'}">${this.escapeHtml(trade.status || '-')}</span></td>
            </tr>`).join('')}
        </tbody></table></div>`;
    }

    renderDailySnapshots(data) {
        if (!data || data.length === 0) return '<p class="muted">日次データなし</p>';
        // 最新の日付が上に来るようにソート
        const sortedData = [...data].sort((a, b) => {
            const dateA = new Date(a.date || 0);
            const dateB = new Date(b.date || 0);
            return dateB - dateA; // 降順（最新が上）
        });
        return `<div class="table-wrap"><table><thead><tr>
            <th>日付</th><th>Equity</th><th>Gross Exposure</th><th>最大DD</th>
            <th>勝率</th><th>平均リターン</th>
        </tr></thead><tbody>
        ${sortedData.map(snapshot => `
            <tr><td>${fmt.dt(snapshot.date)}</td>
                <td>${fmt.usd(snapshot.equity)}</td>
                <td>${fmt.usd(snapshot.gross_exposure)}</td>
                <td>${fmt.pct(snapshot.max_drawdown_pct)}</td>
                <td>${fmt.pct(snapshot.win_rate)}</td>
                <td>${fmt.pctSigned(snapshot.avg_return_per_trade)}</td>
            </tr>`).join('')}
        </tbody></table></div>`;
    }

    renderPositions() {
        const positions = this.data.positions || {};
        const posArr = positions.positions || positions.by_symbol || [];
        const summary = positions.summary || {};
        
        // ポジションを評価額でソート
        const sortedPositions = [...posArr].sort((a, b) => (b.market_value || 0) - (a.market_value || 0));
        
        return `
        <div class="grid">
            <div class="card performance-card ${summary.unrealized_pnl >= 0 ? 'success-border' : 'danger-border'}">
                <h3>📊 ポートフォリオサマリー</h3>
                <div class="metric big-metric">
                    <span class="label">評価損益</span>
                    <span class="value huge ${summary.unrealized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(summary.unrealized_pnl || 0)}</span>
                </div>
                <div class="metric"><span class="label">評価損益率</span><span class="value ${summary.total_pnl_pct >= 0 ? 'success' : 'danger'}">${fmt.pctSigned(summary.total_pnl_pct || 0)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">PnL率</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${summary.total_pnl_pct >= 0 ? 'success' : 'danger'}" style="width: ${Math.min(Math.abs(summary.total_pnl_pct || 0) * 100, 100)}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pctSigned(summary.total_pnl_pct || 0)}</div>
                </div>
            </div>
            
            <div class="card">
                <h3>💼 エクスポージャー</h3>
                <div class="metric"><span class="label">Gross Exposure</span><span class="value">${fmt.usd(summary.gross_exposure || 0)}</span></div>
                <div class="metric"><span class="label">Net Exposure</span><span class="value">${fmt.usd(summary.net_exposure || 0)}</span></div>
                <div class="metric"><span class="label">現金</span><span class="value">${fmt.usd(summary.cash || 0)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">Exposure比率</div>
                    <div class="progress-bar">
                        <div class="progress-fill warn" style="width: ${Math.min((summary.gross_exposure || 0) / (summary.portfolio_value || 1) * 100, 100)}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct((summary.gross_exposure || 0) / (summary.portfolio_value || 1))}</div>
                </div>
            </div>
            
            <div class="card">
                <h3>📈 ポジション統計</h3>
                <div class="metric"><span class="label">総ポジション数</span><span class="value">${summary.position_count || 0}</span></div>
                <div class="metric"><span class="label">ロング / ショート</span><span class="value">${summary.long_count || 0} / ${summary.short_count || 0}</span></div>
                <div class="metric"><span class="label">平均保有日数</span><span class="value">${(summary.avg_holding_days || 0).toFixed(1)}日</span></div>
                <div class="metric"><span class="label">最大ポジション比率</span><span class="value">${fmt.pct(summary.largest_position_weight || 0)}</span></div>
            </div>
            
            <div class="card">
                <h3>⚠️ 集中リスク</h3>
                <div class="metric"><span class="label">Top 5集中度</span><span class="value ${(summary.top5_concentration || 0) > 0.7 ? 'danger' : 'success'}">${fmt.pct(summary.top5_concentration || 0)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">集中度</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${(summary.top5_concentration || 0) > 0.7 ? 'danger' : 'success'}" style="width: ${(summary.top5_concentration || 0) * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(summary.top5_concentration || 0)}</div>
                </div>
            </div>
        </div>
        
        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>📋 現在のポジション (${sortedPositions.length}件)</h3>
                ${this.renderPositionsTable(sortedPositions)}
            </div>
        </div>`;
    }

    renderPositionsTable(data) {
        if (!data || data.length === 0) return '<p class="muted">ポジションなし</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>シンボル</th><th>数量</th><th>保有日数</th><th>取得価格</th><th>現在価格</th><th>評価損益</th><th>損益率</th><th>Peak</th><th>ストップ水準</th><th>ストップまで</th><th>比率</th>
        </tr></thead><tbody>
        ${data.map(pos => {
            const pnlPct = pos.unrealized_pnl_pct ?? pos.unrealized_return_pct ?? pos.return_pct ?? 0;
            const pnlClass = (pos.unrealized_pnl || 0) >= 0 ? 'success' : 'danger';
            const pnlPctClass = pnlPct >= 0 ? 'success' : 'danger';
            // Stop level display
            const stopPrice = pos.effective_stop_price;
            const distPct = pos.dist_to_stop_pct;
            const trailingActive = pos.trailing_active;
            const stopLabel = stopPrice ? fmt.usd(stopPrice) : '—';
            const stopMode = trailingActive ? '🔵 Trail' : '🟡 Hard';
            const distLabel = distPct != null ? `▲${distPct.toFixed(1)}%` : '—';
            const distClass = distPct == null ? '' : distPct < 1.5 ? 'danger' : distPct < 3 ? 'warn' : 'success';
            // Trailing active row highlight
            const rowStyle = trailingActive ? 'background:rgba(16,185,129,0.07);' : '';
            const trailBadge = trailingActive ? ' <span class="badge badge-success" title="Trailing Stop 起動中🔒">🔵Trail</span>' : '';
            return `
            <tr style="${rowStyle}">
                <td><strong>${this.escapeHtml(pos.symbol)}</strong>${trailBadge}</td>
                <td>${pos.qty || pos.quantity || 0}</td>
                <td>${pos.holding_days != null ? pos.holding_days + '日' : '—'}</td>
                <td>${fmt.usd(pos.entry_price ?? pos.avg_entry_price ?? pos.avg_price ?? 0)}</td>
                <td>${fmt.usd(pos.current_price || 0)}</td>
                <td class="${pnlClass}">${fmt.usdSigned(pos.unrealized_pnl || 0)}</td>
                <td class="${pnlPctClass}">${fmt.pctSigned(pnlPct)}</td>
                <td class="small">${pos.peak_price ? fmt.usd(pos.peak_price) : '—'}</td>
                <td class="small">${stopPrice ? `<span title="${stopMode}">${stopLabel}</span>` : '—'}</td>
                <td class="${distClass} small">${distLabel}</td>
                <td>${fmt.pct(pos.portfolio_weight || 0)}</td>
            </tr>`;
        }).join('')}
        </tbody></table></div>`;
    }

    renderCronJobs() {
        const cron = this.data.cron_jobs || {};
        const jobsArr = cron.jobs || [];
        
        // 状態の統計
        const totalJobs = jobsArr.length;
        const enabledJobs = jobsArr.filter(j => j.enabled).length;
        const laggedJobs = jobsArr.filter(j => (j.lag_seconds || 0) > 3600).length; // 1時間以上遅延
        const criticalLag = jobsArr.filter(j => (j.lag_seconds || 0) > 86400).length; // 1日以上遅延
        
        return `<div class="grid">
            <div class="card">
                <h3>🔄 定期実行統計</h3>
                <div class="metric"><span class="label">総ジョブ数</span><span class="value">${totalJobs}</span></div>
                <div class="metric"><span class="label">有効</span><span class="value success">${enabledJobs}</span></div>
                <div class="metric"><span class="label">遅延中 (>1h)</span><span class="value ${laggedJobs > 0 ? 'warn' : 'success'}">${laggedJobs}</span></div>
                <div class="metric"><span class="label">重大遅延 (>1d)</span><span class="value ${criticalLag > 0 ? 'danger' : 'success'}">${criticalLag}</span></div>
            </div>
        </div>
        
        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>📊 ジョブ一覧 (${totalJobs}件)</h3>
                ${this.renderCronJobsTable(jobsArr)}
            </div>
        </div>`;
    }

    renderCronJobsTable(data) {
        if (!data || data.length === 0) return '<p class="muted">ジョブなし</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>名前</th><th>スケジュール</th><th>状態</th><th>最終実行</th><th>次回実行</th><th>遅延</th><th>成功率 (7d)</th><th>平均実行時間</th>
        </tr></thead><tbody>
        ${data.map(job => {
            const lagSeconds = job.lag_seconds || 0;
            const lagClass = lagSeconds > 86400 ? 'danger' : lagSeconds > 3600 ? 'warn' : 'success';
            const lagDisplay = this.formatDuration(lagSeconds);
            const avgDuration = this.formatDuration((job.avg_duration_ms || 0) / 1000);
            const successRate = job.success_rate_7d || 0;
            const successClass = successRate >= 0.9 ? 'success' : successRate >= 0.7 ? 'warn' : 'danger';
            
            return `
            <tr>
                <td><strong>${this.escapeHtml((job.name || '').replace('stock_swing_', ''))}</strong></td>
                <td class="small">${this.escapeHtml(job.schedule?.expr || '-')}</td>
                <td><span class="badge badge-${job.enabled ? 'success' : 'unknown'}">${job.enabled ? '有効' : '無効'}</span></td>
                <td class="small">${fmt.dt(job.last_run)}</td>
                <td class="small">${fmt.dt(job.next_run)}</td>
                <td class="${lagClass}"><strong>${lagDisplay}</strong></td>
                <td class="${successClass}">${fmt.pct(successRate)}</td>
                <td class="small">${avgDuration}</td>
            </tr>`;
        }).join('')}
        </tbody></table></div>`;
    }
    
    formatDuration(seconds) {
        if (seconds < 60) return `${Math.floor(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
        return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
    }

    renderDataStatus() {
        const dataStatus = this.data.data_status || {};
        return `<div class="grid">
            <div class="card">
                ${this.renderDataCounts(dataStatus.counts)}
            </div>
            <div class="card">
                ${this.renderDataIntegrity(dataStatus.integrity)}
            </div>
        </div>`;
    }

    renderDataCounts(counts) {
        if (!counts) return '<p class="muted">データなし</p>';
        return Object.entries(counts).map(([key, value]) =>
            `<div class="metric"><span class="label">${key}</span><span class="value ${value > 0 ? '' : 'muted'}">${value}</span></div>`
        ).join('');
    }

    renderDataIntegrity(integrity) {
        if (!integrity) return '<p class="muted">整合性確認未実行</p>';
        return integrity.checks.map(check =>
            `<div class="metric"><span class="label">${this.escapeHtml(check.name)}</span><span class="small ${check.status}">${this.escapeHtml(check.message)}</span></div>`
        ).join('');
    }

    renderArchives() {
        const archiveData = this.data.archives || {};
        const current = archiveData.current || {};
        const archives = archiveData.archives || [];
        const docs = archiveData.migration_docs || [];

        return `
        <div class="grid">
            <div class="card">
                <h3>現行トラッキング</h3>
                <div class="metric"><span class="label">現アカウント</span><span class="value">${this.escapeHtml(current.account_id || '—')}</span></div>
                <div class="metric"><span class="label">基準日</span><span class="value">${this.escapeHtml(current.baseline_date || '—')}</span></div>
                <div class="metric"><span class="label">開始資金</span><span class="value">${current.baseline_equity != null ? fmt.usd(current.baseline_equity) : '—'}</span></div>
                <div class="metric"><span class="label">現行取引数</span><span class="value">${current.trade_count || 0}</span></div>
                <div class="metric"><span class="label">累積実現PnL</span><span class="value ${(current.cumulative_realized_pnl || 0) >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(current.cumulative_realized_pnl || 0)}</span></div>
                <div class="metric"><span class="label">移行メモ</span><span class="small muted">${this.escapeHtml(current.migration_note_path || '—')}</span></div>
            </div>
            <div class="card">
                <h3>履歴サマリー</h3>
                <div class="metric"><span class="label">アーカイブ数</span><span class="value">${archives.length}</span></div>
                <div class="metric"><span class="label">移行メモ数</span><span class="value">${docs.length}</span></div>
                <div class="metric"><span class="label">最新アーカイブ</span><span class="value">${this.escapeHtml(archives[0]?.archive_date || '—')}</span></div>
                <div class="small muted">旧成績は archive 配下、現行成績は baseline 以降で集計しています。</div>
            </div>
        </div>
        <div class="card">
            <h3>旧成績アーカイブ一覧</h3>
            ${archives.length ? this.renderArchiveHistoryTable(archives) : '<p class="muted">アーカイブなし</p>'}
        </div>
        <div class="card" style="margin-top:16px;">
            <h3>Migration Notes</h3>
            ${docs.length ? this.renderMigrationDocsTable(docs) : '<p class="muted">移行メモなし</p>'}
        </div>`;
    }

    renderArchiveHistoryTable(data) {
        return `<div class="table-wrap"><table><thead><tr>
            <th>Archive Date</th><th>旧アカウント</th><th>新アカウント</th><th>基準資金</th><th>取引数</th><th>決済/保有</th><th>累積PnL</th><th>ファイル</th><th>参照先</th>
        </tr></thead><tbody>
        ${data.map(item => `
            <tr>
                <td>${this.escapeHtml(item.archive_date || '—')}</td>
                <td class="small">${this.escapeHtml(item.previous_account_id || '—')}</td>
                <td class="small">${this.escapeHtml(item.new_account_id || '—')}</td>
                <td>${item.baseline_equity != null ? fmt.usd(item.baseline_equity) : '—'}</td>
                <td>${item.trade_count || 0}</td>
                <td>${item.closed_trade_count || 0} / ${item.open_trade_count || 0}</td>
                <td class="${(item.cumulative_realized_pnl || 0) >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(item.cumulative_realized_pnl || 0)}</td>
                <td>${item.tracking_files || 0} tracking / ${item.audit_files || 0} audit</td>
                <td><div class="small muted">${this.escapeHtml(item.archive_path || '—')}</div><div class="small muted">${this.escapeHtml(item.note_path || '—')}</div></td>
            </tr>`).join('')}
        </tbody></table></div>`;
    }

    renderMigrationDocsTable(data) {
        return `<div class="table-wrap"><table><thead><tr>
            <th>Date</th><th>Path</th>
        </tr></thead><tbody>
        ${data.map(item => `
            <tr>
                <td>${this.escapeHtml(item.date || '—')}</td>
                <td class="small">${this.escapeHtml(item.path || '—')}</td>
            </tr>`).join('')}
        </tbody></table></div>`;
    }

    renderLogs() {
        const logs = this.data.logs || {};
        const logsArr = logs.lines || logs.entries || [];
        const currentLogFile = (logs.log_file || '').split('/').pop();
        const currentDate = currentLogFile.match(/\d{8}/);
        const dateStr = currentDate ? currentDate[0] : '';
        
        // 過去7日間のログファイルリンクを生成
        const logDates = [];
        const today = new Date();
        for (let i = 0; i < 7; i++) {
            const d = new Date(today);
            d.setDate(d.getDate() - i);
            const year = d.getFullYear();
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            logDates.push(`${year}${month}${day}`);
        }
        
        // ログをパースして統計を取る
        const parsedLogs = logsArr.map(line => this.parseLogLine(line)).filter(l => l);
        const logStats = {
            total: parsedLogs.length,
            info: parsedLogs.filter(l => l.level === 'INFO').length,
            warning: parsedLogs.filter(l => l.level === 'WARNING').length,
            error: parsedLogs.filter(l => l.level === 'ERROR').length,
            categories: {}
        };
        
        parsedLogs.forEach(log => {
            const cat = log.category || 'other';
            logStats.categories[cat] = (logStats.categories[cat] || 0) + 1;
        });
        
        return `<div class="grid">
            <div class="card">
                <h3>📊 ログ統計</h3>
                <div class="metric"><span class="label">総ログ数</span><span class="value">${logStats.total}</span></div>
                <div class="metric"><span class="label">INFO</span><span class="value success">${logStats.info}</span></div>
                <div class="metric"><span class="label">WARNING</span><span class="value warn">${logStats.warning}</span></div>
                <div class="metric"><span class="label">ERROR</span><span class="value danger">${logStats.error}</span></div>
            </div>
            
            <div class="card">
                <h3>📝 カテゴリ分布</h3>
                ${Object.entries(logStats.categories).sort((a, b) => b[1] - a[1]).map(([cat, count]) => 
                    `<div class="metric"><span class="label">${this.escapeHtml(cat)}</span><span class="value">${count}</span></div>`
                ).join('')}
            </div>
            
            <div class="card">
                <h3>📄 ログファイル</h3>
                <div class="metric"><span class="label">現在のファイル</span><span class="value small">${this.escapeHtml(currentLogFile)}</span></div>
                <div class="metric"><span class="label">行数</span><span class="value">${logs.line_count || 0}</span></div>
                <div class="metric"><span class="label">最終更新</span><span class="value small">${fmt.dt(logs.time)}</span></div>
            </div>
            
            <div class="card">
                <h3>📅 過去ログ</h3>
                <p class="muted small">過去のログファイルを表示するには、以下のコマンドを実行:</p>
                ${logDates.map(date => {
                    const isCurrent = date === dateStr;
                    return `<div class="metric"><span class="label">${date.substring(0,4)}-${date.substring(4,6)}-${date.substring(6,8)}</span><span class="value small ${isCurrent ? 'success' : ''}">${isCurrent ? '現在表示中' : '-'}</span></div>`;
                }).join('')}
                <p class="muted small" style="margin-top: 10px;">ファイルパス: /Users/hirotomookawasaki/stock_swing/data/audits/</p>
            </div>
        </div>
        
        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>📝 監査ログ (${parsedLogs.length}件)</h3>
                ${this.renderLogsTable(parsedLogs)}
            </div>
        </div>`;
    }

    renderMetrics() {
        // Phase 3 パフォーマンスダッシュボード
        let html = '<div class="grid">';
        
        // パフォーマンスサマリー
        if (typeof performanceMonitor !== 'undefined') {
            const perfSummary = performanceMonitor.getSummary();
            
            html += `
                <div class="card">
                    <h3>⚡ パフォーマンスサマリー</h3>
                    <div class="metrics-grid">
                        <div class="metric">
                            <span class="label">ページロード</span>
                            <span class="value">${perfSummary.pageLoad.avg || 0}ms</span>
                            <span class="detail">p95: ${perfSummary.pageLoad.p95 || 0}ms</span>
                        </div>
                        <div class="metric">
                            <span class="label">API呼び出し</span>
                            <span class="value">${perfSummary.apiCalls.avg || 0}ms</span>
                            <span class="detail">p95: ${perfSummary.apiCalls.p95 || 0}ms</span>
                        </div>
                        <div class="metric">
                            <span class="label">レンダリング</span>
                            <span class="value">${perfSummary.renders.avg || 0}ms</span>
                            <span class="detail">p95: ${perfSummary.renders.p95 || 0}ms</span>
                        </div>
                        <div class="metric">
                            <span class="label">API成功率</span>
                            <span class="value success">${(perfSummary.apiSuccessRate * 100).toFixed(2)}%</span>
                            <span class="detail">${perfSummary.apiCalls.count} calls</span>
                        </div>
                    </div>
                </div>
            `;
        } else {
            html += `<div class="card"><p class="muted">パフォーマンスモニター未初期化</p></div>`;
        }
        
        // エラーサマリー
        if (typeof errorTracker !== 'undefined') {
            const errorStats = errorTracker.getStats(3600000);
            const errorStatusClass = errorStats.total === 0 ? 'success' : 
                                     errorStats.total < 5 ? 'warn' : 'danger';
            
            html += `
                <div class="card">
                    <h3>🚨 エラーサマリー（過去1時間）</h3>
                    <div class="metrics-grid">
                        <div class="metric">
                            <span class="label">総エラー数</span>
                            <span class="value ${errorStatusClass}">${errorStats.total}</span>
                        </div>
                        <div class="metric">
                            <span class="label">エラー率</span>
                            <span class="value ${errorStatusClass}">${(errorStats.errorRate * 100).toFixed(2)}%</span>
                        </div>
                    </div>
            `;
            
            if (Object.keys(errorStats.byType).length > 0) {
                html += `<h4>エラー種別:</h4><div class="metrics-grid">`;
                Object.entries(errorStats.byType)
                    .sort((a, b) => b[1] - a[1])
                    .forEach(([type, count]) => {
                        html += `
                            <div class="metric">
                                <span class="label">${this.escapeHtml(type)}</span>
                                <span class="value">${count}</span>
                            </div>
                        `;
                    });
                html += `</div>`;
            }
            
            html += `</div>`;
        } else {
            html += `<div class="card"><p class="muted">エラートラッカー未初期化</p></div>`;
        }
        
        // ヘルスサマリー
        if (typeof healthMonitor !== 'undefined') {
            const healthSummary = healthMonitor.getSummary();
            const healthStatusClass = healthSummary.overall === 'healthy' ? 'success' : 
                                      healthSummary.overall === 'warning' ? 'warn' : 'danger';
            const healthIcon = healthSummary.overall === 'healthy' ? '✅' : 
                              healthSummary.overall === 'warning' ? '⚠️' : '❌';
            
            html += `
                <div class="card">
                    <h3>🏥 ヘルスサマリー</h3>
                    <div class="metric">
                        <span class="label">全体ステータス</span>
                        <span class="value ${healthStatusClass}">${healthIcon} ${healthSummary.overall}</span>
                    </div>
                    <h4>ヘルスチェック:</h4>
                    <div class="metrics-grid">
            `;
            
            Object.entries(healthSummary.checks).forEach(([name, check]) => {
                const checkIcon = check.status === 'healthy' ? '✅' : 
                                 check.status === 'warning' ? '⚠️' : 
                                 check.status === 'error' ? '❌' : '⏸️';
                const checkClass = check.status === 'healthy' ? 'success' : 
                                  check.status === 'warning' ? 'warn' : 
                                  check.status === 'error' ? 'danger' : 'muted';
                
                html += `
                    <div class="metric">
                        <span class="label">${checkIcon} ${this.escapeHtml(name)}</span>
                        <span class="value ${checkClass}">${check.status}</span>
                    </div>
                `;
            });
            
            html += `</div></div>`;
        } else {
            html += `<div class="card"><p class="muted">ヘルスモニター未初期化</p></div>`;
        }
        
        // リカバリーサマリー
        if (typeof recoveryManager !== 'undefined') {
            const recoveryStats = recoveryManager.getStats(3600000);
            const successRate = recoveryStats.successRate || 0;
            const successClass = successRate >= 0.8 ? 'success' : 
                                successRate >= 0.5 ? 'warn' : 'danger';
            
            html += `
                <div class="card">
                    <h3>🔧 リカバリーサマリー（過去1時間）</h3>
                    <div class="metrics-grid">
                        <div class="metric">
                            <span class="label">総リカバリー数</span>
                            <span class="value">${recoveryStats.total}</span>
                        </div>
                        <div class="metric">
                            <span class="label">成功率</span>
                            <span class="value ${successClass}">${(successRate * 100).toFixed(2)}%</span>
                        </div>
                        <div class="metric">
                            <span class="label">キャッシュエントリ</span>
                            <span class="value">${recoveryManager.cache.size}</span>
                        </div>
                    </div>
            `;
            
            if (Object.keys(recoveryStats.byType).length > 0) {
                html += `<h4>リカバリー種別:</h4><div class="metrics-grid">`;
                Object.entries(recoveryStats.byType)
                    .sort((a, b) => b[1] - a[1])
                    .forEach(([type, count]) => {
                        html += `
                            <div class="metric">
                                <span class="label">${this.escapeHtml(type)}</span>
                                <span class="value">${count}</span>
                            </div>
                        `;
                    });
                html += `</div>`;
            }
            
            html += `</div>`;
        } else {
            html += `<div class="card"><p class="muted">リカバリーマネージャー未初期化</p></div>`;
        }
        
        // 週次レポート
        if (typeof reportGenerator !== 'undefined') {
            const latestReport = reportGenerator.getLatestReport();
            
            html += `
                <div class="card full-width">
                    <h3>📊 週次レポート</h3>
            `;
            
            if (latestReport) {
                const scoreColor = latestReport.overallScore >= 80 ? 'success' : 
                                  latestReport.overallScore >= 60 ? 'warn' : 'danger';
                
                html += `
                    <div class="metric">
                        <span class="label">最新レポート</span>
                        <span class="value">${latestReport.period.label}</span>
                    </div>
                    <div class="metric">
                        <span class="label">総合スコア</span>
                        <span class="value ${scoreColor}">${latestReport.overallScore}/100</span>
                    </div>
                    <button onclick="showLatestReport()" class="btn-primary">レポート詳細を表示</button>
                `;
            } else {
                html += `
                    <p class="muted">レポートがまだ生成されていません</p>
                    <button onclick="generateWeeklyReportNow()" class="btn-primary">今すぐレポートを生成</button>
                `;
            }
            
            html += `</div>`;
        }
        
        html += '</div>';
        
        return html;
    }

    parseLogLine(line) {
        if (!line || typeof line !== 'string') return null;
        const parts = line.split(' | ');
        if (parts.length < 4) return null;
        
        return {
            timestamp: parts[0],
            level: parts[1],
            category: parts[2],
            action: parts[3],
            source: parts[4] || '-',
            id: parts[5] || '-',
            message: parts.slice(6).join(' | ')
        };
    }

    renderLogsTable(data) {
        if (!data || data.length === 0) return '<p class="muted">ログエントリなし</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>時刻</th><th>レベル</th><th>カテゴリ</th><th>アクション</th><th>ソース</th><th>メッセージ</th>
        </tr></thead><tbody>
        ${data.map(log => {
            const levelClass = log.level === 'ERROR' ? 'danger' : log.level === 'WARNING' ? 'warn' : 'success';
            return `
            <tr>
                <td class="small">${new Date(log.timestamp).toLocaleString('ja-JP', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'})}</td>
                <td><span class="badge badge-${levelClass}">${this.escapeHtml(log.level)}</span></td>
                <td class="small">${this.escapeHtml(log.category)}</td>
                <td class="small">${this.escapeHtml(log.action)}</td>
                <td class="small">${this.escapeHtml(log.source)}</td>
                <td class="small">${this.escapeHtml(log.message)}</td>
            </tr>`;
        }).join('')}
        </tbody></table></div>`;
    }

    renderWeekly() {
        const charts = this.data?.charts?.overview || {};
        const trading = this.data?.trading || {};
        const summary = trading.summary || {};
        const dailySnapshots = trading.daily_snapshots || [];
        const recentTrades = trading.recent_trades || [];
        
        // 前週比計算（仮のデータ、実際はAPIから取得）
        const equityData = charts.equity || [];
        const currentEquity = equityData[equityData.length - 1]?.value || 0;
        const prevEquity = equityData[equityData.length - 8]?.value || currentEquity;
        const equityChange = currentEquity - prevEquity;
        const equityChangePct = prevEquity > 0 ? (equityChange / prevEquity) : 0;
        
        return `
        <div class="grid">
            <div class="card">
                <h3>💰 週次Equity</h3>
                <div class="metric big-metric">
                    <span class="value huge ${equityChangePct >= 0 ? 'success' : 'danger'}">${fmt.usd(currentEquity)}</span>
                </div>
                <div class="metric">
                    <span class="label">前週比</span>
                    <span class="value ${equityChangePct >= 0 ? 'success' : 'danger'}">
                        ${equityChangePct >= 0 ? '↑' : '↓'} ${fmt.usdSigned(equityChange)} (${fmt.pctSigned(equityChangePct)})
                    </span>
                </div>
            </div>
            <div class="card">
                <h3>📊 取引サマリー</h3>
                <div class="metric"><span class="label">総取引数</span><span class="value">${summary.total_trades || 0}</span></div>
                <div class="metric"><span class="label">勝率</span><span class="value ${summary.win_rate >= 0.6 ? 'success' : 'warn'}">${fmt.pct(summary.win_rate || 0)}</span></div>
                <div class="metric"><span class="label">平均リターン</span><span class="value ${summary.avg_return_per_trade >= 0 ? 'success' : 'danger'}">${fmt.pctSigned(summary.avg_return_per_trade || 0)}</span></div>
                <div class="metric"><span class="label">累積実現PnL</span><span class="value ${summary.cumulative_realized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(summary.cumulative_realized_pnl || 0)}</span></div>
            </div>
            <div class="card">
                <h3>⚠️ リスク指標</h3>
                <div class="metric"><span class="label">最大Drawdown</span><span class="value danger">${fmt.pct(summary.max_drawdown_pct || 0)}</span></div>
                <div class="metric"><span class="label">Peak Equity</span><span class="value">${fmt.usd(summary.peak_equity || 0)}</span></div>
                <div class="metric"><span class="label">取引日数</span><span class="value">${summary.trading_days || 0}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">勝率</div>
                    <div class="progress-bar">
                        <div class="progress-fill success" style="width: ${(summary.win_rate || 0) * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(summary.win_rate || 0)}</div>
                </div>
            </div>
        </div>
        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                    <h3 style="margin:0">📈 Equity推移</h3>
                    <div class="chart-period-selector">
                        ${['week','month','all'].map(p =>
                            `<button class="chart-period-btn weekly-period-btn${this._weeklyChartPeriod === p ? ' active' : ''}" data-period="${p}">${{week:'1W', month:'1M', all:'ALL'}[p]}</button>`
                        ).join('')}
                    </div>
                </div>
                <canvas id="weeklyEquityChart" height="80"></canvas>
            </div>
        </div>
        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>📋 最近の取引</h3>
                ${this.renderRecentTrades(recentTrades.slice(0, 10))}
            </div>
        </div>`;
    }

    renderAnalysis() {
        const perf = this.data?.performance || {};
        const alpha = perf.alpha || {};
        const beta = perf.beta || {};
        const sharpe = perf.sharpe || {};

        const alphaAvailable = alpha.available !== false;
        const betaAvailable = beta.available !== false;
        const sharpeAvailable = sharpe.available !== false;

        // Alphaの色分け
        const alphaValue = alpha.alpha || 0;
        const alphaClass = !alphaAvailable ? 'unknown' : alphaValue > 2 ? 'success' : alphaValue > 0 ? 'warn' : 'danger';
        const alphaIcon = !alphaAvailable ? '⏸️' : alphaValue > 0 ? '🚀' : '🐢';

        // Betaの色分け
        const betaValue = beta.beta || 0;
        const betaClass = !betaAvailable ? 'unknown' : betaValue < 0.5 ? 'success' : betaValue < 1 ? 'warn' : 'danger';
        const betaIcon = !betaAvailable ? '⏸️' : betaValue < 0.5 ? '🛡️' : betaValue < 1 ? '⚠️' : '🔥';

        // Sharpeの色分け
        const sharpeValue = sharpe.sharpe_ratio || 0;
        const sharpeClass = !sharpeAvailable ? 'unknown' : sharpeValue > 2 ? 'success' : sharpeValue > 1 ? 'warn' : 'danger';
        const sharpeIcon = !sharpeAvailable ? '⏸️' : sharpeValue > 2 ? '⭐' : sharpeValue > 1 ? '🟡' : '🔴';
        const periodInfo = alpha.period?.start && alpha.period?.end
            ? `${alpha.period.start} → ${alpha.period.end} (${alpha.period.days || 0}点)`
            : `${this.getPeriodLabel(perf.period_filter || this.currentPeriod)} / snapshots=${perf.snapshot_count || 0}`;
        const strategyAttribution = perf.by_strategy || [];

        // 全期間サマリー
        const fp = perf.full_period;
        const fpHtml = fp ? (() => {
            const fpAlpha = fp.alpha ?? null;
            const fpPf = fp.portfolio_return_pct ?? null;
            const fpBm = fp.benchmark_return_pct ?? null;
            const fpSharpe = fp.sharpe ?? null;
            const fpClass = fpAlpha == null ? 'unknown' : fpAlpha > 0 ? 'success' : 'danger';
            return `<div class="card" style="margin-bottom:16px;border-left:4px solid #6366f1">
                <h4 style="margin:0 0 8px">📅 全期間サマリー（${fp.start || '?'} → ${fp.end || '?'} / ${fp.days || '?'}日）</h4>
                <div style="display:flex;gap:24px;flex-wrap:wrap">
                    <div class="metric" style="margin:0"><span class="label">Portfolio</span><span class="value ${fpPf >= 0 ? 'success' : 'danger'}">${fpPf != null ? (fpPf >= 0 ? '+' : '') + fpPf.toFixed(2) + '%' : '—'}</span></div>
                    <div class="metric" style="margin:0"><span class="label">SPY</span><span class="value">${fpBm != null ? (fpBm >= 0 ? '+' : '') + fpBm.toFixed(2) + '%' : '—'}</span></div>
                    <div class="metric" style="margin:0"><span class="label">Alpha</span><span class="value ${fpClass}">${fpAlpha != null ? (fpAlpha >= 0 ? '+' : '') + fpAlpha.toFixed(2) + '%' : '—'}</span></div>
                    <div class="metric" style="margin:0"><span class="label">Sharpe</span><span class="value">${fpSharpe != null ? fpSharpe.toFixed(2) : '—'}</span></div>
                </div>
            </div>`;
        })() : '';

        return `
        ${this.renderPeriodSelector()}
        ${fpHtml}
        <div class="card" style="margin-bottom: 16px;">
            <div class="metric"><span class="label">分析対象期間</span><span class="value">${this.escapeHtml(periodInfo)}</span></div>
        </div>
        <div class="grid">
            <div class="card performance-card ${alphaClass}-border">
                <h3>${alphaIcon} α (Alpha) - 超過リターン</h3>
                <div class="metric big-metric">
                    <span class="value huge ${alphaClass}">${alphaAvailable ? fmt.pctSigned(alphaValue / 100) : 'N/A'}</span>
                </div>
                <div class="metric"><span class="label">ポートフォリオ</span><span class="value success">${alphaAvailable ? fmt.pct((alpha.portfolio?.return_pct || 0) / 100) : '—'}</span></div>
                <div class="metric"><span class="label">ベンチマーク (${alpha.benchmark?.symbol || 'SPY'})</span><span class="value">${alphaAvailable ? fmt.pct((alpha.benchmark?.return_pct || 0) / 100) : '—'}</span></div>
                <div class="interpretation-box ${alphaClass}">
                    <strong>${alphaAvailable ? '評価' : '状態'}:</strong> ${this.escapeHtml(alphaAvailable ? (alpha.interpretation || '') : (alpha.error || 'データ不足'))}
                </div>
                <div class="progress-bar-container">
                    <div class="progress-label">アルファ貢献度</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${alphaClass}" style="width: ${alphaAvailable ? Math.min(Math.abs(alphaValue) * 10, 100) : 0}%"></div>
                    </div>
                </div>
            </div>
            
            <div class="card performance-card ${betaClass}-border">
                <h3>${betaIcon} β (Beta) - 市場連動性</h3>
                <div class="metric big-metric">
                    <span class="value huge ${betaClass}">${betaAvailable ? betaValue.toFixed(2) : 'N/A'}</span>
                </div>
                <div class="metric"><span class="label">R² (決定係数)</span><span class="value">${betaAvailable ? (beta.r_squared || 0).toFixed(3) : '—'}</span></div>
                <div class="metric"><span class="label">相関係数</span><span class="value">${betaAvailable ? (beta.correlation || 0).toFixed(3) : '—'}</span></div>
                <div class="interpretation-box ${betaClass}">
                    <strong>${betaAvailable ? '評価' : '状態'}:</strong> ${this.escapeHtml(betaAvailable ? (beta.interpretation || '') : (beta.error || 'データ不足'))}
                </div>
                <div class="progress-bar-container">
                    <div class="progress-label">市場連動度</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${betaClass}" style="width: ${betaAvailable ? Math.min(betaValue * 100, 100) : 0}%"></div>
                    </div>
                </div>
            </div>
            
            <div class="card performance-card ${sharpeClass}-border">
                <h3>${sharpeIcon} Sharpe Ratio - リスク調整後リターン</h3>
                <div class="metric big-metric">
                    <span class="value huge ${sharpeClass}">${sharpeAvailable ? sharpeValue.toFixed(2) : 'N/A'}</span>
                </div>
                <div class="metric"><span class="label">年間リターン</span><span class="value success">${sharpeAvailable ? fmt.pct((sharpe.annual_return_pct || 0) / 100) : '—'}</span></div>
                <div class="metric"><span class="label">年間ボラティリティ</span><span class="value danger">${sharpeAvailable ? fmt.pct((sharpe.annual_volatility_pct || 0) / 100) : '—'}</span></div>
                <div class="interpretation-box ${sharpeClass}">
                    <strong>${sharpeAvailable ? '評価' : '状態'}:</strong> ${this.escapeHtml(sharpeAvailable ? (sharpe.interpretation || '') : (sharpe.error || 'データ不足'))}
                </div>
                <div class="progress-bar-container">
                    <div class="progress-label">シャープ質</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${sharpeClass}" style="width: ${sharpeAvailable ? Math.min(sharpeValue * 50, 100) : 0}%"></div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="grid" style="margin-top: 16px;">
            <div class="card summary-card" style="grid-column: 1 / -1;">
                <h3>📊 総合評価</h3>
                <p class="summary-text">${this.escapeHtml(perf.summary || '')}</p>
            </div>
        </div>
        
        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>🎯 リスク・リターン比較</h3>
                <canvas id="riskReturnChart" height="100"></canvas>
            </div>
        </div>

        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>🧪 戦略別 α/β/Sharpe（近似）</h3>
                <p class="muted small">closed trades の日次 realized return から作る近似値です。戦略別の日次 equity snapshot が無いため、参考値として扱ってください。</p>
                ${this.renderStrategyAttributionTable(strategyAttribution)}
            </div>
        </div>`;
    }

    renderStrategyAttributionTable(data) {
        if (!data || data.length === 0) return '<p class="muted">戦略別 attribution はまだ計算できるデータがありません</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>strategy_version_id</th><th>決済取引</th><th>稼働日</th><th>勝/負</th><th>実現PnL</th><th>α</th><th>β</th><th>Sharpe</th><th>メモ</th>
        </tr></thead><tbody>
        ${data.map(row => {
            const alphaTxt = row.alpha?.available !== false ? fmt.pctSigned((row.alpha?.alpha || 0) / 100) : 'N/A';
            const betaTxt = row.beta?.available !== false ? (row.beta?.beta || 0).toFixed(2) : 'N/A';
            const sharpeTxt = row.sharpe?.available !== false ? (row.sharpe?.sharpe_ratio || 0).toFixed(2) : 'N/A';
            const alphaCls = row.alpha?.available !== false ? ((row.alpha?.alpha || 0) >= 0 ? 'success' : 'danger') : 'muted';
            const pnlCls = (row.realized_pnl || 0) >= 0 ? 'success' : 'danger';
            const memo = row.summary || row.alpha?.error || row.beta?.error || row.sharpe?.error || row.approximation || '';
            return `<tr>
                <td class="small">${this.formatStrategyLabel(row.strategy_version_id || '')}</td>
                <td>${row.closed_trades || 0}</td>
                <td>${row.active_days || 0}</td>
                <td>${row.winning_trades || 0} / ${row.losing_trades || 0}</td>
                <td class="${pnlCls}">${fmt.usdSigned(row.realized_pnl || 0)}</td>
                <td class="${alphaCls}">${alphaTxt}</td>
                <td>${betaTxt}</td>
                <td>${sharpeTxt}</td>
                <td class="small muted">${this.escapeHtml(memo)}</td>
            </tr>`;
        }).join('')}
        </tbody></table></div>`;
    }

    renderCharts() {
        const charts = this.data?.charts?.overview || {};
        const periodBtns = ['week','month','all'].map(p =>
            `<button class="chart-period-btn${this._equityChartPeriod === p ? ' active' : ''}" data-period="${p}">${{week:'1W', month:'1M', all:'ALL'}[p]}</button>`
        ).join('');
        return `
        ${this.renderPeriodSelector()}
        <div class="grid" style="margin-bottom: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                    <h3 style="margin:0">💰 Equity推移</h3>
                    <div class="chart-period-selector">${periodBtns}</div>
                </div>
                <canvas id="equityChart" height="80"></canvas>
            </div>
        </div>
        
        <div class="grid" style="margin-bottom: 16px;">
            <div class="card" style="grid-column: 1 / 3;">
                <h3>📉 Drawdown推移</h3>
                <canvas id="drawdownChart" height="80"></canvas>
            </div>
            <div class="card" style="grid-column: 3 / -1;">
                <h3>📊 Open Positions推移</h3>
                <canvas id="positionsChart" height="80"></canvas>
            </div>
        </div>
        
        <div class="grid" style="margin-bottom: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>📡 Signals & Orders推移</h3>
                <canvas id="signalsOrdersChart" height="80"></canvas>
            </div>
        </div>
        
        <div class="grid">
            <div class="card" style="grid-column: 1 / 3;">
                <h3>🎯 取引回数推移</h3>
                <canvas id="tradeCountChart" height="80"></canvas>
            </div>
            <div class="card" style="grid-column: 3 / -1;">
                <h3>🏆 勝率推移</h3>
                <canvas id="winRateChart" height="80"></canvas>
            </div>
        </div>`;
    }

    renderPeriodSelector() {
        const periods = [
            ['day', '1D'],
            ['3days', '3D'],
            ['week', '1W'],
            ['month', '1M'],
            ['all', 'ALL'],
        ];
        return `<div class="period-selector" style="margin-bottom: 16px;">
            ${periods.map(([key, label]) => `<button class="period-btn ${this.currentPeriod === key ? 'active' : ''}" data-period="${key}">${label}</button>`).join('')}
        </div>`;
    }

    getPeriodLabel(period) {
        const labels = { day: '1日', '3days': '3日', week: '1週間', month: '1か月', all: '全期間' };
        return labels[period] || period || '—';
    }

    setupPeriodSelectors() {
        document.querySelectorAll('.period-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const nextPeriod = btn.dataset.period || 'month';
                if (nextPeriod === this.currentPeriod) return;
                this.currentPeriod = nextPeriod;
                localStorage.setItem('dashboardPeriod', nextPeriod);
                await this.loadData();
                this.render();
            });
        });
    }

    _filterEquityByPeriod(equityData, period) {
        if (!equityData || equityData.length === 0) return equityData;
        const periodDays = { week: 7, month: 30, all: Infinity }[period] || 30;
        if (periodDays === Infinity) return equityData;
        return equityData.slice(-periodDays);
    }

    _setupChartPeriodBtns(selector, storageKey, stateKey, redrawFn) {
        document.querySelectorAll(selector).forEach(btn => {
            btn.addEventListener('click', () => {
                const p = btn.dataset.period;
                if (!p || this[stateKey] === p) return;
                this[stateKey] = p;
                localStorage.setItem(storageKey, p);
                document.querySelectorAll(selector).forEach(b =>
                    b.classList.toggle('active', b.dataset.period === p));
                redrawFn(p);
            });
        });
    }

    renderNews() {
        const news = this.data.news || {};
        const newsArr = news.items || [];
        const summary = news.summary || {};
        
        // 判断に使用されたニュースを分析
        const usedInDecision = newsArr.filter(n => n.used_in_decision);
        const sentimentBreakdown = {
            positive: newsArr.filter(n => n.sentiment_label === 'positive').length,
            negative: newsArr.filter(n => n.sentiment_label === 'negative').length,
            neutral: newsArr.filter(n => n.sentiment_label === 'neutral').length
        };
        const impactBreakdown = {
            high: newsArr.filter(n => n.impact_label === 'high').length,
            medium: newsArr.filter(n => n.impact_label === 'medium').length,
            low: newsArr.filter(n => n.impact_label === 'low').length,
            critical: newsArr.filter(n => n.impact_label === 'critical').length
        };
        const categoryBreakdown = {};
        newsArr.forEach(n => {
            const cat = n.category || 'other';
            categoryBreakdown[cat] = (categoryBreakdown[cat] || 0) + 1;
        });
        
        return `<div class="grid">
            <div class="card performance-card success-border">
                <h3>📰 ニュース概要</h3>
                <div class="metric"><span class="label">総記事数 (24h)</span><span class="value">${summary.total_24h || 0}</span></div>
                <div class="metric"><span class="label">判断に使用</span><span class="value success">${summary.decision_referenced || 0}</span></div>
                <div class="metric"><span class="label">追跡シンボル</span><span class="value">${summary.symbols_covered || 0}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">判断使用率</div>
                    <div class="progress-bar">
                        <div class="progress-fill success" style="width: ${(summary.decision_referenced || 0) / (summary.total_24h || 1) * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct((summary.decision_referenced || 0) / (summary.total_24h || 1))}</div>
                </div>
            </div>
            
            <div class="card">
                <h3>📊 センチメント分布</h3>
                <div class="metric"><span class="label">ポジティブ</span><span class="value success">${sentimentBreakdown.positive}</span></div>
                <div class="metric"><span class="label">ネガティブ</span><span class="value danger">${sentimentBreakdown.negative}</span></div>
                <div class="metric"><span class="label">中立</span><span class="value muted">${sentimentBreakdown.neutral}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">ポジティブ比率</div>
                    <div class="progress-bar">
                        <div class="progress-fill success" style="width: ${(sentimentBreakdown.positive / (summary.total_24h || 1)) * 100}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(sentimentBreakdown.positive / (summary.total_24h || 1))}</div>
                </div>
            </div>
            
            <div class="card">
                <h3>⚡ インパクト分布</h3>
                <div class="metric"><span class="label">クリティカル</span><span class="value danger">${impactBreakdown.critical || 0}</span></div>
                <div class="metric"><span class="label">高</span><span class="value warn">${impactBreakdown.high || 0}</span></div>
                <div class="metric"><span class="label">中</span><span class="value">${impactBreakdown.medium || 0}</span></div>
                <div class="metric"><span class="label">低</span><span class="value muted">${impactBreakdown.low || 0}</span></div>
            </div>
            
            <div class="card">
                <h3>📝 カテゴリ分布</h3>
                ${Object.entries(categoryBreakdown).sort((a, b) => b[1] - a[1]).map(([cat, count]) => 
                    `<div class="metric"><span class="label">${this.escapeHtml(cat)}</span><span class="value">${count}</span></div>`
                ).join('')}
            </div>
        </div>
        
        <div class="grid" style="margin-top: 16px;">
            <div class="card" style="grid-column: 1 / -1;">
                <h3>📋 ニュース記事 (${newsArr.length}件)</h3>
                ${this.renderNewsTable(newsArr)}
            </div>
        </div>`;
    }

    renderNewsTable(data) {
        if (!data || data.length === 0) return '<p class="muted">ニュースなし</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>日付</th><th>シンボル</th><th>タイトル</th><th>センチメント</th><th>インパクト</th><th>概要</th>
        </tr></thead><tbody>
        ${data.map(item => `
            <tr>
                <td>${fmt.dt(item.published_at)}</td>
                <td><strong>${this.escapeHtml(item.symbol)}</strong></td>
                <td><a href="${this.escapeHtml(item.url)}" target="_blank">${this.escapeHtml(item.headline_ja || item.headline)}</a></td>
                <td><span class="badge badge-${item.sentiment_label === 'positive' ? 'success' : item.sentiment_label === 'negative' ? 'danger' : 'unknown'}">${this.escapeHtml(item.sentiment_label_ja || item.sentiment_label)}</span></td>
                <td><span class="badge badge-${item.impact_label === 'high' ? 'warn' : 'unknown'}">${this.escapeHtml(item.impact_label_ja || item.impact_label)}</span></td>
                <td class="small muted">${this.escapeHtml(item.summary_ja || item.snippet || '').substring(0, 100)}...</td>
            </tr>`).join('')}
        </tbody></table></div>`;
    }

    escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') return '—';
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    renderDelta(value, type) {
        if (!value) return '';
        switch (type) {
            case 'usd':
                return `<div class="metric"><span class="label">vs. Previous</span><span class="value small ${value >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(value)}</span></div>`;
            case 'count':
                return `<div class="metric"><span class="label">vs. Previous</span><span class="value small ${value >= 0 ? 'success' : 'danger'}">${value}</span></div>`;
            default:
                return '';
        }
    }

    initOverviewCharts() {
        setTimeout(() => {
            const charts = this.data?.charts?.overview || {};
            
            // Equity Chart with adjusted y-axis
            this.createAdaptiveChart('overviewEquityChart', charts.equity || [], 'Equity', '#10b981', (v) => fmt.usd(v));
            
            // Drawdown Chart with adjusted y-axis
            this.createAdaptiveChart('overviewDrawdownChart', charts.drawdown_pct || [], 'Drawdown', '#ef4444', (v) => fmt.pct(v), true);
            
            // Positions Chart with adjusted y-axis
            this.createAdaptiveChart('overviewPositionsChart', charts.open_positions || [], 'Open Positions', '#3b82f6', (v) => v.toFixed(0));
            
            // Signals & Orders Chart
            const signalsOrders = charts.signals_orders || [];
            const ctx = document.getElementById('overviewSignalsChart');
            if (ctx && signalsOrders.length > 0) {
                new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: signalsOrders.map(d => new Date(d.date).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'})),
                        datasets: [
                            {
                                label: 'Signals',
                                data: signalsOrders.map(d => d.signals || d.signals_value || 0),
                                backgroundColor: '#60a5fa',
                                borderRadius: 4
                            },
                            {
                                label: 'Orders',
                                data: signalsOrders.map(d => d.orders || d.orders_value || 0),
                                backgroundColor: '#34d399',
                                borderRadius: 4
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        plugins: { 
                            legend: { display: true, position: 'top' },
                            tooltip: {
                                callbacks: {
                                    label: (context) => `${context.dataset.label}: ${context.parsed.y}`
                                }
                            }
                        },
                        scales: { 
                            y: { 
                                beginAtZero: true,
                                ticks: {
                                    stepSize: 1
                                }
                            } 
                        }
                    }
                });
            }
        }, 100);
    }

    createAdaptiveChart(canvasId, data, label, color, formatter, isNegative = false) {
        const ctx = document.getElementById(canvasId);
        if (!ctx || data.length === 0) return;
        
        const values = data.map(d => d.value || 0);
        const minValue = Math.min(...values);
        const maxValue = Math.max(...values);
        const range = maxValue - minValue;
        
        // 変化が小さい場合はy軸の範囲を狭くする
        const padding = range * 0.1; // 10%の余白
        const suggestedMin = Math.max(minValue - padding, isNegative ? minValue - padding : 0);
        const suggestedMax = maxValue + padding;
        
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => new Date(d.date).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'})),
                datasets: [{
                    label: label,
                    data: values,
                    borderColor: color,
                    backgroundColor: color + '30',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${label}: ${formatter(context.parsed.y)}`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        suggestedMin: suggestedMin,
                        suggestedMax: suggestedMax,
                        ticks: {
                            callback: (value) => formatter(value)
                        },
                        grid: {
                            color: 'rgba(255, 255, 255, 0.1)'
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        }
                    }
                }
            }
        });
    }

    initWeeklyCharts() {
        const drawWeeklyEquity = async (period) => {
            const charts = this.data?.charts?.overview || {};
            const allEquity = charts.equity || [];
            const equityData = this._filterEquityByPeriod(allEquity, period);
            const ctx = document.getElementById('weeklyEquityChart');
            if (!ctx) return;
            if (ctx._chartInstance) { ctx._chartInstance.destroy(); ctx._chartInstance = null; }

            // Fetch normalized benchmark data
            let bmData = {};
            try {
                const res = await fetch('/api/benchmark/normalized?symbols=SPY,QQQ');
                const json = await res.json();
                if (json.available) bmData = json.benchmarks || {};
            } catch (e) { /* ignore */ }

            // Normalize date keys to YYYY-MM-DD (equity ts may be ISO datetime like '2026-06-30T00:00:00')
            const dateKeys = equityData.map(d => (d.date || '').slice(0, 10));
            const labels = dateKeys.map(d => new Date(d + 'T00:00:00').toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'}));

            const datasets = [
                {
                    label: 'Equity',
                    data: equityData.map(d => d.value),
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    order: 0
                }
            ];

            const bmColors = { SPY: { line: '#6366f1', bg: 'rgba(99,102,241,0)' }, QQQ: { line: '#f59e0b', bg: 'rgba(245,158,11,0)' } };
            const bmLabels = { SPY: 'SPY（S&P500）', QQQ: 'QQQ（NASDAQ100）' };
            for (const [sym, series] of Object.entries(bmData)) {
                const seriesMap = Object.fromEntries(series.map(s => [s.date.slice(0, 10), s.value]));
                const color = bmColors[sym] || { line: '#9ca3af', bg: 'rgba(156,163,175,0)' };
                datasets.push({
                    label: bmLabels[sym] || sym,
                    data: dateKeys.map(d => seriesMap[d] ?? null),
                    borderColor: color.line,
                    backgroundColor: color.bg,
                    fill: false,
                    tension: 0.4,
                    borderWidth: 1.5,
                    borderDash: [4, 3],
                    pointRadius: 0,
                    spanGaps: true,
                    order: 1
                });
            }

            new Chart(ctx, {
                type: 'line',
                data: { labels, datasets },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: Object.keys(bmData).length > 0 },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.dataset.label}: ${fmt.usd(context.parsed.y)}`
                            }
                        }
                    },
                    scales: {
                        y: { ticks: { callback: (value) => fmt.usd(value) } }
                    }
                }
            });
        };
        setTimeout(async () => {
            await drawWeeklyEquity(this._weeklyChartPeriod);
            this._setupChartPeriodBtns(
                '.weekly-period-btn', 'weeklyChartPeriod', '_weeklyChartPeriod',
                (p) => drawWeeklyEquity(p)
            );
        }, 100);
    }

    initAnalysisCharts() {
        setTimeout(async () => {
            const perf = this.data?.performance || {};
            const sharpe = perf.sharpe || {};
            const alpha = perf.alpha || {};

            const ctx = document.getElementById('riskReturnChart');
            if (!ctx) return;

            // Portfolio point: use actual data_points for annualization
            // annual_return_pct from Sharpe calc may be distorted if data is short.
            // Show raw period return + annualized vol instead.
            const periodDays = alpha.period?.days || sharpe.data_points || 1;
            const portfolioReturnPct = alpha.portfolio?.return_pct ?? (sharpe.annual_return_pct / 252 * periodDays);
            // Annualized vol is reliable; use it
            const portfolioVolPct = sharpe.annual_volatility_pct || 0;

            // Benchmark: calculate annualized vol + period return for SPY and QQQ
            const bmPoints = {};
            try {
                const res = await fetch('/api/benchmark/normalized?symbols=SPY,QQQ');
                const bm = await res.json();
                for (const [sym, series] of Object.entries(bm.benchmarks || {})) {
                    if (series.length < 3) continue;
                    const vals = series.map(s => s.value);
                    const dailyReturns = vals.slice(1).map((v, i) => (v - vals[i]) / vals[i]);
                    const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
                    const variance = dailyReturns.reduce((a, r) => a + (r - mean) ** 2, 0) / dailyReturns.length;
                    const annualVol = Math.sqrt(variance * 252) * 100;
                    const periodReturn = (vals[vals.length - 1] - vals[0]) / vals[0] * 100;
                    bmPoints[sym] = { vol: annualVol, ret: periodReturn };
                }
            } catch (e) { /* use fallback */ }

            const bmConfig = {
                SPY: { label: 'SPY（S&P500）',  color: '#6366f1' },
                QQQ: { label: 'QQQ（NASDAQ100）', color: '#f59e0b' },
            };

            const bmDatasets = Object.entries(bmPoints).map(([sym, pt]) => ({
                label: bmConfig[sym]?.label || sym,
                data: [{ x: pt.vol, y: pt.ret }],
                backgroundColor: bmConfig[sym]?.color || '#9ca3af',
                pointRadius: 10,
                pointHoverRadius: 12
            }));

            new Chart(ctx, {
                type: 'scatter',
                data: {
                    datasets: [{
                        label: 'ポートフォリオ',
                        data: [{ x: portfolioVolPct, y: portfolioReturnPct }],
                        backgroundColor: '#10b981',
                        pointRadius: 12,
                        pointHoverRadius: 14
                    }, ...bmDatasets]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: true },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    const r = context.parsed.y;
                                    const v = context.parsed.x;
                                    return `${context.dataset.label}:  リターン ${r >= 0 ? '+' : ''}${r.toFixed(1)}%  ボラ ${v.toFixed(1)}%`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            title: { display: true, text: `リスク（年率ボラティリティ）` },
                            ticks: { callback: (v) => v.toFixed(0) + '%' }
                        },
                        y: {
                            title: { display: true, text: `リターン（期間: ${periodDays}日）` },
                            ticks: { callback: (v) => v.toFixed(0) + '%' }
                        }
                    }
                }
            });
        }, 100);
    }

    initAllCharts() {
        const drawEquityChart = async (period) => {
            const charts = this.data?.charts?.overview || {};
            const allEquity = charts.equity || [];
            const equityData = this._filterEquityByPeriod(allEquity, period);
            const equityCtx = document.getElementById('equityChart');
            if (!equityCtx || equityData.length === 0) return;
            if (equityCtx._chartInstance) { equityCtx._chartInstance.destroy(); equityCtx._chartInstance = null; }

            let bmData = {};
            try {
                const res = await fetch('/api/benchmark/normalized?symbols=SPY,QQQ');
                const json = await res.json();
                if (json.available) bmData = json.benchmarks || {};
            } catch (e) { /* ignore */ }

                // Normalize date keys to YYYY-MM-DD
                const dateKeys = equityData.map(d => (d.date || '').slice(0, 10));
                const labels = dateKeys.map(d => new Date(d + 'T00:00:00').toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'}));

                const datasets = [
                    {
                        label: 'Equity',
                        data: equityData.map(d => d.value),
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16,185,129,0.1)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2,
                        order: 0
                    }
                ];
                const bmColors = { SPY: '#6366f1', QQQ: '#f59e0b' };
                const bmLabels = { SPY: 'SPY（S&P500）', QQQ: 'QQQ（NASDAQ100）' };
                for (const [sym, series] of Object.entries(bmData)) {
                    const seriesMap = Object.fromEntries(series.map(s => [s.date.slice(0, 10), s.value]));
                    datasets.push({
                        label: bmLabels[sym] || sym,
                        data: dateKeys.map(d => seriesMap[d] ?? null),
                        borderColor: bmColors[sym] || '#9ca3af',
                        backgroundColor: 'rgba(0,0,0,0)',
                        fill: false,
                        tension: 0.4,
                        borderWidth: 1.5,
                        borderDash: [5, 4],
                        pointRadius: 0,
                        spanGaps: true,
                        order: 1
                    });
                }

                new Chart(equityCtx, {
                    type: 'line',
                    data: { labels, datasets },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: { display: true },
                            tooltip: {
                                callbacks: {
                                    label: (ctx) => `${ctx.dataset.label}: ${fmt.usd(ctx.parsed.y)}`
                                }
                            },
                            zoom: {
                                pan: { enabled: true, mode: 'x' },
                                zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' }
                            }
                        },
                        scales: {
                            y: { ticks: { callback: (v) => fmt.usd(v) } }
                        }
                    }
                });
        };

        setTimeout(async () => {
            const charts = this.data?.charts?.overview || {};
            await drawEquityChart(this._equityChartPeriod);
            this._setupChartPeriodBtns(
                '.chart-period-btn:not(.weekly-period-btn)',
                'equityChartPeriod', '_equityChartPeriod',
                (p) => drawEquityChart(p)
            );

            // Drawdown Chart
            this.createLineChart('drawdownChart', charts.drawdown_pct || [], 'Drawdown', '#ef4444', (v) => fmt.pct(v));
            
            // Positions Chart
            this.createLineChart('positionsChart', charts.open_positions || [], 'Open Positions', '#3b82f6', (v) => v);
            
            // Signals & Orders Chart
            const signalsOrders = charts.signals_orders || [];
            const ctx4 = document.getElementById('signalsOrdersChart');
            if (ctx4) {
                new Chart(ctx4, {
                    type: 'bar',
                    data: {
                        labels: signalsOrders.map(d => new Date(d.date).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'})),
                        datasets: [
                            {
                                label: 'Signals',
                                data: signalsOrders.map(d => d.signals || d.signals_value || 0),
                                backgroundColor: '#60a5fa'
                            },
                            {
                                label: 'Orders',
                                data: signalsOrders.map(d => d.orders || d.orders_value || 0),
                                backgroundColor: '#34d399'
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        plugins: { legend: { display: true } },
                        scales: { y: { beginAtZero: true } }
                    }
                });
            }
            
            // Trade Count Chart
            this.createLineChart('tradeCountChart', charts.trade_count || [], '取引回数', '#f59e0b', (v) => v);
            
            // Win Rate Chart
            this.createLineChart('winRateChart', charts.win_rate || [], '勝率', '#10b981', (v) => fmt.pct(v));
        }, 100);
    }

    createLineChart(canvasId, data, label, color, formatter) {
        const ctx = document.getElementById(canvasId);
        if (!ctx || data.length === 0) return;
        
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => new Date(d.date).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'})),
                datasets: [{
                    label: label,
                    data: data.map(d => d.value),
                    borderColor: color,
                    backgroundColor: color + '20',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => formatter(context.parsed.y)
                        }
                    },
                    zoom: {
                        pan: { enabled: true, mode: 'x' },
                        zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' }
                    }
                },
                scales: {
                    y: {
                        ticks: { callback: (value) => formatter(value) }
                    }
                }
            }
        });
    }

    startAutoRefresh() {
        // 市場時間を判定して更新頻度を調整 (CF-3)
        const getRefreshInterval = () => {
            const now = new Date();
            const hour = now.getHours();
            const day = now.getDay(); // 0=日曜, 6=土曜

            // 週末
            if (day === 0 || day === 6) {
                return 3600000; // 1時間
            }

            // 平日の市場時間外 (23:30-9:30 JST ≈ US市場外)
            if (hour >= 23 || hour < 9) {
                return 3600000; // 1時間
            }

            // 平日の市場時間中 (9:30-16:00 JST)
            if (hour >= 9 && hour < 16) {
                return 300000; // 5分
            }

            // その他の時間 (16:00-23:30 JST)
            return 1800000; // 30分
        };

        // CF-3: タブ非表示時はポーリングを停止、再表示時に即度再開
        let pendingRefresh = null;

        const scheduleNext = () => {
            const interval = getRefreshInterval();
            pendingRefresh = setTimeout(refresh, interval);
        };

        const refresh = async () => {
            pendingRefresh = null;
            // タブ非表示中は skip — 次回は表示後に visibilitychange ハンドラで起動
            if (document.visibilityState === 'hidden') {
                return;
            }
            await this.loadData();
            if (this.currentTab !== 'alerts') this.render();
            scheduleNext();
        };

        // タブが再表示されたとき: 待機中なら即度再開、リフレッシュ完了待ちなら次回スケジュール
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                if (pendingRefresh === null) {
                    // refresh実行中に戳った場合は次回の setTimeout で対応済み
                    scheduleNext();
                } else {
                    // 停止中なら遷延をキャンセルして即度実行
                    clearTimeout(pendingRefresh);
                    pendingRefresh = null;
                    refresh();
                }
            }
        });

        // 初回実行
        refresh();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const consoleApp = new Console();
    
    // Phase 3: Initialize monitoring and health checks
    initializeMonitoring();
});

/**
 * Phase 3: モニタリングとヘルスチェックの初期化
 */
function initializeMonitoring() {
    console.log('🚀 Initializing Phase 3 monitoring...');
    
    // ヘルスチェックの登録
    if (typeof healthMonitor !== 'undefined') {
        // Dashboard APIヘルスチェック
        healthMonitor.registerCheck('dashboard_api', async () => {
            const start = Date.now();
            const result = await apiClient.getDashboard();
            const duration = Date.now() - start;
            
            return {
                success: result.success,
                responseTime: duration,
                dataAge: result.timestamp ? Date.now() - result.timestamp.getTime() : 0,
                errorRate: typeof errorTracker !== 'undefined' 
                  ? errorTracker.calculateErrorRate(3600000) 
                  : 0
            };
        }, {
            interval: 60000, // 1分ごと
            thresholds: {
                responseTime: 5000,  // 5秒
                errorRate: 0.1,      // 10%
                dataAge: 300000      // 5分
            }
        });
        
        // ヘルスモニタリング開始（市場時間外は30分、市場時間中は5分）
        const hour = new Date().getHours();
        const day = new Date().getDay();
        let monitoringInterval = 1800000; // デフォルト: 30分
        
        if (day === 0 || day === 6) {
            monitoringInterval = 3600000; // 週末: 1時間
        } else if (hour >= 9 && hour < 16) {
            monitoringInterval = 300000; // 市場時間中: 5分
        }
        
        healthMonitor.startMonitoring(monitoringInterval);
        console.log(`✅ Health monitoring started (interval: ${monitoringInterval/1000}s)`);
    }
    
    // グローバルコマンドの登録（デバッグ用）
    window.showPerformanceReport = () => {
        if (typeof performanceMonitor !== 'undefined') {
            return performanceMonitor.printReport();
        }
    };
    
    window.showErrorReport = () => {
        if (typeof errorTracker !== 'undefined') {
            return errorTracker.printReport();
        }
    };
    
    window.showHealthReport = () => {
        if (typeof healthMonitor !== 'undefined') {
            return healthMonitor.printReport();
        }
    };
    
    window.showRecoveryReport = () => {
        if (typeof recoveryManager !== 'undefined') {
            return recoveryManager.printReport();
        }
    };
    
    // レポート生成コマンド
    window.generateWeeklyReportNow = () => {
        if (typeof reportGenerator !== 'undefined') {
            const report = reportGenerator.generateWeeklyReport();
            console.log('📊 Weekly report generated:', report);
            if (typeof errorHandler !== 'undefined') {
                errorHandler.showSuccess('週次レポートを生成しました！');
            }
            return report;
        }
    };
    
    window.showLatestReport = () => {
        if (typeof reportGenerator !== 'undefined') {
            const report = reportGenerator.getLatestReport();
            if (report) {
                const html = reportGenerator.formatReportHTML(report);
                const win = window.open('', 'WeeklyReport', 'width=800,height=600');
                win.document.write(`
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>週次レポート</title>
                        <link rel="stylesheet" href="/ui/style.css">
                        <style>
                            body { padding: 20px; background: #0b0f18; color: #e5e7eb; }
                            .report-card { max-width: 900px; margin: 0 auto; }
                            .report-header { text-align: center; margin-bottom: 30px; }
                            .report-score { font-size: 32px; font-weight: bold; margin: 20px 0; }
                            .report-section { margin: 30px 0; }
                            .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
                            .metric-card { background: #1a2332; padding: 15px; border-radius: 8px; }
                            .metric-label { color: #9ca3af; font-size: 14px; }
                            .metric-value { font-size: 24px; font-weight: bold; margin: 10px 0; }
                            .metric-detail { color: #9ca3af; font-size: 12px; }
                            .recommendations-list { list-style: none; padding: 0; }
                            .recommendations-list li { background: #1a2332; padding: 15px; margin: 10px 0; border-radius: 8px; }
                            .priority-badge { padding: 4px 8px; border-radius: 4px; color: white; font-size: 12px; margin-right: 10px; }
                            .top-errors { margin-top: 15px; }
                        </style>
                    </head>
                    <body>${html}</body>
                    </html>
                `);
            } else {
                console.warn('レポートがまだ生成されていません');
            }
        }
    };
    
    console.log('✅ Phase 3 monitoring initialized');
    console.log('💡 Debug commands available:');
    console.log('   - showPerformanceReport()');
    console.log('   - showErrorReport()');
    console.log('   - showHealthReport()');
    console.log('   - showRecoveryReport()');
    console.log('   - generateWeeklyReportNow()');
    console.log('   - showLatestReport()');
}
