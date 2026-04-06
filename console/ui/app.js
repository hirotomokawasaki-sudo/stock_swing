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

    // ── Overview ─────────────────────────────────────────────────────────────
    renderOverview() {
        const ov = this.data.overview || {};
        const sys = this.data.system || {};
        const ts = (ov.trading_summary) || {};

        const winRate = ts.win_rate != null ? ts.win_rate : null;
        const wr_color = winRate == null ? '' : (winRate >= 0.55 ? 'success' : winRate < 0.40 ? 'danger' : 'warn');

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
                <h3>取引サマリー</h3>
                <div class="metric"><span class="label">決済取引数</span><span class="value">${ts.closed_trades ?? '—'}</span></div>
                <div class="metric"><span class="label">勝率</span><span class="value ${wr_color}">${winRate != null ? fmt.pct(winRate) : '—'}</span></div>
                <div class="metric"><span class="label">累積損益</span><span class="value ${ts.cumulative_realized_pnl >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ts.cumulative_realized_pnl)}</span></div>
                <div class="metric"><span class="label">最大DD</span><span class="value ${ts.max_drawdown_pct > 0.05 ? 'danger' : ''}">${ts.max_drawdown_pct != null ? fmt.pct(ts.max_drawdown_pct) : '—'}</span></div>
            </div>

            <div class="card">
                <h3>定期実行</h3>
                <div class="metric"><span class="label">有効</span><span class="value success">${ov.cron_jobs_active||0}</span></div>
                <div class="metric"><span class="label">合計</span><span class="value">${ov.cron_jobs_total||0}</span></div>
            </div>

            <div class="card">
                <h3>データファイル</h3>
                ${this.renderDataCountsCompact(ov.data_counts)}
            </div>
        </div>`;
    }

    renderDataCountsCompact(counts) {
        if (!counts) return '<p class="muted">データなし</p>';
        return Object.entries(counts).map(([stage, count]) =>
            `<div class="metric"><span class="label">${stage}</span><span class="value ${count > 0 ? '' : 'muted'}">${count}</span></div>`
        ).join('');
    }

    // ── Trading ───────────────────────────────────────────────────────────────
    renderTrading() {
        const td = this.data.trading || {};
        if (!td.available) {
            return `<div class="card"><p class="muted">取引データが利用できません。${td.error||''}</p></div>`;
        }
        const s = td.summary || {};
        const recent = td.recent_trades || [];
        const snaps = td.daily_snapshots || [];

        const winRate = s.win_rate;
        const wr_cls = winRate >= 0.55 ? 'success' : winRate < 0.40 && s.closed_trades > 0 ? 'danger' : 'warn';

        return `
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

    // ── Positions ─────────────────────────────────────────────────────────────
    renderPositions() {
        const pd = this.data.positions || {};
        const positions = pd.positions || [];

        return `
        <div class="card">
            <h3>保有ポジション (${positions.length}件)</h3>
            ${positions.length === 0
                ? '<p class="muted">保有ポジションなし。Paper Demo実行後に表示されます。</p>'
                : `<table>
                    <thead><tr><th>銘柄</th><th>売買</th><th>数量</th><th>取得価格</th><th>戦略</th><th>取得時刻</th><th>注文ID</th></tr></thead>
                    <tbody>${positions.map(p => `
                        <tr>
                            <td><strong>${p.symbol}</strong></td>
                            <td>${p.side?.toUpperCase()}</td>
                            <td>${p.qty}</td>
                            <td>${fmt.usd(p.entry_price)}</td>
                            <td><span class="tag">${p.strategy_id}</span></td>
                            <td class="muted small">${fmt.dt(p.entry_time)}</td>
                            <td class="muted small">${p.broker_order_id||'—'}</td>
                        </tr>`).join('')}
                    </tbody></table>`
            }
        </div>`;
    }

    // ── Cron Jobs ─────────────────────────────────────────────────────────────
    renderCronJobs() {
        const cronData = this.data.cron_jobs || {};
        const jobs = cronData.jobs || [];
        if (jobs.length === 0) return '<div class="card"><p class="muted">定期実行ジョブが見つかりません</p></div>';

        return `
        <div class="card">
            <h3>定期実行ジョブ (合計${cronData.total||0}件 / 有効${cronData.active||0}件)</h3>
            <table>
                <thead><tr><th>名前</th><th>スケジュール</th><th>次回実行</th><th>状態</th></tr></thead>
                <tbody>${jobs.map(job => `
                    <tr>
                        <td>${job.name||'Unknown'}</td>
                        <td><code>${job.schedule_display||'N/A'}</code></td>
                        <td class="muted small">${job.next_run ? fmt.dt(job.next_run) : '—'}</td>
                        <td>${job.enabled ? '<span class="badge badge-success">有効</span>' : '<span class="badge badge-danger">無効</span>'}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
        </div>`;
    }

    // ── Data Status ───────────────────────────────────────────────────────────
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
        </div>`;
    }

    // ── Logs ──────────────────────────────────────────────────────────────────
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
