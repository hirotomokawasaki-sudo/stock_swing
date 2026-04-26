// Stock Swing Console Frontend

const fmt = {
    usd: (v) => v == null ? '—' : `$${Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`,
    pct: (v) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`,
    pctSigned: (v) => v == null ? '—' : `${Number(v) >= 0 ? '+' : ''}${(Number(v) * 100).toFixed(2)}%`,
    usdSigned: (v) => v == null ? '—' : `${Number(v) >= 0 ? '+$' : '-$'}${Math.abs(Number(v)).toLocaleString('en-US', {minimumFractionDigits: 2})}`,
    dt: (iso) => iso ? new Date(iso).toLocaleString('ja-JP') : '—',
    badge: (label, cls) => `<span class="badge badge-${cls}">${label}</span>`,
};

class Console {
    constructor() {
        this.currentTab = 'overview';
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
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                e.target.classList.add('active');
                this.currentTab = e.target.dataset.tab;
                this.render();
            });
        });
    }

    async loadData() {
        try {
            const response = await fetch('/api/dashboard');
            this.data = await response.json();
            this.updateStatusBar();
        } catch (error) {
            console.error('Failed to load data:', error);
            this.data = { error: error.message };
        }
    }

    updateStatusBar() {
        if (!this.data) return;
        const systemStatus = document.getElementById('system-status');
        const lastUpdate = document.getElementById('last-update');
        if (this.data.system) {
            const status = this.data.system.status || 'unknown';
            const mode = this.data.system.runtime_mode || '?';
            systemStatus.innerHTML = `${fmt.badge(status.toUpperCase(), status)} <span style="color:#9ca3af;font-size:13px">モード: ${mode}</span>`;
        }
        if (this.data.time) {
            lastUpdate.textContent = `更新: ${fmt.dt(this.data.time)}`;
        }
    }

    render() {
        const content = document.getElementById('content');
        if (!this.data) { content.innerHTML = '<p class="muted">読み込み中...</p>'; return; }
        if (this.data.error) { content.innerHTML = `<div class="card"><p class="danger">エラー: ${this.data.error}</p></div>`; return; }
        switch (this.currentTab) {
            case 'overview':   content.innerHTML = this.renderOverview(); break;
            case 'analysis':   this.renderAnalysis(); break;
            case 'charts':     this.renderCharts(); break;
            case 'trading':    content.innerHTML = this.renderTrading(); break;
            case 'positions':  content.innerHTML = this.renderPositions(); break;
            case 'cron':       content.innerHTML = this.renderCronJobs(); break;
            case 'data':       content.innerHTML = this.renderDataStatus(); break;
            case 'logs':       content.innerHTML = this.renderLogs(); break;
            case 'news':       content.innerHTML = this.renderNews(); break;
        }
    }

    renderOverview() {
        return `
        ${this.renderAlerts()}
        ${this.renderOverviewKpis()}
        ${this.renderPerformanceAttribution()}
        ${this.renderOverviewCharts()}
        ${this.renderOverviewDiagnostics()}`;
    }
    
    renderPerformanceAttribution() {
        const perf = this.data?.performance || {};
        if (!perf.available && perf.alpha?.available !== true) {
            return `<div class="card"><h3>📊 パフォーマンス分析</h3><p class="muted">データ不足のため分析できません</p></div>`;
        }
        
        const alpha = perf.alpha || {};
        const beta = perf.beta || {};
        const sharpe = perf.sharpe || {};
        const summary = perf.summary || 'データ不足';
        
        if (!alpha.available) {
            return `<div class="card"><h3>📊 パフォーマンス分析</h3><p class="muted">データ不足のため分析できません</p></div>`;
        }
        
        const alphaValue = alpha.alpha || 0;
        const betaValue = beta.beta || 1.0;
        const sharpeValue = sharpe.sharpe_ratio || 0;
        
        return `
        <div class="card performance-card">
            <h3>📊 パフォーマンス分析 (vs ${alpha.benchmark?.symbol || 'SPY'})</h3>
            <div class="performance-summary">${this.escapeHtml(summary)}</div>
            <div class="grid" style="margin-top: 16px;">
                <div class="perf-metric">
                    <div class="perf-label">Alpha (超過リターン)</div>
                    <div class="perf-value ${alphaValue >= 2 ? 'success' : alphaValue >= -2 ? '' : 'danger'}">${fmt.pctSigned(alphaValue / 100)}</div>
                    <div class="perf-interpretation muted small">${this.escapeHtml(alpha.interpretation || '')}</div>
                    <div class="perf-details muted small">
                        あなた: ${fmt.pct((alpha.portfolio?.return_pct || 0) / 100)} | 
                        市場: ${fmt.pct((alpha.benchmark?.return_pct || 0) / 100)}
                    </div>
                </div>
                <div class="perf-metric">
                    <div class="perf-label">Beta (ボラティリティ)</div>
                    <div class="perf-value">${betaValue.toFixed(2)}</div>
                    <div class="perf-interpretation muted small">${this.escapeHtml(beta.interpretation || '')}</div>
                    <div class="perf-details muted small">
                        ${betaValue < 1 ? '🛡️ 市場より低リスク' : betaValue > 1 ? '⚡ 市場より高リスク' : '📊 市場と同程度'}
                    </div>
                </div>
                <div class="perf-metric">
                    <div class="perf-label">Sharpe Ratio (効率)</div>
                    <div class="perf-value ${sharpeValue >= 2 ? 'success' : sharpeValue >= 1 ? '' : 'danger'}">${sharpeValue.toFixed(2)}</div>
                    <div class="perf-interpretation muted small">${this.escapeHtml(sharpe.interpretation || '')}</div>
                    <div class="perf-details muted small">
                        年間: ${fmt.pct((sharpe.annual_return_pct || 0) / 100)} ± ${fmt.pct((sharpe.annual_volatility_pct || 0) / 100)}
                    </div>
                </div>
            </div>
            <div class="perf-period muted small" style="margin-top: 12px;">
                期間: ${alpha.period?.start || ''} ～ ${alpha.period?.end || ''} (${alpha.period?.days || 0}日間)
            </div>
        </div>`;
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

    renderOverviewKpis() {
        const ov = this.data?.overview || {};
        const ts = ov.trading_summary || {};
        const deltas = ov.deltas || {};
        const ps = this.data?.positions?.summary || {};
        const account = ov.account || {};
        const latestEquity = account.equity || this.latestEquity();
        const cash = account.cash || 0;
        const cashPct = latestEquity > 0 ? (cash / latestEquity) : 0;
        const positionPct = latestEquity > 0 ? ((latestEquity - cash) / latestEquity) : 0;

        return `
        <div class="grid">
            <div class="card">
                <h3>💰 資産総額</h3>
                <div class="metric"><span class="label">Equity</span><span class="value big">${fmt.usd(latestEquity)}</span></div>
                <div class="metric"><span class="label">現金</span><span class="value">${fmt.usd(cash)} <span class="small muted">(${fmt.pct(cashPct)})</span></span></div>
                <div class="metric"><span class="label">ポジション</span><span class="value">${fmt.usd(ps.gross_exposure)} <span class="small muted">(${fmt.pct(positionPct)})</span></span></div>
                ${this.renderDelta(deltas.equity_vs_prev_snapshot, 'usd')}
            </div>
            <div class="card">
                <h3>📊 損益</h3>
                <div class="metric"><span class="label">含み損益</span><span class="value ${ps.unrealized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ps.unrealized_pnl)}</span></div>
                <div class="metric"><span class="label">確定損益</span><span class="value ${ts.cumulative_realized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ts.cumulative_realized_pnl)}</span></div>
                <div class="metric"><span class="label">合計損益</span><span class="value big ${(ps.unrealized_pnl + ts.cumulative_realized_pnl) >= 0 ? 'success' : 'danger'}">${fmt.usdSigned((ps.unrealized_pnl || 0) + (ts.cumulative_realized_pnl || 0))}</span></div>
            </div>
            <div class="card">
                <h3>オープン取引</h3>
                <div class="metric"><span class="label">件数</span><span class="value">${ts.open_trades ?? 0}</span></div>
                ${this.renderDelta(deltas.open_trades_vs_prev_snapshot, 'count')}
            </div>
            <div class="card">
                <h3>意思決定</h3>
                <div class="metric"><span class="label">Decisions</span><span class="value">${this.data?.data_status?.counts?.decisions ?? 0}</span></div>
                ${this.renderDelta(deltas.decisions_vs_prev_snapshot, 'count')}
            </div>
            <div class="card">
                <h3>リスク</h3>
                <div class="metric"><span class="label">Gross Exposure</span><span class="value">${fmt.usd(ps.gross_exposure)}</span></div>
                <div class="metric"><span class="label">最大DD</span><span class="value ${(ts.max_drawdown_pct || 0) > 0.05 ? 'danger' : ''}">${fmt.pct(ts.max_drawdown_pct)}</span></div>
            </div>
            <div class="card">
                <h3>集中度</h3>
                <div class="metric"><span class="label">最大ポジション比率</span><span class="value">${fmt.pct(ps.largest_position_weight)}</span></div>
                <div class="metric"><span class="label">Top 5集中</span><span class="value">${fmt.pct(ps.top5_concentration)}</span></div>
            </div>
        </div>`;
    }

    renderOverviewCharts() {
        const charts = this.data?.charts?.overview || {};
        return `
        <div class="grid charts-grid">
            <div class="card">
                <h3>Equity推移</h3>
                ${this.renderMiniBarsWithDates(charts.equity || [], 'value', 'usd')}
            </div>
            <div class="card">
                <h3>Drawdown推移</h3>
                ${this.renderMiniBarsWithDates(charts.drawdown_pct || [], 'value', 'pct')}
            </div>
            <div class="card">
                <h3>Open Positions推移</h3>
                ${this.renderMiniBarsWithDates(charts.open_positions || [], 'value', 'count')}
            </div>
            <div class="card">
                <h3>Signals / Orders推移</h3>
                ${this.renderSignalsOrdersWithDates(charts.signals_orders || [])}
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
        const strategyOverview = this.renderStrategyOverviewTable((pipeline.by_strategy || []).map(r => ({
            ...r,
            conversion_rate: r.decisions ? ((r.buy + r.sell) / r.decisions) : 0,
        })));
        if (!td.available) {
            return `<div class="card"><p class="muted">取引データが利用できません。${td.error||''}</p></div>`;
        }
        const s = td.summary || {};
        const recent = td.recent_trades || [];
        const snaps = td.daily_snapshots || [];
        const winRate = s.win_rate;
        const wr_cls = winRate >= 0.55 ? 'success' : winRate < 0.40 && s.closed_trades > 0 ? 'danger' : 'warn';

        return `
        ${this.renderPipelineFunnel()}
        <div class="grid">
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
                <div class="metric"><span class="label">平均損益</span><span class="value ${s.avg_pnl_per_trade >= 0 ? 'success':'danger'}">${fmt.usdSigned(s.avg_pnl_per_trade)}</span></div>
                <div class="metric"><span class="label">累積実現損益</span><span class="value ${s.cumulative_realized_pnl >= 0 ? 'success':'danger'} big">${fmt.usdSigned(s.cumulative_realized_pnl)}</span></div>
                <div class="metric"><span class="label">最大DD</span><span class="value ${s.max_drawdown_pct > 0.05 ? 'danger':''}">${fmt.pct(s.max_drawdown_pct)}</span></div>
                <div class="metric"><span class="label">ピーク資産</span><span class="value">${fmt.usd(s.peak_equity)}</span></div>
                <div class="metric"><span class="label">取引日数</span><span class="value">${s.trading_days||0}</span></div>
            </div>

            <div class="card">
                <h3>戦略別 Decision 内訳</h3>
                ${strategyOverview}
            </div>

            <div class="card">
                <h3>銘柄別 Decision 内訳</h3>
                ${this.renderBreakdownTable(pipeline.by_symbol || [], 'symbol')}
            </div>

            <div class="card">
                <h3>リジェクト理由（正規化）</h3>
                ${this.renderReasonList((pipeline.rejections || {}).normalized_reasons || [])}
            </div>
        </div>

        <div class="grid" style="margin-top:16px">
            <div class="card">
                <h3>リジェクト理由（原文）</h3>
                ${this.renderReasonList((pipeline.rejections || {}).decision_reasons || [])}
            </div>
            <div class="card">
                <h3>実行サマリー</h3>
                ${this.renderExecutionSummary(pipeline.execution || {})}
            </div>
            <div class="card">
                <h3>最近のPaper Runs</h3>
                ${this.renderRunList(pipeline.runs || [])}
            </div>
        </div>

        <div class="grid" style="margin-top:16px">
            <div class="card">
                <h3>Recent Submissions</h3>
                ${this.renderSubmissionTable((pipeline.execution || {}).recent_submissions || [])}
            </div>
            <div class="card">
                <h3>Execution by Symbol</h3>
                ${this.renderExecutionBySymbolTable((pipeline.execution || {}).by_symbol || [])}
            </div>
        </div>

        <div class="card" style="margin-top:16px">
            <h3>Symbol Overview</h3>
            ${this.renderSymbolOverviewTable(pipeline.symbol_overview || [])}
        </div>

        <div class="card" style="margin-top:16px">
            <h3>日次スナップショット (直近${snaps.length}件)</h3>
            ${snaps.length === 0
                ? '<p class="muted">スナップショットなし。Paper Demo実行後に表示されます。</p>'
                : `<table>
                    <thead><tr><th>日付</th><th>資産</th><th>実現損益</th><th>取引数</th><th>勝利</th><th>シグナル</th></tr></thead>
                    <tbody>${[...snaps].reverse().map(d => `
                        <tr>
                            <td>${d.date}</td>
                            <td>${fmt.usd(d.equity)}</td>
                            <td class="${d.realized_pnl >= 0 ? 'success':'danger'}">${fmt.usdSigned(d.realized_pnl)}</td>
                            <td>${d.trade_count}</td>
                            <td>${d.win_count}/${d.trade_count}</td>
                            <td>${d.signals_generated}</td>
                        </tr>`).join('')}
                    </tbody></table>`
            }
        </div>

        <div class="card" style="margin-top:16px">
            <h3>最近の決済取引 (直近${recent.length}件)</h3>
            ${recent.length === 0
                ? '<p class="muted">決済取引なし。</p>'
                : `<table>
                    <thead><tr><th>銘柄</th><th>売買</th><th>数量</th><th>取得価格</th><th>決済価格</th><th>損益</th><th>リターン</th><th>戦略</th><th>時刻</th></tr></thead>
                    <tbody>${[...recent].reverse().map(t => `
                        <tr>
                            <td><strong>${t.symbol}</strong></td>
                            <td>${t.side?.toUpperCase()}</td>
                            <td>${t.qty}</td>
                            <td>${fmt.usd(t.entry_price)}</td>
                            <td>${fmt.usd(t.exit_price)}</td>
                            <td class="${(t.pnl||0) >= 0 ? 'success':'danger'}">${fmt.usdSigned(t.pnl)}</td>
                            <td class="${(t.return_pct||0) >= 0 ? 'success':'danger'}">${fmt.pctSigned(t.return_pct)}</td>
                            <td><span class="tag">${t.strategy_id}</span></td>
                            <td class="muted small">${fmt.dt(t.exit_time)}</td>
                        </tr>`).join('')}
                    </tbody></table>`
            }
        </div>`;
    }

    renderPositionsSummary() {
        const s = this.data?.positions?.summary || {};
        return `
        <div class="grid" style="margin-bottom:16px">
            <div class="card">
                <h3>Exposure</h3>
                <div class="metric"><span class="label">Gross</span><span class="value">${fmt.usd(s.gross_exposure)}</span></div>
                <div class="metric"><span class="label">Net</span><span class="value">${fmt.usd(s.net_exposure)}</span></div>
                <div class="metric"><span class="label">Long / Short</span><span class="value">${s.long_count ?? 0} / ${s.short_count ?? 0}</span></div>
            </div>
            <div class="card">
                <h3>PnL</h3>
                <div class="metric"><span class="label">Unrealized</span><span class="value ${s.unrealized_pnl >= 0 ? 'success':'danger'}">${fmt.usdSigned(s.unrealized_pnl)}</span></div>
                <div class="metric"><span class="label">平均保有日数</span><span class="value">${s.avg_holding_days ?? '—'}</span></div>
            </div>
            <div class="card">
                <h3>集中度</h3>
                <div class="metric"><span class="label">最大比率</span><span class="value">${fmt.pct(s.largest_position_weight)}</span></div>
                <div class="metric"><span class="label">Top5</span><span class="value">${fmt.pct(s.top5_concentration)}</span></div>
            </div>
        </div>`;
    }

    renderPositions() {
        const pd = this.data.positions || {};
        const positions = pd.positions || [];

        return `
        ${this.renderPositionsSummary()}
        <div class="card">
            <h3>保有ポジション (${positions.length}件)</h3>
            ${positions.length === 0
                ? '<p class="muted">保有ポジションなし。Paper Demo実行後に表示されます。</p>'
                : `<table>
                    <thead><tr><th>銘柄</th><th>売買</th><th>数量</th><th>取得価格</th><th>現在価格</th><th>時価</th><th>含み損益</th><th>保有日数</th><th>比率</th><th>戦略</th><th>取得時刻</th></tr></thead>
                    <tbody>${positions.map(p => `
                        <tr>
                            <td><strong>${p.symbol}</strong></td>
                            <td>${p.side?.toUpperCase()}</td>
                            <td>${p.qty}</td>
                            <td>${fmt.usd(p.entry_price)}</td>
                            <td>${fmt.usd(p.current_price)}</td>
                            <td>${fmt.usd(p.market_value)}</td>
                            <td class="${(p.unrealized_pnl||0) >= 0 ? 'success':'danger'}">${fmt.usdSigned(p.unrealized_pnl)}</td>
                            <td>${p.holding_days ?? '—'}</td>
                            <td>${fmt.pct(p.portfolio_weight)}</td>
                            <td><span class="tag">${p.strategy_id}</span></td>
                            <td class="muted small">${fmt.dt(p.entry_time)}</td>
                        </tr>`).join('')}
                    </tbody></table>`
            }
        </div>`;
    }

    renderCronJobs() {
        const cronData = this.data.cron_jobs || {};
        const jobs = cronData.jobs || [];
        if (jobs.length === 0) return '<div class="card"><p class="muted">定期実行ジョブが見つかりません</p></div>';

        return `
        <div class="card">
            <h3>定期実行ジョブ (合計${cronData.total||0}件 / 有効${cronData.active||0}件)</h3>
            <table>
                <thead><tr><th>名前</th><th>スケジュール</th><th>次回実行</th><th>最終成功</th><th>実行時間</th><th>成功率(7d)</th><th>状態</th></tr></thead>
                <tbody>${jobs.map(job => `
                    <tr>
                        <td>${job.name||'Unknown'}</td>
                        <td><code>${job.schedule_display||'N/A'}</code></td>
                        <td class="muted small">${job.next_run ? fmt.dt(job.next_run) : '—'}</td>
                        <td class="muted small">${job.last_success ? fmt.dt(job.last_success) : '—'}</td>
                        <td>${job.last_duration_ms != null ? `${Math.round(job.last_duration_ms/1000)}s` : '—'}</td>
                        <td>${job.success_rate_7d != null ? fmt.pct(job.success_rate_7d) : '—'}</td>
                        <td>${job.running ? fmt.badge('RUNNING', 'warn') : ((job.lag_seconds||0) > 0 ? fmt.badge('LAG', 'danger') : (job.enabled ? fmt.badge('OK', 'success') : fmt.badge('DISABLED', 'danger')))}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
        </div>`;
    }

    renderDataIntegrity() {
        const integrity = this.data?.data_status?.integrity;
        if (!integrity) return '<div class="card"><p class="muted">整合性チェックなし</p></div>';
        const checks = integrity.checks || [];
        return `
        <div class="card">
            <h3>整合性チェック</h3>
            <div class="metric"><span class="label">全体状態</span><span>${fmt.badge(integrity.status || 'unknown', integrity.status || 'unknown')}</span></div>
            ${checks.map(c => `
                <div class="metric" style="align-items:flex-start">
                    <span class="label">${this.escapeHtml(c.name)}</span>
                    <span style="text-align:right">
                        ${fmt.badge(c.status, c.status === 'ok' ? 'success' : c.status === 'warn' ? 'warn' : 'danger')}
                        <div class="muted small">${this.escapeHtml(c.message || '')}</div>
                    </span>
                </div>`).join('')}
        </div>`;
    }

    renderDataStatus() {
        const ds = this.data.data_status || {};
        const counts = ds.counts || {};
        const freshness = ds.freshness || {};

        return `
        <div class="grid">
            <div class="card">
                <h3>ステージ別データファイル</h3>
                ${Object.entries(counts).map(([stage, count]) =>
                    `<div class="metric"><span class="label">${stage}</span><span class="value ${count > 0 ? '':'muted'}">${count}件</span></div>`
                ).join('')}
            </div>
            <div class="card">
                <h3>データ鮮度</h3>
                ${Object.entries(freshness).map(([stage, info]) =>
                    `<div class="metric">
                        <span class="label">${stage}</span>
                        <span>${fmt.badge(info.status, info.status)} ${info.age_hours != null ? `<span class="muted small">${info.age_hours}h ago</span>` : ''}</span>
                    </div>`
                ).join('')}
            </div>
            ${this.renderDataIntegrity()}
        </div>`;
    }

    renderNews() {
        return `
        ${this.renderNewsSummary()}
        <div class="card" style="margin-top:16px">
            <h3>News Coverage Status</h3>
            ${this.renderNewsCoverageStatus()}
        </div>
        <div class="card" style="margin-top:16px">
            <h3>Filters</h3>
            ${this.renderNewsFilters()}
        </div>
        <div class="grid" style="margin-top:16px">
            <div class="card">
                <h3>News Feed</h3>
                ${this.renderNewsTable()}
            </div>
            <div class="card">
                <h3>集計</h3>
                ${this.renderNewsAggregates()}
                <div style="margin-top:16px">
                  <h4 style="margin-bottom:8px">Timeline</h4>
                  ${this.renderNewsTimeline()}
                </div>
            </div>
        </div>
        <div class="card" style="margin-top:16px">
            <h3>News Detail</h3>
            ${this.renderNewsDetail()}
        </div>
        <div class="card" style="margin-top:16px">
            <h3>Source Reliability Report</h3>
            ${this.renderSourceReliabilityTable()}
        </div>
        <div class="card" style="margin-top:16px">
            <h3>News Diagnostics</h3>
            ${this.renderNewsDiagnostics()}
        </div>`;
    }

    renderNewsSummary() {
        const s = this.data?.news?.summary || {};
        const sr = this.data?.source_reliability?.summary || {};
        return `
        <div class="grid">
          <div class="card"><h3>News 24h</h3><div class="metric"><span class="label">件数</span><span class="value">${s.total_24h ?? 0}</span></div></div>
          <div class="card"><h3>Sentiment</h3><div class="metric"><span class="label">ポジティブ</span><span class="value success">${s.positive ?? 0}</span></div><div class="metric"><span class="label">ネガティブ</span><span class="value danger">${s.negative ?? 0}</span></div><div class="metric"><span class="label">中立</span><span class="value">${s.neutral ?? 0}</span></div></div>
          <div class="card"><h3>Impact</h3><div class="metric"><span class="label">高</span><span class="value warn">${s.high_impact ?? 0}</span></div><div class="metric"><span class="label">重大</span><span class="value danger">${s.critical_impact ?? 0}</span></div></div>
          <div class="card"><h3>Decision Link</h3><div class="metric"><span class="label">採用件数</span><span class="value">${s.decision_referenced ?? 0}</span></div><div class="metric"><span class="label">対象銘柄</span><span class="value">${s.symbols_covered ?? 0}</span></div></div>
          <div class="card"><h3>Source Reliability</h3><div class="metric"><span class="label">sources</span><span class="value">${sr.sources ?? 0}</span></div><div class="metric"><span class="label">+delta</span><span class="value success">${sr.with_positive_delta ?? 0}</span></div><div class="metric"><span class="label">-delta</span><span class="value danger">${sr.with_negative_delta ?? 0}</span></div></div>
        </div>`;
    }

    getFilteredNewsItems() {
        let items = this.data?.news?.items || [];
        if (this.newsFilterTrackedOnly) items = items.filter(n => n.is_tracked_symbol !== false);
        if (this.newsFilterUsed) items = items.filter(n => n.used_in_decision);
        if (this.newsFilterSentiment && this.newsFilterSentiment !== 'all') items = items.filter(n => n.sentiment_label === this.newsFilterSentiment);
        if (this.newsFilterImpact && this.newsFilterImpact !== 'all') items = items.filter(n => n.impact_label === this.newsFilterImpact);
        if (this.newsFilterSymbol) items = items.filter(n => (n.symbol || '').toUpperCase() === this.newsFilterSymbol.toUpperCase());
        const sortKey = this.newsSort || 'published_at';
        items = [...items].sort((a, b) => {
            if (sortKey === 'impact') return Number(b.impact_score || 0) - Number(a.impact_score || 0);
            if (sortKey === 'influence') return Number(b.influence_score || 0) - Number(a.influence_score || 0);
            if (sortKey === 'sentiment') return Math.abs(Number(b.sentiment_score || 0)) - Math.abs(Number(a.sentiment_score || 0));
            return String(b.published_at || '').localeCompare(String(a.published_at || ''));
        });
        return items;
    }

    renderNewsCoverageStatus() {
        const alerts = (this.data?.alerts || []).filter(a => a.code === 'no_news_for_tracked_symbols' || a.code === 'stale_news_symbols');
        const ingestion = this.data?.news_ingestion || {};
        return `
          <div class="grid">
            <div class="card"><h3>Latest External News</h3><div class="metric"><span class="label">時刻</span><span class="small muted">${ingestion.latest_news_time ? fmt.dt(ingestion.latest_news_time) : '—'}</span></div><div class="metric"><span class="label">鮮度</span><span class="value ${(ingestion.status || 'ok') === 'stale' ? 'danger' : (ingestion.status || 'ok') === 'partial' ? 'warn' : 'success'}">${ingestion.freshness_hours != null ? ingestion.freshness_hours + 'h' : '—'}</span></div><div class="metric"><span class="label">items</span><span class="value">${ingestion.total_items ?? 0}</span></div><div class="metric"><span class="label">raw/tracked-display/requested</span><span class="value">${ingestion.raw_symbols_collected ?? 0}/${ingestion.displayed_tracked_symbols_collected ?? 0}/${ingestion.symbols_requested ?? 0}</span></div>${(ingestion.displayed_non_tracked_symbols || []).length ? `<div class="small muted">non-tracked: ${this.escapeHtml((ingestion.displayed_non_tracked_symbols || []).join(', '))}</div>` : ''}<div class="metric"><span class="label">last success</span><span class="small muted">${ingestion.last_success ? fmt.dt(ingestion.last_success) : '—'}</span></div><div class="metric"><span class="label">last failure</span><span class="small muted">${ingestion.last_failure ? fmt.dt(ingestion.last_failure) : '—'}</span></div></div>
            <div class="card"><h3>Source Coverage</h3>${(ingestion.source_counts || []).slice(0,5).map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.source)}</span><span class="value">${r.count}</span></div>`).join('') || '<p class="muted">source data なし</p>'}<div style="margin-top:8px">${(ingestion.source_failures || []).map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.source)}</span><span class="value danger">${r.count}</span></div>`).join('')}</div><div style="margin-top:8px">${(ingestion.failure_reason_counts || []).map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.reason)}</span><span class="value">${r.count}</span></div>`).join('')}</div></div>
            <div class="card"><h3>Coverage Alerts</h3>${alerts.length ? alerts.map(a => `<div class="alert alert-${a.severity}" style="margin-bottom:8px"><div class="alert-head">${this.renderSeverityBadge(a.severity)} <strong>${this.escapeHtml(a.title || a.code)}</strong></div><div>${this.escapeHtml(a.message || '')}</div></div>`).join('') : '<p class="muted">tracked symbols のニュース鮮度に大きな問題はありません。</p>'}<div style="margin-top:8px">${(ingestion.missing_symbol_reasons || []).length ? `<table><thead><tr><th>symbol</th><th>reason</th><th>fallback</th></tr></thead><tbody>${(ingestion.missing_symbol_reasons || []).map(r => `<tr><td><strong>${this.escapeHtml(r.symbol)}</strong></td><td>${this.escapeHtml(r.reason)}</td><td>${r.used_fallback ? 'yes' : 'no'}</td></tr>`).join('')}</tbody></table>` : ((ingestion.missing_symbols || []).length ? `<div class="small muted">missing: ${this.escapeHtml((ingestion.missing_symbols || []).join(', '))}</div>` : '')}</div></div>
          </div>`;
    }

    renderNewsFilters() {
        return `
          <div style="display:flex; gap:16px; flex-wrap:wrap; align-items:center;">
            <label><input type="checkbox" ${this.newsFilterUsed ? 'checked' : ''} onchange="window.app.setNewsUsedFilter(this.checked)"> 採用のみ</label>
            <label><input type="checkbox" ${this.newsFilterTrackedOnly ? 'checked' : ''} onchange="window.app.setNewsTrackedOnlyFilter(this.checked)"> trackedのみ</label>
            <label>symbol
              <input type="text" value="${this.escapeHtml(this.newsFilterSymbol || '')}" placeholder="例: MRVL" oninput="window.app.setNewsSymbolFilter(this.value)">
            </label>
            <label>感情
              <select onchange="window.app.setNewsSentimentFilter(this.value)">
                <option value="all" ${!this.newsFilterSentiment || this.newsFilterSentiment==='all' ? 'selected' : ''}>すべて</option>
                <option value="positive" ${this.newsFilterSentiment==='positive' ? 'selected' : ''}>ポジティブ</option>
                <option value="negative" ${this.newsFilterSentiment==='negative' ? 'selected' : ''}>ネガティブ</option>
                <option value="neutral" ${this.newsFilterSentiment==='neutral' ? 'selected' : ''}>中立</option>
              </select>
            </label>
            <label>重要度
              <select onchange="window.app.setNewsImpactFilter(this.value)">
                <option value="all" ${!this.newsFilterImpact || this.newsFilterImpact==='all' ? 'selected' : ''}>すべて</option>
                <option value="high" ${this.newsFilterImpact==='high' ? 'selected' : ''}>高</option>
                <option value="critical" ${this.newsFilterImpact==='critical' ? 'selected' : ''}>重大</option>
                <option value="medium" ${this.newsFilterImpact==='medium' ? 'selected' : ''}>中</option>
              </select>
            </label>
            <label>並び替え
              <select onchange="window.app.setNewsSort(this.value)">
                <option value="published_at" ${this.newsSort==='published_at' ? 'selected' : ''}>新着順</option>
                <option value="impact" ${this.newsSort==='impact' ? 'selected' : ''}>影響度順</option>
                <option value="influence" ${this.newsSort==='influence' ? 'selected' : ''}>参考度順</option>
                <option value="sentiment" ${this.newsSort==='sentiment' ? 'selected' : ''}>感情強度順</option>
              </select>
            </label>
          </div>`;
    }

    renderNewsTable() {
        const items = this.getFilteredNewsItems();
        if (!items.length) return '<p class="muted">ニュースはありません</p>';
        return `<div class="table-wrap"><table><thead><tr><th>時刻</th><th>銘柄</th><th>見出し</th><th>感情</th><th>重要度</th><th>影響度</th><th>採用</th></tr></thead><tbody>${items.map(n => `
          <tr class="clickable-row ${this.selectedNewsId === n.id ? 'selected-row' : ''}" onclick="window.app.selectNews('${this.escapeHtml(n.id)}')">
            <td class="small muted">${fmt.dt(n.published_at)}</td>
            <td><strong>${this.escapeHtml(n.symbol || '—')}</strong>${n.is_tracked_symbol === false ? ' <span class="badge badge-muted">non-tracked</span>' : ' <span class="badge badge-success">tracked</span>'}</td>
            <td><div>${n.url ? `<a href="${this.escapeHtml(n.url)}" target="_blank" rel="noopener noreferrer">${this.escapeHtml(n.headline_ja || n.headline || '—')}</a>` : this.escapeHtml(n.headline_ja || n.headline || '—')}</div><div class="small muted">${this.escapeHtml(n.summary_ja || '')}</div></td>
            <td>${this.renderSentimentBadge(n.sentiment_label, n.sentiment_score)}</td>
            <td>${this.renderImpactBadge(n.impact_label)}</td>
            <td>${this.renderInfluenceBar(n.influence_score)}</td>
            <td>${n.used_in_decision ? '<span class="badge badge-success">採用</span>' : '<span class="badge badge-muted">未採用</span>'}</td>
          </tr>`).join('')}</tbody></table></div>`;
    }

    renderNewsAggregates() {
        const bySymbol = this.data?.news?.by_symbol || [];
        const bySource = this.data?.news?.by_source || [];
        const byEventType = this.data?.news?.by_event_type || [];
        return `
          <h4 style="margin-bottom:8px">銘柄別</h4>
          ${bySymbol.length ? `<div class="table-wrap"><table><thead><tr><th>銘柄</th><th>tracked</th><th>件数</th><th>平均感情</th><th>平均重要度</th><th>採用</th><th>submitted</th><th>open</th><th>conv</th><th>最新見出し</th></tr></thead><tbody>${bySymbol.map(r => `
            <tr><td><strong>${this.escapeHtml(r.symbol)}</strong></td><td>${r.is_tracked_symbol === false ? '<span class="badge badge-muted">non-tracked</span>' : '<span class="badge badge-success">tracked</span>'}</td><td>${r.news_count}</td><td>${Number(r.avg_sentiment ?? 0).toFixed(2)}</td><td>${Number(r.avg_impact ?? 0).toFixed(2)}</td><td>${r.decision_referenced ?? 0}</td><td>${r.submitted ?? 0}</td><td>${r.open_position ? '✅' : '—'}</td><td>${fmt.pct(r.conversion_rate ?? 0)}</td><td class="small muted">${this.escapeHtml(r.latest_headline_ja || '')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">銘柄別集計なし</p>'}
          <h4 style="margin:16px 0 8px">Symbol Overview 連携</h4>
          ${bySymbol.length ? `<div class="table-wrap"><table><thead><tr><th>symbol</th><th>avg sentiment</th><th>avg impact</th><th>submitted</th><th>open</th><th>conv</th></tr></thead><tbody>${bySymbol.map(r => `
            <tr><td><strong>${this.escapeHtml(r.symbol)}</strong></td><td>${Number(r.avg_sentiment ?? 0).toFixed(2)}</td><td>${Number(r.avg_impact ?? 0).toFixed(2)}</td><td>${r.submitted ?? 0}</td><td>${r.open_position ? '✅' : '—'}</td><td>${fmt.pct(r.conversion_rate ?? 0)}</td></tr>`).join('')}</tbody></table></div>` : ''}
          <h4 style="margin:16px 0 8px">ソース別</h4>
          ${bySource.length ? `<div class="table-wrap"><table><thead><tr><th>source</th><th>count</th><th>pos</th><th>neg</th><th>neutral</th></tr></thead><tbody>${bySource.map(r => `
            <tr><td>${this.escapeHtml(r.source)}</td><td>${r.count}</td><td>${r.positive}</td><td>${r.negative}</td><td>${r.neutral}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">ソース別集計なし</p>'}
          <h4 style="margin:16px 0 8px">イベント種別</h4>
          ${byEventType.length ? `<div class="table-wrap"><table><thead><tr><th>event_type</th><th>count</th><th>pos</th><th>neg</th><th>neutral</th></tr></thead><tbody>${byEventType.map(r => `
            <tr><td>${this.renderEventTypeBadge(r.event_type)}</td><td>${r.count}</td><td>${r.positive}</td><td>${r.negative}</td><td>${r.neutral}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">イベント種別集計なし</p>'}`;
    }

    renderNewsDetail() {
        const items = this.data?.news?.items || [];
        const n = items.find(x => x.id === this.selectedNewsId) || this.data?.news?.selected;
        if (!n) return '<p class="muted">詳細表示対象のニュースはありません</p>';
        return `
          <div class="metric"><span class="label">銘柄</span><span class="value">${this.escapeHtml(n.symbol || '—')} ${n.is_tracked_symbol === false ? '<span class="badge badge-muted">non-tracked</span>' : '<span class="badge badge-success">tracked</span>'}</span></div>
          <div class="metric"><span class="label">時刻</span><span class="small muted">${fmt.dt(n.published_at)}</span></div>
          <div class="metric"><span class="label">ソース</span><span>${this.escapeHtml(n.source || '—')}</span></div>
          <div class="metric"><span class="label">Source reliability</span><span>${Number(n.source_reliability ?? 0).toFixed(2)}</span></div>
          <div class="metric"><span class="label">イベント種別</span><span>${this.renderEventTypeBadge(n.event_type)}</span></div>
          <div class="metric"><span class="label">見出し</span><span>${this.escapeHtml(n.headline_ja || n.headline || '—')}</span></div>
          <div class="metric"><span class="label">要約</span><span>${this.escapeHtml(n.summary_ja || n.snippet || '—')}</span></div>
          <div class="metric"><span class="label">感情</span><span>${this.renderSentimentBadge(n.sentiment_label, n.sentiment_score)}</span></div>
          <div class="metric"><span class="label">重要度</span><span>${this.renderImpactBadge(n.impact_label)}</span></div>
          <div class="metric"><span class="label">影響度</span><span>${this.renderInfluenceBar(n.influence_score)}</span></div>
          <div class="metric"><span class="label">戦略</span><span>${this.escapeHtml((n.strategy_refs || []).join(', '))}</span></div>
          <div class="metric"><span class="label">Decision refs</span><span class="small muted">${this.escapeHtml((n.decision_refs || []).join(', '))}</span></div>
          <div style="margin-top:12px">
            <div class="small muted">理由</div>
            <ul>${(n.rationale_ja || []).map(r => `<li>${this.escapeHtml(r)}</li>`).join('')}</ul>
          </div>
          ${n.headline ? `<div style="margin-top:12px"><div class="small muted">原文</div><div>${this.escapeHtml(n.headline)}</div></div>` : ''}
          ${n.url ? `<div style="margin-top:12px"><a href="${this.escapeHtml(n.url)}" target="_blank" rel="noopener noreferrer">詳細を開く</a></div>` : `<div style="margin-top:12px" class="small muted">外部リンクなし（内部判断由来）</div>`}
        `;
    }

    renderEventTypeBadge(eventType) {
        const e = String(eventType || 'event').toLowerCase();
        const map = {
            momentum: ['モメンタム', 'success'],
            event: ['イベント', 'warn'],
            earnings: ['決算', 'danger'],
            guidance: ['ガイダンス', 'warn'],
            regulation: ['規制', 'danger'],
            filing: ['開示', 'muted']
        };
        const pair = map[e] || ['その他', 'muted'];
        return `<span class="badge badge-${pair[1]}">${pair[0]}</span>`;
    }

    renderNewsTimeline() {
        const timeline = this.data?.news?.timeline || [];
        if (!timeline.length) return '<p class="muted">タイムラインなし</p>';
        const max = Math.max(...timeline.flatMap(t => [Number(t.positive || 0), Number(t.negative || 0), Number(t.neutral || 0), Number(t.count || 0)]), 1);
        return `<div class="sparkline dual-bars"><div class="bars">${timeline.map(t => {
            const ph = Math.max(8, Math.round((Number(t.positive || 0) / max) * 80));
            const nh = Math.max(8, Math.round((Number(t.negative || 0) / max) * 80));
            return `<div class="bar-pair"><div class="bar signal-bar" style="height:${ph}px"></div><div class="bar order-bar" style="height:${nh}px"></div></div>`;
        }).join('')}</div><div class="legend small muted" style="margin-top:8px"><span class="legend-dot signal-dot"></span>Positive <span class="legend-dot order-dot"></span>Negative</div><div class="small muted" style="margin-top:8px">最新: ${timeline[timeline.length - 1]?.count ?? 0}件</div></div>`;
    }

    selectNews(id) {
        this.selectedNewsId = id;
        this.render();
    }

    setNewsUsedFilter(v) {
        this.newsFilterUsed = v;
        localStorage.setItem('newsFilterUsed', String(v));
        this.render();
    }

    setNewsTrackedOnlyFilter(v) {
        this.newsFilterTrackedOnly = v;
        localStorage.setItem('newsFilterTrackedOnly', String(v));
        this.render();
    }

    setNewsSentimentFilter(v) {
        this.newsFilterSentiment = v;
        localStorage.setItem('newsFilterSentiment', String(v));
        this.render();
    }

    setNewsImpactFilter(v) {
        this.newsFilterImpact = v;
        localStorage.setItem('newsFilterImpact', String(v));
        this.render();
    }

    setNewsSymbolFilter(v) {
        this.newsFilterSymbol = v;
        localStorage.setItem('newsFilterSymbol', String(v));
        this.render();
    }

    setNewsSort(v) {
        this.newsSort = v;
        localStorage.setItem('newsSort', String(v));
        this.render();
    }

    openNewsForSymbol(symbol) {
        this.currentTab = 'news';
        this.newsFilterSymbol = symbol || '';
        localStorage.setItem('newsFilterSymbol', String(this.newsFilterSymbol));
        const items = this.data?.news?.items || [];
        const first = items.find(n => (n.symbol || '').toUpperCase() === String(symbol || '').toUpperCase());
        this.selectedNewsId = first ? first.id : null;
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        const tab = document.querySelector('.tab[data-tab="news"]');
        if (tab) tab.classList.add('active');
        this.render();
    }

    renderSentimentBadge(label, score) {
        const l = String(label || 'neutral').toLowerCase();
        const cls = l === 'positive' ? 'success' : l === 'negative' ? 'danger' : 'muted';
        const ja = l === 'positive' ? 'ポジティブ' : l === 'negative' ? 'ネガティブ' : '中立';
        return `<span class="badge badge-${cls}">${ja} ${score != null ? `(${Number(score).toFixed(2)})` : ''}</span>`;
    }

    renderImpactBadge(label) {
        const l = String(label || 'low').toLowerCase();
        const map = { low: ['低', 'muted'], medium: ['中', 'warn'], high: ['高', 'warn'], critical: ['重大', 'danger'] };
        const pair = map[l] || ['不明', 'muted'];
        return `<span class="badge badge-${pair[1]}">${pair[0]}</span>`;
    }

    renderInfluenceBar(score=0) {
        const pct = Math.max(0, Math.min(100, Math.round(Number(score || 0) * 100)));
        return `<div class="influence-wrap"><div class="influence-bar"><div class="influence-fill" style="width:${pct}%"></div></div><div class="small muted">${pct}%</div></div>`;
    }

    renderSourceReliabilityTable() {
        const rows = this.data?.source_reliability?.rows || [];
        const history = this.data?.source_reliability?.history || [];
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `${history.length ? `<div style="margin-bottom:12px">${this.renderSourceReliabilityHistory(history)}</div>` : ''}<table>
          <thead><tr><th>source</th><th>current</th><th>observed</th><th>suggested</th><th>delta</th><th>count</th><th>used</th><th>avg influence</th></tr></thead>
          <tbody>${rows.map(r => `
            <tr>
              <td><strong>${this.escapeHtml(r.source)}</strong></td>
              <td>${Number(r.current_reliability ?? 0).toFixed(2)}</td>
              <td>${Number(r.observed_quality_score ?? 0).toFixed(2)}</td>
              <td>${Number(r.suggested_reliability ?? 0).toFixed(2)}</td>
              <td class="${(r.delta || 0) >= 0 ? 'success' : 'danger'}">${(r.delta || 0) >= 0 ? '+' : ''}${Number(r.delta || 0).toFixed(2)}</td>
              <td>${r.count ?? 0}</td>
              <td>${r.used_count ?? 0}</td>
              <td>${Number(r.avg_influence ?? 0).toFixed(2)}</td>
            </tr>`).join('')}
          </tbody>
        </table>`;
    }

    renderSourceReliabilityHistory(history = []) {
        if (!history.length) return '';
        const sourceMap = {};
        for (const snap of history) {
            for (const row of (snap.rows || [])) {
                if (!sourceMap[row.source]) sourceMap[row.source] = [];
                sourceMap[row.source].push({ time: snap.time, value: Number(row.suggested_reliability || 0), delta: Number(row.delta || 0) });
            }
        }
        const entries = Object.entries(sourceMap);
        if (!entries.length) return '';
        return `<div><div class="small muted" style="margin-bottom:6px">提案値の履歴</div>${entries.map(([source, points]) => {
            const max = Math.max(...points.map(p => p.value), 1);
            const latest = points[points.length - 1] || { value: 0, delta: 0 };
            return `<div style="margin-bottom:12px"><div class="small muted">${this.escapeHtml(source)} latest=${latest.value.toFixed(2)} delta=${latest.delta >= 0 ? '+' : ''}${latest.delta.toFixed(2)}</div><div class="bars">${points.map(p => {
                const h = Math.max(8, Math.round((p.value / max) * 80));
                return `<div class="bar-wrap"><div class="bar" style="height:${h}px"></div></div>`;
            }).join('')}</div></div>`;
        }).join('')}</div>`;
    }

    renderNewsDiagnostics() {
        const d = this.data?.news?.diagnostics || {};
        const renderCounts = (rows=[]) => rows.length ? rows.map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.symbol)}</span><span class="value">${r.count}</span></div>`).join('') : '<p class="muted">データなし</p>';
        return `<div class="grid">
          <div class="card"><h3>Loaded</h3>${renderCounts(d.loaded_by_symbol || [])}</div>
          <div class="card"><h3>Linked</h3>${renderCounts(d.linked_by_symbol || [])}</div>
          <div class="card"><h3>Selected</h3>${renderCounts(d.selected_by_symbol || [])}</div>
        </div>`;
    }

    renderLogs() {
        const ld = this.data.logs || {};
        const lines = ld.lines || [];
        const report = ld.daily_report || '';

        return `
        <div class="card" style="margin-bottom:16px">
            <h3>本日の日次レポート</h3>
            ${report
                ? `<pre class="log-box">${this.escapeHtml(report)}</pre>`
                : '<p class="muted">本日のレポートはまだありません。</p>'
            }
        </div>
        <div class="card">
            <h3>監査ログ — 本日 (${lines.length}行)</h3>
            <p class="muted small" style="margin-bottom:8px">ファイル: ${ld.log_file||'—'}</p>
            ${lines.length === 0
                ? '<p class="muted">ログエントリなし。まずPaper Demoを実行してください。</p>'
                : `<pre class="log-box">${lines.map(l => this.escapeHtml(l)).join('\n')}</pre>`
            }
        </div>`;
    }

    renderPipelineFunnel() {
        const funnel = this.data?.pipeline?.funnel || {};
        const items = [
            ['raw', funnel.raw],
            ['normalized', funnel.normalized],
            ['features', funnel.features],
            ['signals', funnel.signals],
            ['decisions', funnel.decisions],
            ['risk_rejected', funnel.risk_rejected],
            ['orders_submitted', funnel.orders_submitted],
            ['positions_opened', funnel.positions_opened],
            ['positions_closed', funnel.positions_closed],
        ];
        const max = Math.max(...items.map(([, v]) => Number(v || 0)), 1);
        return `
        <div class="card" style="margin-bottom:16px">
            <h3>Pipeline Funnel</h3>
            <div class="funnel-grid">${items.map(([label, value]) => {
                const width = Math.max(6, Math.round((Number(value || 0) / max) * 100));
                return `<div class="funnel-item"><div class="small muted">${label}</div><div class="funnel-bar"><div class="funnel-fill" style="width:${width}%"></div></div><div class="value">${value ?? 0}</div></div>`;
            }).join('')}</div>
        </div>`;
    }

    renderBreakdownTable(rows = [], keyField = 'symbol') {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>${keyField}</th><th>decisions</th><th>buy</th><th>sell</th><th>deny</th><th>pass</th><th>reject</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td><strong>${this.escapeHtml(r[keyField] || '—')}</strong></td>
                    <td>${r.decisions ?? 0}</td>
                    <td>${r.buy ?? 0}</td>
                    <td>${r.sell ?? 0}</td>
                    <td>${r.deny ?? 0}</td>
                    <td class="success">${r.pass ?? 0}</td>
                    <td class="danger">${r.reject ?? 0}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderStrategyOverviewTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>strategy</th><th>decisions</th><th>buy</th><th>sell</th><th>deny</th><th>pass</th><th>reject</th><th>conv</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td><strong>${this.escapeHtml(r.strategy_id || '—')}</strong></td>
                    <td>${r.decisions ?? 0}</td>
                    <td>${r.buy ?? 0}</td>
                    <td>${r.sell ?? 0}</td>
                    <td class="danger">${r.deny ?? 0}</td>
                    <td class="success">${r.pass ?? 0}</td>
                    <td class="danger">${r.reject ?? 0}</td>
                    <td>${fmt.pct(r.conversion_rate ?? 0)}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderReasonList(rows = []) {
        if (!rows.length) return '<p class="muted">リジェクト理由なし</p>';
        return rows.map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.reason)}</span><span class="value">${r.count}</span></div>`).join('');
    }

    renderSubmissionTable(rows = []) {
        if (!rows.length) return '<p class="muted">Submissionなし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>time</th><th>symbol</th><th>side</th><th>qty</th><th>details</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td class="small muted">${fmt.dt(r.ts)}</td>
                    <td><strong>${this.escapeHtml(r.symbol || '—')}</strong></td>
                    <td>${this.escapeHtml((r.side || '—').toUpperCase())}</td>
                    <td>${r.qty ?? 0}</td>
                    <td class="small muted">${this.escapeHtml(r.details || '')}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderExecutionBySymbolTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>symbol</th><th>submitted</th><th>buy</th><th>sell</th><th>qty</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td><strong>${this.escapeHtml(r.symbol || '—')}</strong></td>
                    <td>${r.submitted ?? 0}</td>
                    <td>${r.buy ?? 0}</td>
                    <td>${r.sell ?? 0}</td>
                    <td>${r.qty ?? 0}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderPendingOrdersTable(rows = []) {
        if (!rows.length) return '<p class="muted">対象なし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>time</th><th>symbol</th><th>side</th><th>qty</th><th>status</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td class="small muted">${fmt.dt(r.ts)}</td>
                    <td><strong>${this.escapeHtml(r.symbol || '—')}</strong></td>
                    <td>${this.escapeHtml((r.side || '—').toUpperCase())}</td>
                    <td>${r.qty ?? 0}</td>
                    <td><span class="tag ${r.status === 'reconciled_ok' ? 'success' : r.status.includes('mismatch') ? 'danger' : 'warn'}">${this.escapeHtml(r.status || '—')}</span></td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderReconciliationBySymbolTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>symbol</th><th>submissions</th><th>buy</th><th>sell</th><th>mismatches</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td><strong>${this.escapeHtml(r.symbol || '—')}</strong></td>
                    <td>${r.submissions ?? 0}</td>
                    <td>${r.buy ?? 0}</td>
                    <td>${r.sell ?? 0}</td>
                    <td class="${(r.mismatches || 0) > 0 ? 'danger' : 'success'}">${r.mismatches ?? 0}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderSymbolOverviewTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>symbol</th><th>strategies</th><th>decisions</th><th>deny</th><th>submitted</th><th>conv</th><th>news</th><th>news sent</th><th>news impact</th><th>ref news</th><th>sub qty</th><th>open pos</th><th>pos qty</th><th>hold d</th><th>uPnL</th><th>latest news</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td><strong>${this.escapeHtml(r.symbol || '—')}</strong></td>
                    <td class="small muted">${this.escapeHtml((r.strategy_ids || []).join(', '))}</td>
                    <td>${r.decisions ?? 0}</td>
                    <td class="danger">${r.deny ?? 0}</td>
                    <td>${r.submitted ?? 0}</td>
                    <td>${fmt.pct(r.conversion_rate ?? 0)}</td>
                    <td>${r.news_count ?? 0}</td>
                    <td>${Number(r.avg_news_sentiment ?? 0).toFixed(2)}</td>
                    <td>${Number(r.avg_news_impact ?? 0).toFixed(2)}</td>
                    <td>${r.decision_referenced_news_count ?? 0}</td>
                    <td>${r.submitted_qty ?? 0}</td>
                    <td>${r.open_position ? '✅' : '—'}</td>
                    <td>${r.position_qty ?? 0}</td>
                    <td>${r.holding_days ?? '—'}</td>
                    <td class="${(r.unrealized_pnl || 0) >= 0 ? 'success' : 'danger'}">${r.unrealized_pnl == null ? '—' : fmt.usdSigned(r.unrealized_pnl)}</td>
                    <td class="small muted">${r.latest_news_headline_ja ? `<a href="#" onclick="event.preventDefault(); window.app.openNewsForSymbol('${this.escapeHtml(r.symbol || '')}')">${this.escapeHtml(r.latest_news_headline_ja || '')}</a>` : ''}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderExecutionSummary(execution = {}) {
        const discrepancies = execution.discrepancies || {};
        return `
        <div class="metric"><span class="label">Submitted Orders</span><span class="value">${execution.submitted_orders ?? 0}</span></div>
        <div class="metric"><span class="label">Estimated Fills</span><span class="value">${execution.fills_estimated ?? 0}</span></div>
        <div class="metric"><span class="label">Reconciliations</span><span class="value">${execution.reconciliations ?? 0}</span></div>
        <div class="metric"><span class="label">Discrepancy Events</span><span class="value">${discrepancies.total ?? 0}</span></div>
        <div class="metric"><span class="label">Recent Submissions</span><span class="value">${(execution.recent_submissions || []).length}</span></div>
        ${(discrepancies.types || []).slice(0, 5).map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.reason)}</span><span class="value">${r.count}</span></div>`).join('')}`;
    }

    renderRunList(runs = []) {
        if (!runs.length) return '<p class="muted">Run履歴なし</p>';
        return `<div class="table-wrap"><table>
            <thead><tr><th>start</th><th>complete</th><th>decisions</th><th>submitted</th><th>conv</th></tr></thead>
            <tbody>${runs.map(r => `
                <tr>
                    <td class="small muted">${fmt.dt(r.started_at)}</td>
                    <td class="small muted">${fmt.dt(r.completed_at)}</td>
                    <td>${r.decisions ?? 0}</td>
                    <td>${r.submitted ?? 0}</td>
                    <td>${fmt.pct(r.conversion_rate ?? 0)}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>`;
    }

    renderMiniBarsWithDates(series = [], key = 'value', type = 'count') {
        if (!series.length) return '<p class="muted">データなし</p>';
        const vals = series.map(d => d[key]).filter(v => v != null);
        if (!vals.length) return '<p class="muted">値なし</p>';
        const max = Math.max(...vals);
        const min = Math.min(...vals);
        const range = max - min || 1;
        
        // For count type (positions), use 0 as baseline instead of min
        const baseline = type === 'count' ? 0 : min;
        const effectiveRange = type === 'count' ? max : range;
        
        const firstDate = series[0]?.ts ? new Date(series[0].ts).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'}) : '';
        const lastDate = series[series.length - 1]?.ts ? new Date(series[series.length - 1].ts).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'}) : '';
        
        return `
        <div class="mini-chart">
            <div class="mini-bars">
                ${series.map((d, i) => {
                    const v = d[key];
                    if (v == null) return '<div class="mini-bar" style="height:2px;background:#444"></div>';
                    const pct = ((v - baseline) / effectiveRange) * 100;
                    const fmtVal = type === 'usd' ? fmt.usd(v) : type === 'pct' ? fmt.pct(v) : v;
                    return `<div class="mini-bar" style="height:${Math.max(pct, 2)}%" title="${fmtVal}"></div>`;
                }).join('')}
            </div>
            <div class="mini-labels" style="display:flex;justify-content:space-between;font-size:11px;color:#9ca3af;margin-top:4px;">
                <span>${firstDate}</span>
                <span>${lastDate}</span>
            </div>
            <div class="muted small" style="margin-top:4px;">最小: ${type === 'usd' ? fmt.usd(min) : type === 'pct' ? fmt.pct(min) : min} / 最大: ${type === 'usd' ? fmt.usd(max) : type === 'pct' ? fmt.pct(max) : max}</div>
        </div>`;
    }

    renderMiniBars(series = [], key = 'value', type = 'count') {
        if (!series.length) return '<p class="muted">データなし</p>';
        const vals = series.map(p => Number(p[key] ?? 0));
        const max = Math.max(...vals, 1);
        return `
        <div class="sparkline">
            <div class="bars">${series.map(p => {
                const v = Number(p[key] ?? 0);
                const h = Math.max(8, Math.round((v / max) * 80));
                return `<div class="bar-wrap"><div class="bar" style="height:${h}px"></div></div>`;
            }).join('')}</div>
            <div class="small muted" style="margin-top:8px">最新: ${this.formatByType(vals[vals.length - 1], type)}</div>
        </div>`;
    }

    renderSignalsOrdersWithDates(series = []) {
        if (!series.length) return '<p class="muted">データなし</p>';
        const maxVal = Math.max(...series.map(d => Math.max(d.signals || 0, d.orders || 0)), 1);
        
        const firstDate = series[0]?.ts ? new Date(series[0].ts).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'}) : '';
        const lastDate = series[series.length - 1]?.ts ? new Date(series[series.length - 1].ts).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'}) : '';
        
        // Calculate total and conversion rate
        const totalSignals = series.reduce((sum, d) => sum + (d.signals || 0), 0);
        const totalOrders = series.reduce((sum, d) => sum + (d.orders || 0), 0);
        const conversionRate = totalSignals > 0 ? (totalOrders / totalSignals * 100) : 0;
        
        return `
        <div class="mini-chart signals-orders-chart">
            <div class="chart-stats" style="display:flex;gap:16px;margin-bottom:8px;font-size:12px;">
                <div><span style="color:#3b82f6">■</span> Signals: <strong>${totalSignals}</strong></div>
                <div><span style="color:#10b981">■</span> Orders: <strong>${totalOrders}</strong></div>
                <div><span style="color:#fbbf24">▶</span> Conversion: <strong>${conversionRate.toFixed(1)}%</strong></div>
            </div>
            <div class="stacked-bars" style="display:flex;gap:2px;height:120px;align-items:flex-end;">
                ${series.map((d, idx) => {
                    const sig = d.signals || 0;
                    const ord = d.orders || 0;
                    const sigHeight = (sig / maxVal) * 100;
                    const ordHeight = (ord / maxVal) * 100;
                    const conv = sig > 0 ? (ord / sig * 100) : 0;
                    const date = d.ts ? new Date(d.ts).toLocaleDateString('ja-JP', {month: 'short', day: 'numeric'}) : '';
                    
                    // Show every 5th date or first/last
                    const showDate = idx === 0 || idx === series.length - 1 || idx % 5 === 0;
                    
                    return `
                    <div class="stacked-bar-group" style="flex:1;position:relative;height:100%;">
                        <div style="position:absolute;bottom:0;width:100%;height:100%;display:flex;flex-direction:column;justify-content:flex-end;">
                            <div class="signal-bar" 
                                 style="height:${Math.max(sigHeight, sig > 0 ? 8 : 0)}%;background:#3b82f6;opacity:0.7;border-radius:2px 2px 0 0;" 
                                 title="${date}\nSignals: ${sig}\nOrders: ${ord}\nConversion: ${conv.toFixed(1)}%">
                            </div>
                            <div class="order-bar" 
                                 style="height:${Math.max(ordHeight, ord > 0 ? 8 : 0)}%;background:#10b981;border-radius:2px 2px 0 0;margin-top:2px;" 
                                 title="${date}\nOrders: ${ord}\nConversion: ${conv.toFixed(1)}%">
                            </div>
                        </div>
                        ${showDate ? `<div class="bar-label" style="position:absolute;bottom:-20px;left:50%;transform:translateX(-50%);font-size:9px;color:#6b7280;white-space:nowrap;">${date}</div>` : ''}
                    </div>`;
                }).join('')}
            </div>
            <div class="mini-labels" style="margin-top:24px;font-size:11px;color:#9ca3af;text-align:center;">
                期間: ${firstDate} ～ ${lastDate} (最大値: ${maxVal})
            </div>
        </div>`;
    }

    renderSignalsOrders(series = []) {
        if (!series.length) return '<p class="muted">データなし</p>';
        const max = Math.max(...series.flatMap(p => [Number(p.signals || 0), Number(p.orders || 0)]), 1);
        return `
        <div class="sparkline dual-bars">
            <div class="bars">${series.map(p => {
                const sh = Math.max(8, Math.round((Number(p.signals || 0) / max) * 80));
                const oh = Math.max(8, Math.round((Number(p.orders || 0) / max) * 80));
                return `<div class="bar-pair"><div class="bar signal-bar" style="height:${sh}px"></div><div class="bar order-bar" style="height:${oh}px"></div></div>`;
            }).join('')}</div>
            <div class="legend small muted" style="margin-top:8px"><span class="legend-dot signal-dot"></span>Signals <span class="legend-dot order-dot"></span>Orders</div>
        </div>`;
    }

    renderDelta(value, type='count') {
        if (value == null) return '<div class="muted small">前回比: —</div>';
        const text = this.formatByType(value, type, true);
        const cls = value > 0 ? 'success' : value < 0 ? 'danger' : 'muted';
        return `<div class="small ${cls}">前回比: ${text}</div>`;
    }

    renderSeverityBadge(severity) {
        const s = String(severity || 'info').toLowerCase();
        const label = s === 'critical' ? 'CRITICAL' : s === 'warning' ? 'WARNING' : 'INFO';
        const cls = s === 'critical' ? 'danger' : s === 'warning' ? 'warn' : 'success';
        return fmt.badge(label, cls);
    }

    latestEquity() {
        const snaps = this.data?.trading?.daily_snapshots || [];
        return snaps.length ? snaps[snaps.length - 1].equity : null;
    }

    formatByType(value, type='count', signed=false) {
        if (value == null) return '—';
        if (type === 'usd') return signed ? fmt.usdSigned(value) : fmt.usd(value);
        if (type === 'pct') return signed ? fmt.pctSigned(value) : fmt.pct(value);
        const num = Number(value);
        return `${signed && num >= 0 ? '+' : ''}${num}`;
    }

    escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    async renderAnalysis() {
        const content = document.getElementById('content');
        content.innerHTML = '<div class="card"><h3>分析</h3><p class="muted">読み込み中...</p></div>';
        
        try {
            const [strategyData, liveMetrics] = await Promise.all([
                fetch('/api/strategy_analysis').then(r => r.json()),
                fetch('/api/live_metrics').then(r => r.json())
            ]);
            
            content.innerHTML = this.renderLiveMetricsCard(liveMetrics) + this.renderStrategyAnalysis(strategyData);
        } catch (error) {
            content.innerHTML = `<div class="card"><p class="danger">エラー: ${error.message}</p></div>`;
        }
    }
    
    renderLiveMetricsCard(data) {
        if (!data.available) {
            return '<div class="card"><h3>📊 Live Metrics</h3><p class="muted">データなし</p></div>';
        }
        
        const riskColor = data.risk_score < 4 ? 'success' : data.risk_score < 7 ? 'warn' : 'danger';
        
        return `
        <div class="card live-metrics-card">
            <h3>📊 Live Metrics <span class="refresh-dot">●</span></h3>
            <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))">
                <div class="metric">
                    <span class="label">Current Drawdown</span>
                    <span class="value ${data.current_drawdown_pct > 5 ? 'danger' : ''}">${data.current_drawdown_pct.toFixed(2)}%</span>
                    <span class="small muted">Max: ${data.max_drawdown_pct.toFixed(2)}%</span>
                </div>
                <div class="metric">
                    <span class="label">Portfolio Heat</span>
                    <span class="value">${data.portfolio_heat_pct.toFixed(1)}%</span>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width:${Math.min(data.portfolio_heat_pct, 100)}%"></div>
                    </div>
                </div>
                <div class="metric">
                    <span class="label">Risk Score</span>
                    <span class="value ${riskColor}">${data.risk_score.toFixed(1)}/10 ${data.risk_emoji}</span>
                    <span class="small muted">${data.risk_level}</span>
                </div>
                <div class="metric">
                    <span class="label">Kelly Suggested Size</span>
                    <span class="value">${data.kelly_suggested_size_pct.toFixed(1)}%</span>
                    <span class="small muted">Per position</span>
                </div>
                <div class="metric">
                    <span class="label">Open P&L</span>
                    <span class="value ${data.open_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(data.open_pnl)}</span>
                    <span class="small muted">${data.open_positions_count} positions</span>
                </div>
                <div class="metric">
                    <span class="label">Days Since Last Trade</span>
                    <span class="value">${data.days_since_last_trade.toFixed(1)}</span>
                    <span class="small muted">days</span>
                </div>
            </div>
        </div>`;
    }
    
    renderStrategyAnalysis(data) {
        if (!data.available) {
            return '<div class="card"><h3>戦略別パフォーマンス</h3><p class="muted">データなし</p></div>';
        }
        
        const strategies = Object.values(data.by_strategy || {});
        if (strategies.length === 0) {
            return '<div class="card"><h3>戦略別パフォーマンス</h3><p class="muted">トレードデータなし</p></div>';
        }
        
        strategies.sort((a, b) => b.total_trades - a.total_trades);
        
        return `
        <div class="card">
            <h3>戦略別パフォーマンス</h3>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Strategy</th>
                            <th>Trades</th>
                            <th>Win Rate</th>
                            <th>Total P&L</th>
                            <th>Avg P&L</th>
                            <th>Sharpe</th>
                            <th>Profit Factor</th>
                            <th>Max DD</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${strategies.map(s => `
                            <tr>
                                <td><strong>${this.escapeHtml(s.strategy_id)}</strong></td>
                                <td>${s.total_trades}</td>
                                <td>${fmt.pct(s.win_rate)}</td>
                                <td class="${s.total_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(s.total_pnl)}</td>
                                <td class="${s.avg_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(s.avg_pnl)}</td>
                                <td class="${s.sharpe_ratio >= 1 ? 'success' : ''}">${s.sharpe_ratio.toFixed(2)}</td>
                                <td>${s.profit_factor.toFixed(2)}</td>
                                <td>${fmt.usd(s.max_drawdown)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>`;
    }

    async renderCharts() {
        const content = document.getElementById('content');
        content.innerHTML = `
            <div class="grid">
                <div class="card">
                    <h3>Equity Curve</h3>
                    <canvas id="equity-chart"></canvas>
                </div>
                <div class="card">
                    <h3>Drawdown</h3>
                    <canvas id="drawdown-chart"></canvas>
                </div>
            </div>
            <div class="grid" style="margin-top:16px">
                <div class="card">
                    <h3>P&L Distribution</h3>
                    <canvas id="pnl-distribution-chart"></canvas>
                </div>
                <div class="card">
                    <h3>Monthly Returns</h3>
                    <canvas id="monthly-returns-chart"></canvas>
                </div>
            </div>
        `;
        
        setTimeout(() => {
            this.createEquityChart();
            this.createDrawdownChart();
            this.createPnLDistribution();
            this.createMonthlyReturns();
        }, 100);
    }
    
    createEquityChart() {
        const snapshots = this.data?.trading?.daily_snapshots || [];
        if (snapshots.length === 0) return;
        
        const ctx = document.getElementById('equity-chart');
        if (!ctx) return;
        
        const dates = snapshots.map(s => s.date || s.ts);
        const equity = snapshots.map(s => s.equity || 0);
        
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: [{
                    label: 'Equity',
                    data: equity,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        mode: 'index',
                        callbacks: {
                            label: (ctx) => `Equity: ${fmt.usd(ctx.parsed.y)}`
                        }
                    }
                },
                scales: {
                    y: {
                        ticks: {
                            callback: (value) => fmt.usd(value)
                        }
                    }
                }
            }
        });
    }
    
    createDrawdownChart() {
        const snapshots = this.data?.trading?.daily_snapshots || [];
        if (snapshots.length === 0) return;
        
        const ctx = document.getElementById('drawdown-chart');
        if (!ctx) return;
        
        const equity = snapshots.map(s => s.equity || 0);
        const peak = [];
        let maxSoFar = 0;
        const drawdown = equity.map(e => {
            maxSoFar = Math.max(maxSoFar, e);
            peak.push(maxSoFar);
            return maxSoFar > 0 ? ((maxSoFar - e) / maxSoFar) * 100 : 0;
        });
        
        const dates = snapshots.map(s => s.date || s.ts);
        
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: [{
                    label: 'Drawdown',
                    data: drawdown.map(d => -d),
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    fill: true,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `Drawdown: ${Math.abs(ctx.parsed.y).toFixed(2)}%`
                        }
                    }
                },
                scales: {
                    y: {
                        ticks: {
                            callback: (value) => `${Math.abs(value).toFixed(1)}%`
                        }
                    }
                }
            }
        });
    }
    
    createPnLDistribution() {
        const trades = this.data?.trading?.closed_trades || [];
        if (trades.length === 0) return;
        
        const ctx = document.getElementById('pnl-distribution-chart');
        if (!ctx) return;
        
        const pnls = trades.map(t => t.pnl || 0);
        const min = Math.min(...pnls);
        const max = Math.max(...pnls);
        const binCount = 20;
        const binSize = (max - min) / binCount;
        
        const bins = Array(binCount).fill(0);
        pnls.forEach(pnl => {
            const binIndex = Math.min(Math.floor((pnl - min) / binSize), binCount - 1);
            bins[binIndex]++;
        });
        
        const labels = bins.map((_, i) => {
            const start = min + i * binSize;
            return fmt.usd(start);
        });
        
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Trade Count',
                    data: bins,
                    backgroundColor: bins.map((_, i) => {
                        const midpoint = min + (i + 0.5) * binSize;
                        return midpoint >= 0 ? 'rgba(16, 185, 129, 0.7)' : 'rgba(239, 68, 68, 0.7)';
                    })
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2,
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }
    
    createMonthlyReturns() {
        const snapshots = this.data?.trading?.daily_snapshots || [];
        if (snapshots.length === 0) return;
        
        const ctx = document.getElementById('monthly-returns-chart');
        if (!ctx) return;
        
        const monthlyData = {};
        snapshots.forEach(s => {
            const date = s.date || s.ts?.substring(0, 10) || '';
            const month = date.substring(0, 7);
            if (!monthlyData[month]) {
                monthlyData[month] = [];
            }
            monthlyData[month].push(s.equity || 0);
        });
        
        const months = Object.keys(monthlyData).sort();
        const returns = months.map((month, i) => {
            const equities = monthlyData[month];
            const endEquity = equities[equities.length - 1];
            if (i === 0) {
                return 0;
            }
            const prevMonth = months[i - 1];
            const prevEnd = monthlyData[prevMonth][monthlyData[prevMonth].length - 1];
            return prevEnd > 0 ? ((endEquity - prevEnd) / prevEnd) * 100 : 0;
        });
        
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: months,
                datasets: [{
                    label: 'Monthly Return (%)',
                    data: returns,
                    backgroundColor: returns.map(r => r >= 0 ? 'rgba(16, 185, 129, 0.7)' : 'rgba(239, 68, 68, 0.7)')
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `Return: ${ctx.parsed.y.toFixed(2)}%`
                        }
                    }
                },
                scales: {
                    y: {
                        ticks: {
                            callback: (value) => `${value.toFixed(1)}%`
                        }
                    }
                }
            }
        });
    }

    startAutoRefresh() {
        setInterval(async () => {
            if (this.currentTab === 'analysis') {
                try {
                    const liveMetrics = await fetch('/api/live_metrics').then(r => r.json());
                    const card = document.querySelector('.live-metrics-card');
                    if (card) {
                        const newCard = this.renderLiveMetricsCard(liveMetrics);
                        card.outerHTML = newCard;
                    }
                } catch (error) {
                    console.error('Auto-refresh failed:', error);
                }
            } else {
                await this.loadData();
                this.render();
            }
        }, 30000);
    }
}

document.addEventListener('DOMContentLoaded', () => { window.app = new Console(); });
