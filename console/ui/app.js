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
            case 'trading':    content.innerHTML = this.renderTrading(); break;
            case 'positions':  content.innerHTML = this.renderPositions(); break;
            case 'cron':       content.innerHTML = this.renderCronJobs(); break;
            case 'data':       content.innerHTML = this.renderDataStatus(); break;
            case 'logs':       content.innerHTML = this.renderLogs(); break;
        }
    }

    renderOverview() {
        return `
        ${this.renderAlerts()}
        ${this.renderOverviewKpis()}
        ${this.renderOverviewCharts()}
        ${this.renderOverviewDiagnostics()}`;
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
        const latestEquity = this.latestEquity();

        return `
        <div class="grid">
            <div class="card">
                <h3>資産</h3>
                <div class="metric"><span class="label">推定Equity</span><span class="value">${fmt.usd(latestEquity)}</span></div>
                ${this.renderDelta(deltas.equity_vs_prev_snapshot, 'usd')}
            </div>
            <div class="card">
                <h3>含み損益</h3>
                <div class="metric"><span class="label">Unrealized PnL</span><span class="value ${ps.unrealized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ps.unrealized_pnl)}</span></div>
                <div class="small muted">概算値</div>
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
                <h3>Equity</h3>
                ${this.renderMiniBars(charts.equity || [], 'value', 'usd')}
            </div>
            <div class="card">
                <h3>Drawdown</h3>
                ${this.renderMiniBars(charts.drawdown_pct || [], 'value', 'pct')}
            </div>
            <div class="card">
                <h3>Open Positions</h3>
                ${this.renderMiniBars(charts.open_positions || [], 'value', 'count')}
            </div>
            <div class="card">
                <h3>Signals / Orders</h3>
                ${this.renderSignalsOrders(charts.signals_orders || [])}
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
                <div class="metric"><span class="label">決済取引数</span><span class="value">${s.closed_trades||0}</span></div>
                <div class="metric"><span class="label">保有取引数</span><span class="value">${s.open_trades||0}</span></div>
                <div class="metric"><span class="label">勝 / 負</span><span class="value">${s.winning_trades||0} / ${s.losing_trades||0}</span></div>
                <div class="metric"><span class="label">勝率</span><span class="value ${wr_cls}">${fmt.pct(winRate)}</span></div>
                <div class="metric"><span class="label">平均リターン</span><span class="value ${s.avg_return_per_trade >= 0 ? 'success':'danger'}">${fmt.pctSigned(s.avg_return_per_trade)}</span></div>
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
        return `<table>
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
        </table>`;
    }

    renderStrategyOverviewTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<table>
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
        </table>`;
    }

    renderReasonList(rows = []) {
        if (!rows.length) return '<p class="muted">リジェクト理由なし</p>';
        return rows.map(r => `<div class="metric"><span class="label">${this.escapeHtml(r.reason)}</span><span class="value">${r.count}</span></div>`).join('');
    }

    renderSubmissionTable(rows = []) {
        if (!rows.length) return '<p class="muted">Submissionなし</p>';
        return `<table>
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
        </table>`;
    }

    renderExecutionBySymbolTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<table>
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
        </table>`;
    }

    renderPendingOrdersTable(rows = []) {
        if (!rows.length) return '<p class="muted">対象なし</p>';
        return `<table>
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
        </table>`;
    }

    renderReconciliationBySymbolTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<table>
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
        </table>`;
    }

    renderSymbolOverviewTable(rows = []) {
        if (!rows.length) return '<p class="muted">データなし</p>';
        return `<table>
            <thead><tr><th>symbol</th><th>strategies</th><th>decisions</th><th>deny</th><th>submitted</th><th>conv</th><th>sub qty</th><th>open pos</th><th>pos qty</th><th>hold d</th><th>uPnL</th></tr></thead>
            <tbody>${rows.map(r => `
                <tr>
                    <td><strong>${this.escapeHtml(r.symbol || '—')}</strong></td>
                    <td class="small muted">${this.escapeHtml((r.strategy_ids || []).join(', '))}</td>
                    <td>${r.decisions ?? 0}</td>
                    <td class="danger">${r.deny ?? 0}</td>
                    <td>${r.submitted ?? 0}</td>
                    <td>${fmt.pct(r.conversion_rate ?? 0)}</td>
                    <td>${r.submitted_qty ?? 0}</td>
                    <td>${r.open_position ? '✅' : '—'}</td>
                    <td>${r.position_qty ?? 0}</td>
                    <td>${r.holding_days ?? '—'}</td>
                    <td class="${(r.unrealized_pnl || 0) >= 0 ? 'success' : 'danger'}">${r.unrealized_pnl == null ? '—' : fmt.usdSigned(r.unrealized_pnl)}</td>
                </tr>`).join('')}
            </tbody>
        </table>`;
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
        return `<table>
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
        </table>`;
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

    startAutoRefresh() {
        setInterval(async () => {
            await this.loadData();
            this.render();
        }, 30000);
    }
}

document.addEventListener('DOMContentLoaded', () => { new Console(); });
