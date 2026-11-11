// Stock Swing Console Frontend
// Version: 2026-05-12-0938 (archive history view)
console.log('📊 Stock Swing Console v2026-05-12-0938 loaded');

// Format helpers (safe + compatible with original implementation)
const finiteValue = (v) => {
    if (v == null || typeof v === 'boolean' || (typeof v !== 'number' && typeof v !== 'string') || String(v).trim() === '') return null;
    const n = Number(v); return Number.isFinite(n) ? n : null;
};
const fmt = {
    usd: (v) => {
        const num = finiteValue(v);
        if (num === null) return '未取得';
        return `$${num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    },
    pct: (v) => {
        const num = finiteValue(v);
        if (num === null) return '未取得';
        return `${(num * 100).toFixed(2)}%`;
    },
    pctSigned: (v) => {
        const num = finiteValue(v);
        if (num === null) return '未取得';
        return `${num >= 0 ? '+' : ''}${(num * 100).toFixed(2)}%`;
    },
    usdSigned: (v) => {
        const num = finiteValue(v);
        if (num === null) return '未取得';
        return `${num >= 0 ? '+$' : '-$'}${Math.abs(num).toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    },
    dt: (iso) => iso ? new Date(iso).toLocaleString('ja-JP') : '—',
    badge: (label, cls) => `<span class="badge badge-${cls}">${label}</span>`,
};

let consoleMarketClock = null;
class Console {
    static pollingDelay(clock, now = Date.now()) {
        const stamp = Date.parse(clock?.as_of || '');
        const boundary = Date.parse(clock?.next_transition_at || '');
        if (clock?.timezone !== 'America/New_York' || !['regular','extended','closed'].includes(clock?.session)
            || ![300000,1800000,3600000].includes(clock?.refresh_interval_ms)
            || !/(Z|[+-]\d{2}:\d{2})$/.test(clock?.as_of || '') || !/(Z|[+-]\d{2}:\d{2})$/.test(clock?.next_transition_at || '')
            || !Number.isFinite(stamp) || stamp > now || now-stamp > 7200000
            || !Number.isFinite(boundary) || boundary <= now) return 300000;
        return Math.max(10000, Math.min(clock.refresh_interval_ms, boundary-now));
    }

    captureReadingState(content) {
        if (!this._renderedTab || !content) return;
        this._readingState ||= {};
        this._readingState[this._renderedTab] = {
            details: [...content.querySelectorAll('details')].map((e,i)=>({key:e.id || 'detail-'+i,open:e.open})),
            selects: [...content.querySelectorAll('select[id]')].map(e=>({id:e.id,value:e.value})),
            tables: [...content.querySelectorAll('.table-wrap')].map(e=>e.scrollLeft),
            scroll: window.scrollY
        };
        try { sessionStorage.setItem('consoleReadingStateV1',JSON.stringify(this._readingState)); } catch {}
    }

    restoreReadingState(content, revision) {
        const saved=this._readingState?.[this.currentTab];
        if (!saved || typeof saved !== 'object') return;
        [...content.querySelectorAll('details')].forEach((e,i)=>{
            const prior=Array.isArray(saved.details) && saved.details.find(d=>d.key===(e.id || 'detail-'+i));
            if (prior && typeof prior.open === 'boolean') e.open=prior.open;
        });
        if (Array.isArray(saved.selects)) for (const item of saved.selects) {
            const element=document.getElementById(item.id);
            if (element?.tagName==='SELECT' && [...element.options].some(o=>o.value===item.value)) element.value=item.value;
        }
        [...content.querySelectorAll('.table-wrap')].forEach((e,i)=>{
            if (Number.isFinite(saved.tables?.[i]) && saved.tables[i]>=0) e.scrollLeft=saved.tables[i];
        });
        requestAnimationFrame(()=>{
            if(this._renderRevision===revision && Number.isFinite(saved.scroll) && saved.scroll>=0) window.scrollTo(0,saved.scroll);
        });
    }

    constructor() {
        this.currentTab = 'overview';
        window.addEventListener('pagehide', () => this.captureReadingState(document.getElementById('content')));
        try { const saved=JSON.parse(sessionStorage.getItem('consoleReadingStateV1') || '{}'); this._readingState=saved && !Array.isArray(saved) && typeof saved==='object' ? saved : {}; } catch { this._readingState={}; }
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
            consoleMarketClock = jsonData.market_clock || null;
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
        this.captureReadingState(content);
        const revision=this._renderRevision=(this._renderRevision || 0)+1;
        if (!this.data) { content.innerHTML = '<p class="muted">読み込み中...</p>'; return; }
        if (this.data.error) { content.innerHTML = `<div class="card"><p class="danger">エラー: ${this.data.error}</p></div>`; return; }
        
        try {
            // Release charts before replacing canvases; delayed redraws also guard below.
            if (typeof Chart !== 'undefined') content.querySelectorAll('canvas').forEach(canvas => Chart.getChart(canvas)?.destroy());
            switch (this.currentTab) {
                case 'overview':   content.innerHTML = this.renderOverview(); this.initOverviewCharts(); break;
                case 'weekly':     content.innerHTML = this.renderWeekly(); this.initWeeklyCharts(); break;
                case 'analysis':   content.innerHTML = this.renderAnalysis(); this.initAnalysisCharts(); break;
                case 'charts':     content.innerHTML = this.renderCharts(); this.initAllCharts(); break;
                case 'trading':    content.innerHTML = this.renderTrading(); break;
                case 'positions':  content.innerHTML = this.renderPositions(); break;
                case 'archives':   content.innerHTML = this.renderArchives(); break;
                case 'news':       content.innerHTML = this.renderNews(); this._initNewsFilters(); break;
                case 'cron':       content.innerHTML = this.renderCronJobs(); break;
                case 'data':       content.innerHTML = this.renderDataStatus(); break;
                case 'logs':       content.innerHTML = this.renderLogs(); break;
                case 'metrics':    content.innerHTML = this.renderMetrics(); break;
            }
            this.setupPeriodSelectors();
            this.setupProjectionPreview();
            this._renderedTab=this.currentTab;
            this.restoreReadingState(content,revision);
            
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
        ${this.renderEvidenceStatus()}
        ${this.renderOperationalEvidence()}
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
                <h3>現在の未約定注文（過去の照合履歴とは別）</h3>
                ${this.renderPendingOrdersTable((this.data.reconciliation || {}).current_pending_orders ?? (this.data.reconciliation || {}).pending_orders ?? [], (this.data.reconciliation || {}).current_orders_evidence || (this.data.reconciliation || {}).pending_orders_evidence)}
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

    renderPendingOrdersTable(data, evidence) {
        const e = evidence || {};
        const age = e.as_of ? (Date.now() - Date.parse(e.as_of)) / 1000 : NaN;
        const fresh = Number.isFinite(age) && age >= 0 && age <= 120;
        const verified = e.status === 'ok' && fresh;
        const note = `${verified ? '取得確認済み（範囲限定）' : '取得未確認・不完全または古い情報'} / ${e.reason || '取得証拠なし'} / 取得時刻: ${e.as_of ? fmt.dt(e.as_of) : '未取得'} / ${e.scope || '取得範囲不明'}`;
        const heading = `<p class="${verified ? 'muted' : 'warn'} small">${this.escapeHtml(note)}</p>`;
        if (!Array.isArray(data) || data.length === 0) {
            const completeOpen = verified && e.query_status === 'open' && e.complete === true;
            return heading + `<p class="${verified ? 'muted' : 'warn'}">${completeOpen ? '取得時点・照会口座の未約定注文なし（予約資金・全口座の認定とは別）' : verified ? '取得範囲内に対象注文なし（全未約定の網羅確認ではありません）' : '保留注文の有無は未確認'}</p>`;
        }
        const labels = {accepted:'受付済（未約定）', new:'受付済（未約定）', pending_new:'受付処理中',
            filled:'約定済', partially_filled:'一部約定', pending_cancel:'取消依頼中（未確定）',
            canceled:'取消確認済', cancelled:'取消確認済', rejected:'拒否確認済', expired:'期限切れ',
            unknown:'応答不明', unconfirmed:'注文ID対応未確認', pending_reconcile:'照合待ち', reconciled_ok:'旧照合記録のみ'};
        return heading + `<div class="table-wrap"><table><thead><tr><th>時刻</th><th>銘柄</th><th>Side</th><th>数量</th><th>状態</th><th>注文ID</th></tr></thead><tbody>${data.map(o => `<tr>
            <td>${this.escapeHtml(fmt.dt(o.ts))}</td><td>${this.escapeHtml(o.symbol || '未取得')}</td>
            <td>${this.escapeHtml(o.side || '未取得')}</td><td>${this.escapeHtml(String(finiteValue(o.qty) ?? '未取得'))}</td>
            <td>${this.escapeHtml(labels[o.status] || o.status || '未確認')}</td><td>${this.escapeHtml(String(o.order_id || '未取得'))}</td></tr>`).join('')}</tbody></table></div>`;
    }

    renderEvidenceStatus() {
        const e = this.data?.console_evidence || {};
        const current = e.status === 'current';
        const rows = Array.isArray(e.items) ? e.items : [];
        return `<details class="card" style="margin-bottom:16px" id="console-evidence">
            <summary><strong>改善・判断の確認状況</strong> <span class="${current ? 'muted' : 'warn'}">${current ? '資料時点／稼働確認とは別' : '未取得・要再確認'}</span></summary>
            <p class="small muted">文書確認: ${this.escapeHtml(fmt.dt(e.reviewed_at))} ／ ${this.escapeHtml(e.reason || '確認資料なし')}。表示更新時刻は各データの取得時刻ではありません。</p>
            <div class="table-wrap"><table><thead><tr><th>論点</th><th>資料時点の状態</th><th>確認範囲・不足</th></tr></thead><tbody>
            ${rows.map(row => `<tr><td>${this.escapeHtml(row.title || '')}</td><td class="warn">${this.escapeHtml(row.state || '未確認')}${row.source_current === false ? '（根拠変更・再確認）' : ''}</td>
                <td>${this.escapeHtml(row.detail || '')} ${/^\/api\/console-evidence\/document\?name=[a-z]+$/.test(row.url || '') ? `<a href="${row.url}" target="_blank" rel="noopener">根拠</a>` : ''}</td></tr>`).join('')}
            </tbody></table></div>
        </details>`;
    }

    renderOperationalEvidence() {
        const e = this.data?.operational_evidence || {};
        const c = e.control || {}, v = e.versions || {}, f = e.funds || {};
        const esc = value => this.escapeHtml(String(value ?? '未確認'));
        const state = {ok:'正常の記録（全BUY許可とは別）',halted:'BUY停止の記録あり',recovery_pending:'再検証待ち・BUY停止の記録あり',degraded:'縮退の記録あり'}[c.state] || '停止情報未確認';
        const age = finiteValue(c.age_seconds);
        const money = value => finiteValue(value) === null ? '未確認' : fmt.usd(value);
        return `<section class="card ops-evidence" id="operational-evidence">
            <h3>停止・監視の確認</h3>
            <p class="${c.state === 'halted' || c.status === 'missing' || c.status === 'invalid' ? 'danger' : 'warn'}"><strong>${esc(state)}</strong></p>
            <p>停止発生: ${esc(fmt.dt(c.triggered_at))} ／ 最終評価: ${esc(fmt.dt(c.as_of))} ／ 経過: ${age === null ? '未確認' : esc(Math.floor(age / 60)) + '分'}</p>
            <p class="warn">SELL監視の実行証拠：未確認（BUY停止とは別に確認）</p>
            <p class="small muted">${esc(c.source)} ／ ${esc(c.reason)}</p>
            <details><summary>適用版・資金・成績の確認範囲</summary>
                <h4>反映・実行の証拠</h4>
                <div class="table-wrap"><table><thead><tr><th>対象</th><th>現在確認できること</th><th>不足している証拠</th></tr></thead><tbody>
                    <tr><td>Console</td><td>${v.console_startup_match === true ? '起動時のファイル指紋と一致' : '起動時との一致は未確認・再反映確認が必要'}</td><td>応答・実画面検証は別途</td></tr>
                    <tr><td>売買・取消・安全是正</td><td>候補の検証状況は上の根拠資料を参照</td><td>売買ジョブの読込版・実効設定・候補配備は未照合</td></tr>
                    <tr><td>定期実行</td><td>取引タブに保存サマリーの状態を表示</td><td>scheduler実行ID・完了receiptとの独立照合</td></tr>
                </tbody></table></div>
                <p class="small muted">${esc(v.reason)}</p>
                <details><summary>Consoleファイル指紋</summary>${(v.fingerprints || []).map(row => `<p class="small">${esc(row.path)}: ${esc(row.sha256)}</p>`).join('')}</details>
                <h4>資金・注文後リスク（broker報告値と利用可能額は別）</h4>
                <p>取得: ${esc(fmt.dt(f.as_of))} ／ 状態: ${esc(f.status)}</p>
                <div class="metric"><span>cash（broker報告）</span><span>${money(f.cash)}</span></div>
                <div class="metric"><span>buying_power（broker報告）</span><span>${money(f.buying_power)}</span></div>
                ${this.renderOperationalInputs()}
                <p class="small muted">未約定の取得状態: ${esc(f.pending_status)} ／ ${esc(f.reason)}</p>
                ${this.renderMetricQualification()}
            </details>
            ${this.renderDataAvailability()}
            ${this.renderFollowthroughEvidence()}
        </section>`;
    }

    renderOperationalInputs() {
        const e=this.data?.operational_evidence || {}, f=e.capacities || {}, p=e.portfolio_inputs || {}, q=e.quality_context || {};
        const esc=v=>this.escapeHtml(String(v ?? '未確認'));
        const money=v=>finiteValue(v)===null?'未確認':f.currency==='USD'?fmt.usd(v):String(v)+' '+(f.currency || '通貨未確認');
        const pct=v=>finiteValue(v)===null?'未確認':fmt.pct(v);
        const yes=v=>v===true?'対応あり':v===false?'対応なし':'未確認';
        if(!this.projectionDraft) {
            try { this.projectionDraft=JSON.parse(sessionStorage.getItem('consoleProjectionDraftV1') || '{}'); }
            catch { this.projectionDraft={}; }
        }
        const draft=this.projectionDraft || {};
        return `<p>非信用買付余力（broker報告）: ${money(f.non_marginable_buying_power)} ／ 通貨: ${esc(f.currency)}</p>
            <p class="small muted">${esc(f.reason)}</p>
            <p>保有評価額÷equity: ${pct(p.current_gross_exposure_pct)} ／ 最大1銘柄÷equity: ${pct(p.current_largest_position_pct)}</p>
            <p>分類確認: ${esc(p.classified_positions)} / ${esc(p.total_positions)}銘柄 ／ 分類coverage：${pct(p.classification_coverage)}${p.classification_state==='empty_population'?'（保有なし・coverage率は算出しません）':''} ／ 取得: ${esc(fmt.dt(p.as_of))}</p>
            <p class="warn">予約資金・受渡済み現金・出金可能額は未確認。現在の保有比率は注文後リスクではありません。</p>
            <details id="projection-preview"><summary>指値BUYの配分試算（注文送信なし）</summary>
                <p class="small muted">価格・equity固定の概算。手数料・約定・売買許可の判定ではありません。未約定注文あり／分類不足では試算を保留します。</p>
                <form id="projection-form" style="display:flex;flex-wrap:wrap;gap:8px;align-items:end">
                    <label>銘柄<input name="symbol" required maxlength="15" value="${esc(draft.symbol || '')}" style="width:90px"></label>
                    <label>数量<input name="qty" type="number" min="0.000001" step="any" required value="${esc(draft.qty || '')}" style="width:95px"></label>
                    <label>指値<input name="price" type="number" min="0.000001" step="any" required value="${esc(draft.price || '')}" style="width:95px"></label>
                    <button type="submit">配分を試算</button>
                </form><p id="projection-result" aria-live="polite">${esc(this.projectionText || '注文案未指定のため、注文後の集中度は未確認です。')}</p>
            </details>
            <details id="quality-context"><summary>台帳・鮮度警告の根拠（判定は維持）</summary>
                <p>最終完了予定slot: ${esc(fmt.dt(q.expected_completed_slot))}</p>
                <p>保存サマリー: ${yes(q.summary_at_or_after_due)} ／ guardrail評価: ${yes(q.breaker_at_or_after_due)} ／ day-start日付: ${yes(q.day_start_matches_due_session)}</p>
                <p>台帳内隔離: ${esc(q.inline_quarantined)}行 ／ 別隔離配列: ${esc(q.separate_quarantined)}行（重複し得るため合計しません）</p>
                <p class="small muted">${esc(q.ledger_next_action)} ${esc(q.reason)}</p>
            </details>`;
    }

    setupProjectionPreview() {
        const form=document.getElementById('projection-form');
        if(!form) return;
        form.addEventListener('input',()=>{
            this.projectionDraft=Object.fromEntries(new FormData(form));
            this._projectionRevision=(this._projectionRevision || 0)+1;
            this.projectionText='注文案を変更しました。再試算するまで結果は未確認です。';
            document.getElementById('projection-result').textContent=this.projectionText;
            try { sessionStorage.setItem('consoleProjectionDraftV1',JSON.stringify(this.projectionDraft)); } catch {}
        });
        form.addEventListener('submit',async event=>{
            event.preventDefault();
            const draft=Object.fromEntries(new FormData(form));this.projectionDraft=draft;
            const revision=this._projectionRevision || 0;
            const target=document.getElementById('projection-result'), button=form.querySelector('button');
            const params=new URLSearchParams({projection_symbol:draft.symbol,projection_qty:draft.qty,projection_limit:draft.price});
            button.disabled=true;target.textContent='取得済み入力で試算中（注文送信なし）';
            try {
                const response=await fetch('/api/operational-evidence?'+params,{cache:'no-store'});
                if(!response.ok) throw new Error('unavailable');
                const body=await response.json(), p=body.portfolio_inputs || {};
                if(revision!==(this._projectionRevision || 0)) return;
                const value=finiteValue(p.projected_concentration);
                const message=p.projected_status==='limit_buy_scenario' && value!==null
                    ? `${draft.symbol} / ${draft.qty}株 / 指値${draft.price}：注文後の最大1銘柄÷equity ${fmt.pct(value)}（保有取得: ${fmt.dt(p.as_of)}・口座取得: ${fmt.dt(p.account_as_of)}）。固定価格の配分試算のみ・注文送信なし。`
                    : '未約定・分類・取得鮮度などの入力条件が不足し試算保留。注文は送信していません。';
                this.projectionText=message;
                if(target.isConnected) target.textContent=message;
            } catch(error) {
                if(revision!==(this._projectionRevision || 0)) return;
                this.projectionText='試算入力の取得・検証に失敗。結果は未確認、注文送信なし。';
                if(target.isConnected) target.textContent=this.projectionText;
            } finally { if(button.isConnected) button.disabled=false; }
        });
    }

    renderDataAvailability() {
        const rows = this.data?.operational_evidence?.data_availability;
        const labels = {available:'取得済み（表示範囲内）',failed:'取得失敗',partial:'部分取得',stale:'期限切れ・時刻要確認',
            invalid:'入力不正・要確認',not_acquired:'未取得',not_connected:'未接続',not_recorded:'未記録',
            recorded_unqualified:'記録あり・独立照合前',not_qualified:'評価条件未充足',decision_required:'基準未決'};
        const esc = value => this.escapeHtml(String(value ?? '未確認'));
        if (!Array.isArray(rows)) return '<details id="data-availability"><summary>取得状況と不足理由</summary><p class="warn">取得状態の情報は未取得です。</p></details>';
        return `<details id="data-availability"><summary>取得状況と不足理由（未取得・未接続・未記録を区別）</summary>
            <p class="small muted">再読み込みで埋まる値と、データ接続・記録・評価条件の整備が必要な値を区別しています。</p>
            <div class="table-wrap"><table><thead><tr><th>項目</th><th>状態</th><th>理由 / 次の確認</th><th>元取得時刻</th></tr></thead>
            <tbody>${rows.map(row=>`<tr><td>${esc(row.label)}</td><td class="${row.state==='available'?'muted':'warn'}">${esc(labels[row.state] || '未確認')}</td><td>${esc(row.reason)}${row.next_action?`<br>${esc(row.next_action)}`:''}</td><td>${row.as_of?esc(fmt.dt(row.as_of)):'—'}</td></tr>`).join('')}</tbody></table></div>
        </details>`;
    }

    renderFollowthroughEvidence() {
        const e = this.data?.operational_evidence?.followthrough || {};
        const p = e.position_comparison || {}, o = e.pending_risk || {}, r = e.scheduler || {};
        const i = e.research_inputs || {}, a = e.acceptance || {};
        const quantityLabel = {matched_quantity_only:'保存open数量のみ一致', mismatch:'数量差あり', quarantine_present:'隔離行あり・整合認定は保留', unknown:'未確認'};
        const esc = v => this.escapeHtml(String(v ?? '未確認'));
        const n = v => finiteValue(v) === null ? '未確認' : esc(v);
        return `<details id="followthrough-evidence"><summary>実行・照合・改善サイクルの次の確認</summary>
            <h4>定期実行の独立metadata</h4>
            ${r.source ? `<p class="small muted">取得元: ${esc(r.source)} ／ metadata取得: ${esc(fmt.dt(r.as_of))} ／ 保存確認記録: ${esc(r.saved_review_status)}</p>` : ''}
            <p>${r.registered_job_observed === true ? '登録ジョブのmetadata取得済み' : '登録ジョブのmetadata未確認'} ／ 最終状態: ${esc(r.last_scheduler_status)} ／ 時刻: ${esc(fmt.dt(r.last_scheduler_at))}</p>
            <p>保持ログと保存サマリーrun: ${r.application_run_linked === true ? '対応確認（当該1回のみ）' : '未確認'}</p>
            <p class="warn">${esc(r.reason || '実行ID・実効設定・SELL実行は未確認')}</p>
            ${Array.isArray(r.rows) && r.rows.length ? `<div class="table-wrap"><table><thead><tr><th>売買ジョブ</th><th>有効</th><th>最終実行（scheduler申告）</th><th>最終結果（約定とは別）</th></tr></thead><tbody>${r.rows.map(row=>`<tr><td>${esc(row.name)}</td><td>${row.enabled===true?'有効':row.enabled===false?'無効':'未確認'}</td><td>${esc(fmt.dt(row.last_run))}</td><td>${esc(row.last_status)}</td></tr>`).join('')}</tbody></table></div>` : ''}
            <h4>保存open数量との限定比較</h4>
            <p class="warn">${esc(quantityLabel[p.status] || '未確認')} ／ 数量差の銘柄数: ${n(p.mismatch_count)} ／ 口座取得: ${esc(fmt.dt(p.broker_as_of))}</p>
            <p class="small">${esc(p.scope)} ${esc(p.reason)}</p>
            <h4>取得範囲内の注文残</h4>
            <p>未完了: ${n(o.observed_active_orders)} ／ 取消待ち: ${n(o.pending_cancel)} ／ 価格未確定のBUY: ${n(o.unpriced_buy_orders)}</p>
            <p>観測したlimit買い残の概算: ${finiteValue(o.observed_limit_buy_notional) === null ? '未確認' : fmt.usd(o.observed_limit_buy_notional)}</p>
            <p class="small warn">${esc(o.scope)} ${esc(o.reason)}</p>
            <p class="small">理由コード: ${esc(o.reason_code)} ／ 読取行: ${n(o.observed_rows)} / 上限${n(o.query_limit)} ／ 次の確認: ${esc(o.next_action)}</p>
            <h4>凍結した研究入力の充足</h4>
            <p>見送り: ${n(i.deny_exact_snapshots)} / ${n(i.deny_decisions)} ／ SELL: ${n(i.sell_exact_snapshots)} / ${n(i.sell_decisions)}（判断と同actionのsnapshot）</p>
            <p class="warn">出口の直接対応: ${i.exit_direct_link === true ? '資料の直接対応あり・実効性は別' : '未確認'} ／ 正式比較: 未開始・資格未認定</p>
            <p>採用値の未決数: ${Array.isArray(a.missing_fields) ? esc(a.missing_fields.length) : '未確認'}。${esc(a.reason)}（主要16項目の点検で、記入表全体の未決総数ではありません。）</p>
            <details id="acceptance-missing-fields"><summary>未決項目・単位・担当（入力/採用操作なし）</summary>
            <p><a href="/api/console-evidence/document?name=worksheet" target="_blank" rel="noopener">正本の採用値記入表</a></p>
            ${Array.isArray(a.missing_details) ? `<div class="table-wrap"><table><thead><tr><th>項目 / key</th><th>単位</th><th>担当</th></tr></thead><tbody>${a.missing_details.map(row=>`<tr><td>${esc(row.label)}<br><span class="small">${esc(row.key)}</span></td><td>${esc(row.unit)}</td><td>${esc(row.owner)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="warn">記入表の入力未取得・未確認</p>'}
            </details>
            <ol>${(e.next_actions || []).map(x=>`<li>${esc(x)}</li>`).join('')}</ol>
        </details>`;
    }

    renderRunEvidence() {
        const r = this.data?.operational_evidence?.run || {};
        const cfg = this.data?.operational_evidence?.config_instances || {};
        const cfgLabels = {observed:'観測済みの申告',not_reached:'未到達',unavailable:'観測不可',construction_failed:'設定生成失敗',changed_since_capture:'取得後の変更あり'};
        return `<div class="card ops-evidence" id="run-evidence"><h3>実行・実効設定の証拠</h3>
            <p>保存サマリー: ${this.escapeHtml(r.status || '未確認')} ／ 結果申告: ${this.escapeHtml(r.result || '未確認')} ／ 時刻: ${this.escapeHtml(fmt.dt(r.as_of))}</p>
            <p class="warn">定期実行との独立照合：未確認 ／ 売買ジョブの実効設定・読込版：未照合</p>
            <p class="small muted">${this.escapeHtml(r.reason || '実行証拠未取得')}（24時間は表示用の参照窓で、売買の停止条件ではありません。）</p>
            <details id="config-instance-evidence"><summary>設定インスタンスの観測記録（全設定の証明ではありません）</summary>
                <p class="small muted">${this.escapeHtml(cfg.reason || '設定観測receipt未取得。未記録・OFFを成功扱いしません。')}</p>
                ${(cfg.rows || []).length ? `<div class="table-wrap"><table><thead><tr><th>設定family</th><th>観測状態</th><th>記録の申告 / field数</th><th>source指紋</th></tr></thead><tbody>${cfg.rows.map(row=>`<tr><td>${this.escapeHtml(row.family)}</td><td class="warn">${this.escapeHtml(cfgLabels[row.status] || '未確認')}</td><td>${row.recorded === true ? '記録済みの申告' : '未記録'} / ${this.escapeHtml(String(row.field_count ?? '未確認'))}</td><td class="small">${this.escapeHtml(row.source_sha256 || '未確認')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="warn">設定観測receipt未取得・要確認</p>'}
            </details>
        </div>`;
    }

    renderResearchEvidence() {
        const e = this.data?.operational_evidence?.research || {};
        const labels = {observing:'観測結果の保存記録あり',disabled:'観測無効の記録',error:'観測エラーの記録',stale:'古いサマリー・現在の観測は未確認',invalid:'観測契約を確認できません'};
        const count = e.status === 'observing' ? finiteValue(e.observations) : null;
        const esc = value => this.escapeHtml(String(value ?? '未確認'));
        return `<div class="card ops-evidence" id="research-evidence"><h3>購入停止銘柄の観測・再検証</h3>
            <p class="warn">${esc(labels[e.status] || '観測結果未取得')} ／ 最終サマリー: ${esc(fmt.dt(e.as_of))}</p>
            <p>捕捉件数: ${count === null ? '未確認' : esc(count)} ／ 定期実行照合: 未確認</p>
            <p class="small muted">観測版: ${esc(e.protocol || '未確認')}${e.legacy ? ` ／ 旧版は履歴のみ ${esc(e.legacy.observations)}件（新版へ合算・転記しません）` : ''}</p>
            <p class="small">${esc(e.reason || '有効化・実行・捕捉・成熟評価は別。日数経過では解除しません。')}</p>
            ${(e.rows || []).length ? `<div class="table-wrap"><table><thead><tr><th>銘柄 / 戦略</th><th>cohort（合算しない）</th><th>成熟 / 待機 / 必要</th><th>判定記録</th></tr></thead><tbody>${e.rows.map(row => `<tr><td>${esc(row.symbol)} / ${esc(row.strategy_id)}</td><td>${esc(row.cohort)}</td><td>${esc(row.completed)} / ${esc(row.pending)} / ${esc(row.required)}</td><td>${esc({collecting:'蓄積中',deferred:'保留',review_candidate:'再検証候補・解除不可'}[row.status])}</td></tr>`).join('')}</tbody></table></div>` : ''}
            <p class="warn">次の判断：同一版・同一cohortの必要件数/既定条件と、本来のExit・費用・損失制御の検証を確認。自動解除なし。</p>
        </div>`;
    }

    renderMetricQualification() {
        const q = this.data?.operational_evidence?.qualification || {};
        return `<div class="ops-qualification"><h4>成績・費用の評価資格</h4>
            <p class="warn">成績は参考集計。正式な日次時価DD・費用控除後の収益・実請求額：未確認</p>
            <p>保存サマリー: ${this.escapeHtml(q.summary_status || '未確認')} ／ 台帳品質の申告: ${this.escapeHtml(q.reported_ledger_status || '未確認')} ／ 時刻: ${this.escapeHtml(fmt.dt(q.as_of))}</p>
            <p class="small muted">${this.escapeHtml(q.reason || '評価資格未確認。記録cost=0を無料扱いしません。')}</p>
        </div>`;
    }

    renderRunResult(run) {
        const labels = {ok: '処理成功記録あり（約定・利益の証明ではない）', error: '失敗記録あり',
            degraded: '縮退・要確認', completed_unverified: '終了記録のみ・正常性未確認', unconfirmed: '結果未確認'};
        const state = run.result_status || 'unconfirmed';
        return `<span class="${state === 'error' ? 'danger' : 'warn'}">${this.escapeHtml(labels[state] || '結果未確認')}</span>`;
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
                ${alerts.map(a => {
                    // 長期保有アラートにシンボル詳細を展開
                    let detailHtml = '';
                    if (a.message && a.message.includes('held for 10+')) {
                        const pos = this.data?.positions?.positions || [];
                        const longHold = pos.filter(p => (p.holding_days || 0) >= 10)
                            .sort((a, b) => (b.holding_days || 0) - (a.holding_days || 0));
                        if (longHold.length > 0) {
                            detailHtml = `<div class="alert-detail-table" style="margin-top:8px">
                                <table style="width:100%;font-size:12px;border-collapse:collapse">
                                    <thead><tr style="opacity:.7">
                                        <th style="text-align:left;padding:2px 6px">シンボル</th>
                                        <th style="text-align:right;padding:2px 6px">保有日数</th>
                                        <th style="text-align:right;padding:2px 6px">含み損益</th>
                                        <th style="text-align:right;padding:2px 6px">ストップまで</th>
                                    </tr></thead>
                                    <tbody>${longHold.map(p => {
                                        const pct = (p.unrealized_pnl_pct || 0) * 100;
                                        const pClass = pct >= 0 ? 'color:#10b981' : 'color:#ef4444';
                                        const dist = p.dist_to_stop_pct;
                                        const dClass = dist == null ? '' : dist < 2 ? 'color:#ef4444' : dist < 4 ? 'color:#f59e0b' : 'color:#10b981';
                                        return `<tr style="border-top:1px solid rgba(255,255,255,.06)">
                                            <td style="padding:3px 6px"><strong>${this.escapeHtml(p.symbol)}</strong></td>
                                            <td style="text-align:right;padding:3px 6px">${(p.holding_days||0).toFixed(0)}日</td>
                                            <td style="text-align:right;padding:3px 6px;${pClass}">${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%</td>
                                            <td style="text-align:right;padding:3px 6px;${dClass}">${dist != null ? '▲' + dist.toFixed(1) + '%' : '—'}</td>
                                        </tr>`;
                                    }).join('')}</tbody>
                                </table>
                            </div>`;
                        }
                    }
                    return `<div class="alert alert-${a.severity}">
                        <div class="alert-head">
                            ${this.renderSeverityBadge(a.severity)}
                            <strong>${this.escapeHtml(a.title || a.code)}</strong>
                        </div>
                        <div class="alert-message">${this.escapeHtml(a.message || '')}</div>
                        ${detailHtml}
                        ${a.action_hint ? `<div class="muted small">対応: ${this.escapeHtml(a.action_hint)}</div>` : ''}
                    </div>`;
                }).join('')}
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
        const latestEquity = finiteValue(account.equity);
        const cash = finiteValue(account.cash);
        const cashPct = latestEquity > 0 && cash !== null ? cash / latestEquity : null;
        const positionPct = latestEquity > 0 && cash !== null ? (latestEquity - cash) / latestEquity : null;
        const unrealized = finiteValue(ps.unrealized_pnl), realized = finiteValue(ts.cumulative_realized_pnl);
        const totalPnL = unrealized !== null && realized !== null ? unrealized + realized : null;
        const winRate = finiteValue(ts.win_rate);
        const maxDD = finiteValue(ts.max_drawdown_pct);

        // 元本比較
        const tracking = this.data?.trading?.summary?.tracking_context || {};
        const baseline = finiteValue(tracking.baseline_equity);
        const vsBaseline = latestEquity !== null && baseline !== null ? latestEquity - baseline : null;
        const vsBaselinePct = baseline > 0 && vsBaseline !== null ? vsBaseline / baseline : null;
        const vsBaselineClass = vsBaseline === null ? 'muted' : vsBaseline >= 0 ? 'success' : 'danger';
        const vsBaselineSign = vsBaseline !== null && vsBaseline >= 0 ? '+' : '';

        return `
        <div class="grid">
            <div class="card performance-card ${vsBaseline === null ? '' : vsBaseline >= 0 ? 'success-border' : 'danger-border'}">
                <h3>💰 資産総額</h3>
                <div class="metric big-metric">
                    <span class="value huge ${vsBaselineClass}">${fmt.usd(latestEquity)}</span>
                </div>
                <div class="metric" style="margin-top:4px">
                    <span class="label">元本（${fmt.usd(baseline)}）比</span>
                    <span class="value ${vsBaselineClass}" style="font-size:1.15em;font-weight:700">
                        ${vsBaselineSign}${fmt.usd(vsBaseline)}&nbsp;(${vsBaselineSign}${vsBaselinePct === null ? '未取得' : (vsBaselinePct*100).toFixed(2) + '%'})
                    </span>
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
            
            <div class="card performance-card ${totalPnL === null ? '' : totalPnL >= 0 ? 'success-border' : 'danger-border'}">
                <h3>📊 損益</h3>
                <div class="metric big-metric">
                    <span class="value huge ${totalPnL === null ? 'muted' : totalPnL >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(totalPnL)}</span>
                </div>
                <div class="metric"><span class="label">含み損益</span><span class="value ${unrealized === null ? 'muted' : unrealized >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ps.unrealized_pnl)}</span></div>
                <div class="metric"><span class="label">確定損益</span><span class="value ${realized === null ? 'muted' : realized >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(ts.cumulative_realized_pnl)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">PnL比率 (vs Equity)</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${totalPnL === null ? 'muted' : totalPnL >= 0 ? 'success' : 'danger'}" style="width: ${totalPnL !== null && latestEquity > 0 ? Math.min(Math.abs(totalPnL / latestEquity) * 100, 100) : 0}%"></div>
                    </div>
                    <div class="progress-value">${fmt.pct(totalPnL !== null && latestEquity > 0 ? totalPnL / latestEquity : null)}</div>
                </div>
            </div>
            
            <div class="card performance-card ${winRate >= 0.6 ? 'success-border' : 'warn-border'}">
                <h3>🎯 取引成績</h3>
                <div class="metric"><span class="label">総取引数</span><span class="value">${ts.total_trades ?? '未取得'}</span></div>
                <div class="metric"><span class="label">オープン</span><span class="value">${ts.open_trades ?? '未取得'}</span></div>
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
                <div class="metric"><span class="label">最大DD（参考値）</span><span class="value ${maxDD === null ? 'muted' : 'warn'}">${maxDD === null ? '未計測' : fmt.pct(maxDD)}</span></div>
                <p class="small muted">正式DD：評価資格未確認</p>
                <div class="metric"><span class="label">Exposure比率</span><span class="value">${fmt.pct(positionPct)}</span></div>
                <div class="progress-bar-container">
                    <div class="progress-label">Drawdownレベル</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${maxDD === null ? 'muted' : 'warn'}" style="width: ${maxDD === null ? 0 : Math.max(0, Math.min(100, maxDD * 100))}%"></div>
                    </div>
                    <div class="progress-value">${maxDD === null ? '未計測' : fmt.pct(maxDD)}</div>
                </div>
            </div>
            
            <div class="card">
                <h3>📡 意思決定</h3>
                <div class="metric"><span class="label">Decisions</span><span class="value">${this.data?.data_status?.counts?.decisions ?? '未取得'}</span></div>
                <div class="metric"><span class="label">Signals</span><span class="value">${this.data?.data_status?.counts?.signals ?? '未取得'}</span></div>
                <div class="metric"><span class="label">Orders</span><span class="value">${this.data?.data_status?.counts?.orders ?? '未取得'}</span></div>
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
${this.renderCronSummary()}
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
            ${this.renderMarketRegimeCard()}
        </div>`;
    }

    // R11 follow-up (2026-08-15): read-only market chop/regime panel.
    // See src/stock_swing/risk/market_regime_indicator.py module docstring
    // and docs/console_improvement_tasks.md "R11-B付随"/"R11-C付随" sections
    // for the full rationale. Observability only -- never blocks or
    // resizes anything, mirrors the Plan B-E shadow-diagnostic panels.
    renderMarketRegimeCard() {
        const mr = this.data?.market_regime;
        if (!mr || mr.insufficient_data) {
            return `<div class="card">
                <h3>🌐 市場レジーム（SPY）</h3>
                <p class="muted small">データ不足（ベンチマークキャッシュ未取得または履歴不足）</p>
            </div>`;
        }
        const labelMap = {
            trending_bullish: ['📈 上昇トレンド', 'success'],
            trending_bearish: ['📉 下降トレンド', 'warn'],
            neutral: ['➡️ 中立', 'muted'],
            transitional: ['⚠️ 推移中', 'warn'],
            'choppy (mixed trend + wide range)': ['🌀 チョップ相場', 'danger'],
        };
        const [label, cls] = labelMap[mr.regime_label] || [mr.regime_label, 'muted'];
        const chopScore = mr.chop_score ?? 0;
        const chopCls = chopScore >= 60 ? 'danger' : chopScore >= 35 ? 'warn' : 'success';
        return `<div class="card">
            <h3>🌐 市場レジーム（${this.escapeHtml(mr.regime_symbol || 'SPY')}） <span class="muted small" style="font-weight:normal">（参考情報のみ、自動ブロックなし）</span></h3>
            <div class="metric"><span class="label">状態</span><span class="${cls}">${label}</span></div>
            <div class="metric"><span class="label">Chop Score</span><span class="${chopCls}">${chopScore.toFixed(0)}/100</span></div>
            <div class="metric"><span class="label">終値 vs SMA</span><span class="small">${(mr.latest_close ?? 0).toFixed(2)} ${mr.above_sma ? '≥' : '<'} ${(mr.sma_short ?? 0).toFixed(2)}</span></div>
            <div class="metric"><span class="label">20日レンジ幅</span><span class="small">${(mr.range_width_pct ?? 0).toFixed(1)}%</span></div>
            <p class="muted small" style="margin-top:6px">2026-08-15のR11検証で、モメンタム戦略はチョップ相場で一時的に機能低下することが判明（対策は部分緩和のみ）。自動制御はしない。</p>
        </div>`;
    }

    renderDataCountsCompact(counts) {
        if (!counts) return '<p class="muted">データなし</p>';
        return Object.entries(counts).map(([stage, count]) => 
            `<div class="metric"><span class="label">${stage}</span><span class="value ${count > 0 ? '' : 'muted'}">${count}</span></div>`
        ).join('');
    }

    renderReconciliationSummary(rec = {}) {
        const order = rec.current_orders_evidence || rec.pending_orders_evidence || {}, history = rec.history_evidence || {};
        const states = rec.current_orders || {};
        const age = order.as_of ? (Date.now()-Date.parse(order.as_of))/1000 : NaN;
        const qualified = order.status==='ok' && Number.isFinite(age) && age>=0 && age<=120;
        const count = value => finiteValue(value) ?? '未確認';
        const esc = value => this.escapeHtml(String(value ?? '未確認'));
        return `<div id="reconciliation-evidence">
            <div class="metric"><span>現在の未解決不一致</span><span class="value warn">未確認・要確認</span></div>
            <p class="small warn">現在の全保有/全未約定を同時点で照合した結果は未認定です。</p>
            <div class="metric"><span>未約定 / 取消待ち / 一部約定</span><span>${qualified?count(states.open):'未確認'} / ${qualified?count(states.pending_cancel):'未確認'} / ${qualified?count(states.partial):'未確認'}</span></div>
            <div class="metric"><span>その他の未完了状態</span><span>${qualified?count(states.other):'未確認'}</span></div>
            <p class="small ${qualified?'muted':'warn'}">注文取得（範囲限定）: ${esc(order.status)} ／ ${esc(fmt.dt(order.as_of))} ／ ${esc(order.scope)}</p>
            <details><summary>過去ログの照合イベント（現在の未解決件数ではありません）</summary>
                <div class="metric"><span>照合記録 / 不一致等のイベント</span><span>${history.status==='ok'||history.status==='partial'?count(rec.recent_reconciliations):'未確認'} / ${history.status==='ok'||history.status==='partial'?count(rec.pending_or_mismatched):'未確認'}</span></div>
                <p class="small muted">${esc(history.status)} ／ ${esc(history.scope)} ／ ${esc(fmt.dt(history.oldest_at))} → ${esc(fmt.dt(history.as_of))}</p>
                <p class="small muted">履歴の最終成功申告: ${esc(fmt.dt(rec.last_success))} ／ ${esc(history.reason)}</p>
            </details>
            <p class="small">次の確認：${esc(rec.next_action || '口座/台帳の同時点・対象範囲・未解決状態を確認。履歴件数を現在の状態に読み替えません。')}</p>
        </div>`;
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
            return `${this.renderRunEvidence()}${this.renderResearchEvidence()}${this.renderMetricQualification()}<div class="card"><p class="muted">取引データが利用できません。${this.escapeHtml(td.error||'')}</p></div>`;
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
        ${this.renderRunEvidence()}
        ${this.renderResearchEvidence()}
        ${this.renderMetricQualification()}
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

        // データパイプライン詳細
        const ds = this.data?.data_status || {};
        const counts = ds.counts || {};
        const freshness = ds.freshness || {};
        const raw = counts.raw || 0;
        const norm = counts.normalized || 0;
        const normRate = raw > 0 ? (norm / raw * 100) : 0;
        const normStatus = freshness.normalized?.status || 'unknown';
        const normAge = freshness.normalized?.age_hours;
        const decAge = freshness.decisions?.age_hours;
        const normRateClass = normRate < 1 ? 'danger' : normRate < 20 ? 'warn' : 'success';
        const normValid = finiteValue(normAge) !== null && normAge >= 0;
        const normStaleClass = normValid && normStatus === 'fresh' ? 'success' : normStatus === 'stale' ? 'danger' : 'warn';
        const decValid = finiteValue(decAge) !== null && decAge >= 0;
        const decAgeClass = decValid && freshness.decisions?.status === 'fresh' ? 'success' : decValid && decAge > 24 ? 'danger' : 'warn';

        const pipelineStageHtml = `
        <div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">🔄 データパイプライン詳細</h4>
            <p class="small muted">ファイル更新/記録時刻と市場価格の時刻・画面更新は別。鮮度不明を正常にせず、取得元と時刻を確認してください。</p>
            <div class="funnel-reason-row">
                <span class="funnel-reason-label">📥 raw → normalized 変換率</span>
                <span class="funnel-reason-count ${normRateClass}">${norm.toLocaleString()} / ${raw.toLocaleString()} (${normRate.toFixed(1)}%)</span>
            </div>
            <div class="funnel-reason-row">
                <span class="funnel-reason-label">🕒 normalized鮮度（ファイル更新）</span>
                <span class="funnel-reason-count ${normStaleClass}">${normValid ? Number(normAge).toFixed(0) + 'h 前' : '—'} (${this.escapeHtml(normStatus)})</span>
            </div>
            <div class="funnel-reason-row">
                <span class="funnel-reason-label">🧠 Decision鮮度（記録時刻）</span>
                <span class="funnel-reason-count ${decAgeClass}">${decValid ? Number(decAge).toFixed(1) + 'h 前' : '—'}</span>
            </div>
            <div class="funnel-reason-row">
                <span class="funnel-reason-label">📁 features / signals / decisions</span>
                <span class="funnel-reason-count">${counts.features || 0} / ${counts.signals || 0} / ${counts.decisions || 0}</span>
            </div>
        </div>`;

        // NOTE (2026-08-04): funnel.decisions is capped at the 500 most
        // recent decision files (DashboardService._load_recent_decisions),
        // used for the by_strategy/by_symbol/deny-reason breakdowns below.
        // Once total lifetime decisions exceed 500 this metric will always
        // read exactly 500 -- that is expected, not a data bug. The true
        // lifetime decision file count is shown separately via
        // counts.decisions in the "features / signals / decisions" row below.
        return `
        <div class="grid funnel-grid">
            <div class="funnel-item"><div>
                <div class="perf-label">Decisions (直近500件)</div>
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
        </div>` : ''}
        ${pipelineStageHtml}
        ${this._renderDenyBySymbol(p)}
        ${this._renderBuyStopList(funnel)}
        ${this._renderSmallSampleWatchlist(funnel)}
        ${this._renderClusterExposure(funnel)}
        ${this._renderPromotionReadiness(funnel)}
        ${this._renderPaperRuns(p)}`;
    }

    // R6-v2 C5 (2026-08-27): the last remaining item from the original
    // 2026-06-25 C-batch plan ("Risk Dashboard -- ETF/株 別昇格状態 ← R5と
    // 並行"). R5-v2's promotion_gate.py criteria (cluster cap / top5
    // concentration / portfolio beta / clean-cohort PF / pairwise
    // correlation) were implemented 2026-08-14 but only ever surfaced via
    // scripts/check_go_no_go.py or daily cron JSON snapshots -- never here.
    // Read-only, recommendation-only, mirrors _renderClusterExposure above.
    _renderPromotionReadiness(funnel) {
        const pr = funnel.promotion_readiness;
        if (!pr || !pr.available) return '';

        const criteria = pr.criteria || [];
        const rows = criteria.map(c => {
            const icon = c.passed ? '✅' : '❌';
            const actual = Array.isArray(c.actual) ? c.actual.join(', ') : (c.actual ?? '—');
            return `<tr>
                <td>${icon} <strong>${this.escapeHtml(c.name || '—')}</strong></td>
                <td class="small">${this.escapeHtml(String(actual))}</td>
                <td class="small muted">${this.escapeHtml(c.required || '—')}</td>
                <td class="small muted">${this.escapeHtml(c.detail || '')}</td>
            </tr>`;
        }).join('');

        const overallCls = pr.all_pass ? 'success' : 'danger';
        const overallLabel = pr.all_pass ? '✅ ALL PASS' : `❌ FAILING: ${(pr.failing || []).join(', ')}`;

        const acPf = pr.asset_class_pf || {};
        const acRows = Object.keys(acPf).length > 0
            ? Object.entries(acPf).map(([ac, m]) => {
                const pfVal = m.profit_factor;
                const pfStr = (pfVal === null || pfVal === undefined) ? '—' : (typeof pfVal === 'number' ? pfVal.toFixed(3) : pfVal);
                const wr = m.win_rate != null ? (m.win_rate * 100).toFixed(1) + '%' : '—';
                return `<span class="small" style="margin-right:16px">${ac.toUpperCase()}: n=${m.count} PF=${pfStr} WR=${wr}</span>`;
            }).join('')
            : '<span class="muted small">データなし</span>';

        return `
        <div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">📊 PROMOTION GATE READINESS <span class="muted small" style="font-weight:normal">（R5-v2、recommendation-only、Go/No-Go判断の補助情報）</span></h4>
            <div class="${overallCls}" style="margin-bottom:8px"><strong>${overallLabel}</strong></div>
            <div class="table-wrap"><table><thead><tr>
                <th>条件</th><th>実測値</th><th>基準</th><th>詳細</th>
            </tr></thead><tbody>${rows}</tbody></table></div>
            <div style="margin-top:8px">${acRows}</div>
        </div>`;
    }

    _renderPaperRuns(pipeline) {
        const runs = (pipeline.runs || []).slice(0, 10);
        if (runs.length === 0) return '';
        return `<div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">📝 paper_demo 実行ログ（直近10件）</h4>
            <div class="table-wrap"><table><thead><tr>
                <th>開始時刻</th>
                <th>処理終了</th><th>結果</th>
                <th style="text-align:right">Decisions</th>
                <th style="text-align:right">提出</th>
                <th style="text-align:right">変換率</th>
            </tr></thead><tbody>
            ${runs.map(r => {
                const started = (r.started_at || '').slice(0, 16).replace('T', ' ');
                const completed = r.completed_at ? '終了記録あり' : '<span class="warn">終了記録なし</span>';
                const rate = r.conversion_rate || 0;
                const rateClass = rate > 0.1 ? 'success' : rate > 0 ? 'warn' : 'muted';
                return `<tr>
                    <td class="small">${this.escapeHtml(started)} UTC</td>
                    <td class="small">${completed}</td><td class="small">${this.renderRunResult(r)}</td>
                    <td style="text-align:right">${r.decisions || 0}</td>
                    <td style="text-align:right ${r.submitted > 0 ? '" class="success' : ''}">${r.submitted || 0}</td>
                    <td style="text-align:right" class="${rateClass}">${(rate * 100).toFixed(0)}%</td>
                </tr>`;
            }).join('')}
            </tbody></table></div>
        </div>`;
    }

    _renderBuyStopList(funnel) {
        const list = funnel.buy_stop_list || [];
        if (list.length === 0) return '';

        const reasonLabel = (reason) => {
            if (reason === 'stock_reduced')   return '🔍 stock_reduced';
            if (reason === 'rolling_pf_gate') return '📉 PF gate';
            return reason || '—';
        };

        const rows = list.map(item => {
            const pf = item.profit_factor;
            const pfStr = pf != null ? pf.toFixed(3) : '—';
            const pfCls = pf == null ? '' : pf < 0.10 ? 'danger' : pf < 0.50 ? 'warn' : 'success';
            return `<tr>
                <td><strong>${this.escapeHtml(item.symbol || '—')}</strong></td>
                <td class="small">${item.n_trades ?? '—'}</td>
                <td class="small ${pfCls}">${pfStr}</td>
                <td class="small">${this.escapeHtml(reasonLabel(item.reason))}</td>
                <td class="small muted">${this.escapeHtml(item.reason_detail || '—')}</td>
            </tr>`;
        }).join('');

        return `
        <div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">🚫 BUY STOP LIST <span class="muted small" style="font-weight:normal">（永続ブロック中 ${list.length}件）</span></h4>
            <div class="table-wrap"><table><thead><tr>
                <th>銘柄</th><th>取引数</th><th>PF</th><th>理由</th><th>詳細</th>
            </tr></thead><tbody>${rows}</tbody></table></div>
        </div>`;
    }

    // 2026-08-06: small_sample_watchlist was already computed on the backend
    // (2026-08-05, entry_filter.get_small_sample_watchlist) and wired into
    // the CLI console summary, but had no web dashboard panel. Read-only
    // observability — never blocks anything.
    _renderSmallSampleWatchlist(funnel) {
        const list = funnel.small_sample_watchlist || [];
        if (list.length === 0) return '';

        const rows = list.map(item => {
            const wr = item.win_rate;
            const wrStr = wr != null ? (wr * 100).toFixed(0) + '%' : '—';
            const pnl = item.net_pnl;
            const pnlStr = pnl != null ? pnl.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : '—';
            return `<tr>
                <td><strong>${this.escapeHtml(item.symbol || '—')}</strong></td>
                <td class="small">${item.n_trades ?? '—'}</td>
                <td class="small danger">${pnlStr}</td>
                <td class="small">${wrStr}</td>
                <td class="small muted">${this.escapeHtml(item.note || '—')}</td>
            </tr>`;
        }).join('');

        return `
        <div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">⚠️ SMALL-SAMPLE WATCHLIST <span class="muted small" style="font-weight:normal">（n=2〜4、既に赤字、自動ブロック対象外・手動判断推奨 ${list.length}件）</span></h4>
            <div class="table-wrap"><table><thead><tr>
                <th>銘柄</th><th>取引数</th><th>Net PnL</th><th>勝率</th><th>備考</th>
            </tr></thead><tbody>${rows}</tbody></table></div>
        </div>`;
    }

    // R5-v2 (2026-08-14): correlation_cluster.compute_cluster_exposures() was
    // already enforced as a hard BUY block in paper_demo (P4-B) but had zero
    // visibility in the web dashboard -- only indirect via deny_reasons text.
    // Read-only observability, mirrors _renderSmallSampleWatchlist above.
    _renderClusterExposure(funnel) {
        const list = funnel.cluster_exposure || [];
        if (list.length === 0) return '';

        const rows = list.map(item => {
            const util = item.utilization_pct ?? 0;
            const utilCls = item.over_cap ? 'danger' : util >= 80 ? 'warn' : 'success';
            const symbols = (item.symbols || []).join(', ');
            return `<tr>
                <td><strong>${this.escapeHtml(item.cluster_name || '—')}</strong></td>
                <td class="small">${(item.current_notional ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}</td>
                <td class="small">${(item.cap_notional ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}</td>
                <td class="small ${utilCls}">${util.toFixed(0)}%${item.over_cap ? ' 🚫' : ''}</td>
                <td class="small muted">${this.escapeHtml(symbols)}</td>
            </tr>`;
        }).join('');

        return `
        <div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">🔗 CORRELATION CLUSTER EXPOSURE <span class="muted small" style="font-weight:normal">（BUY自動ブロックは既存実装、本パネルは可視化のみ ${list.length}件）</span></h4>
            <div class="table-wrap"><table><thead><tr>
                <th>クラスタ</th><th>現在エクスポージャー</th><th>上限</th><th>使用率</th><th>構成銘柄</th>
            </tr></thead><tbody>${rows}</tbody></table></div>
        </div>`;
    }

    _renderDenyBySymbol(pipeline) {
        const bySymbol = (pipeline.by_symbol || []);
        const denied = bySymbol
            .filter(s => (s.deny || 0) > 0)
            .sort((a, b) => (b.deny || 0) - (a.deny || 0))
            .slice(0, 8);
        if (denied.length === 0) return '';
        return `<div class="card" style="margin-top:8px">
            <h4 style="margin:0 0 8px">🔁 Deny 多発シンボル</h4>
            <div class="table-wrap"><table><thead><tr>
                <th>シンボル</th><th style="text-align:right">Deny件数</th><th style="text-align:right">Pass件数</th><th style="text-align:right">率</th>
            </tr></thead><tbody>
            ${denied.map(s => {
                const deny = s.deny || 0;
                const pass = s.pass || 0;
                const total = deny + pass;
                const denyRate = total > 0 ? (deny / total * 100).toFixed(0) : 0;
                const rateClass = denyRate >= 80 ? 'danger' : denyRate >= 50 ? 'warn' : '';
                return `<tr>
                    <td><strong>${this.escapeHtml(s.symbol)}</strong></td>
                    <td style="text-align:right" class="danger">${deny}</td>
                    <td style="text-align:right" class="success">${pass}</td>
                    <td style="text-align:right" class="${rateClass}">${denyRate}%</td>
                </tr>`;
            }).join('')}
            </tbody></table></div>
        </div>`;
    }

    renderRecentTrades(data) {
        if (!data || data.length === 0) return '<p class="muted">取引履歴なし</p>';
        // 最新の取引が上に来るようにソート
        const sortedData = [...data].sort((a, b) => {
            const dateA = new Date(a.exit_time || a.entry_time || 0);
            const dateB = new Date(b.exit_time || b.entry_time || 0);
            return dateB - dateA; // 降順（最新が上）
        });
        const exitReasonBadge = (reason) => {
            if (!reason) return '<span class="muted">—</span>';
            const cls = reason === 'trailing_stop' ? 'success'
                      : reason === 'stop_loss'     ? 'danger'
                      : reason === 'breakeven_stop' ? 'warn'
                      : reason === 'time_based'    ? 'warn'
                      : 'unknown';
            const label = reason.replace(/_/g, '\u00a0');
            return `<span class="badge badge-${cls}">${this.escapeHtml(label)}</span>`;
        };
        return `<div class="table-wrap"><table><thead><tr>
            <th>日付</th><th>シンボル</th><th>Exit理由</th><th>PnL</th><th>リターン</th><th>ESS</th><th>保有日数</th><th>エントリー</th><th>エグジット</th>
        </tr></thead><tbody>
        ${sortedData.map(trade => `
            <tr>
                <td class="small muted">${(trade.exit_time || trade.entry_time || '').slice(0,10)}</td>
                <td><strong>${this.escapeHtml(trade.symbol)}</strong></td>
                <td>${exitReasonBadge(trade.exit_reason)}</td>
                <td class="${(trade.pnl || 0) >= 0 ? 'success' : 'danger'}">${fmt.usdSigned(trade.pnl || 0)}</td>
                <td class="${(trade.return_pct || 0) >= 0 ? 'success' : 'danger'}">${fmt.pctSigned(trade.return_pct || 0)}</td>
                ${this.essCell(trade.entry_signal_strength ?? null)}
                <td class="small">${trade.holding_days != null ? (+trade.holding_days).toFixed(1) + '日' : '—'}</td>
                <td class="small">${fmt.usd(trade.entry_price)}</td>
                <td class="small">${trade.exit_price ? fmt.usd(trade.exit_price) : '—'}</td>
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

    renderMarketStatusCard(marketStatus) {
        if (!marketStatus) return '';
        const badges = {
            regular: { icon: '\u{1F7E2}', label: 'MARKET OPEN' },
            pre_market: { icon: '\u{1F305}', label: 'PRE-MARKET' },
            after_hours: { icon: '\u{1F319}', label: 'AFTER-HOURS' },
            closed: { icon: '\u23F8', label: 'MARKET CLOSED' },
        };
        const badge = badges[marketStatus.status] || { icon: '\u2753', label: marketStatus.status || 'UNKNOWN' };

        if (marketStatus.status === 'regular' || !marketStatus.has_lastday_basis) {
            return `
            <div class="card" style="margin-bottom:16px">
                <h3>${badge.icon} ${badge.label}</h3>
            </div>`;
        }

        const lastday = marketStatus.unrealized_pnl_lastday_total || 0;
        const live = marketStatus.unrealized_pnl_live_total || 0;
        return `
        <div class="card" style="margin-bottom:16px">
            <h3>${badge.icon} ${badge.label} — 取引時間外の気配値は前日終値と乖離することがあります</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <div class="metric">
                    <span class="label">前日終値ベース評価損益</span>
                    <span class="value ${lastday >= 0 ? 'success' : 'danger'}" style="font-weight:700">${fmt.usdSigned(lastday)}</span>
                </div>
                <div class="metric">
                    <span class="label">現在値（時間外含む）ベース評価損益</span>
                    <span class="value ${live >= 0 ? 'success' : 'danger'}" style="font-weight:700">${fmt.usdSigned(live)}</span>
                </div>
            </div>
        </div>`;
    }

    renderPositions() {
        const p = this.data?.positions || {}, e = p.evidence || {};
        const rows = Array.isArray(p.positions) ? p.positions : [];
        const age = e.as_of ? (Date.now() - Date.parse(e.as_of))/1000 : NaN;
        const qualified = p.available === true && e.status === 'ok' && Number.isFinite(age) && age >= 0 && age <= 120;
        const summary = qualified ? (p.summary || {}) : {};
        const esc = value => this.escapeHtml(String(value ?? '未確認'));
        const number = value => finiteValue(value) ?? '未取得';
        const mood = value => finiteValue(value) === null ? 'muted' : value < 0 ? 'danger' : 'success';
        const concentration = finiteValue(summary.top5_concentration);
        const exposure = finiteValue(summary.gross_exposure), equity = finiteValue(summary.portfolio_value);
        const ratio = exposure !== null && equity > 0 ? exposure/equity : null;
        const sorted = [...rows].sort((a,b)=>(finiteValue(b.market_value) ?? -Infinity)-(finiteValue(a.market_value) ?? -Infinity));
        const groupRows = ['etf','stock'].map(kind=>{
            const group = rows.filter(row=>row.asset_class===kind);
            const mv = group.map(row=>finiteValue(row.market_value)), pnl = group.map(row=>finiteValue(row.unrealized_pnl));
            return `<div class="metric"><span>${kind.toUpperCase()}（${group.length}記録）</span><span>${qualified && mv.every(v=>v!==null) ? fmt.usd(mv.reduce((a,b)=>a+b,0)) : '未取得'} / ${qualified && pnl.every(v=>v!==null) ? fmt.usdSigned(pnl.reduce((a,b)=>a+b,0)) : '未取得'}</span></div>`;
        }).join('');
        return `${this.renderMarketStatusCard(p.market_status)}
        <section class="card ops-evidence" id="positions-evidence"><h3>保有の取得・評価範囲</h3>
            <p class="${qualified?'muted':'warn'}">${qualified ? '口座API取得（範囲限定）' : p.source==='tracker' ? '台帳の代用値・現在の口座保有は未確認' : 'ポジションの有無は未確認'}</p>
            <p>元時刻: ${esc(fmt.dt(e.as_of))} ／ 状態: ${esc(e.status)} ／ 取得元: ${esc(e.source || p.source)}</p>
            <p class="small muted">${esc(e.reason)} ／ ${esc(e.scope)}</p>
            <p class="warn small">口座API取得時刻と価格の市場時刻は別。分類coverage・実効ストップ・SELL監視の真正実行は未確認。</p>
            <p class="small">次の確認：${esc(p.next_action || '取得元・元時刻・価格欠測を確認。未取得を保有ゼロとみなしません。')}</p>
        </section>
        <div class="grid">
            <div class="card"><h3>📊 ポートフォリオサマリー</h3>
                <div class="metric"><span>評価損益</span><span class="value ${mood(summary.unrealized_pnl)}">${fmt.usdSigned(summary.unrealized_pnl)}</span></div>
                <div class="metric"><span>評価損益率</span><span class="value ${mood(summary.total_pnl_pct)}">${fmt.pctSigned(summary.total_pnl_pct)}</span></div>
                ${groupRows}<p class="small muted">ETF/Stock内訳は表示記録内。未分類やETF内部の重複まで網羅した配分認定ではありません。</p>
            </div>
            <div class="card"><h3>💼 エクスポージャー</h3>
                <div class="metric"><span>Gross Exposure</span><span class="value">${fmt.usd(summary.gross_exposure)}</span></div>
                <div class="metric"><span>Net Exposure</span><span class="value">${fmt.usd(summary.net_exposure)}</span></div>
                <div class="metric"><span>現金</span><span class="value">${fmt.usd(summary.cash)}</span></div>
                <div class="metric"><span>Exposure比率（対口座価値）</span><span>${fmt.pct(ratio)}</span></div>
                <p class="small muted">Grossは評価額の絶対値合計、Netは符号付き合計。未取得の構成要素はゼロ補完しません。</p>
            </div>
            <div class="card"><h3>📈 ポジション統計</h3>
                <div class="metric"><span>総ポジション数</span><span>${number(summary.position_count)}</span></div>
                <div class="metric"><span>ロング / ショート</span><span>${number(summary.long_count)} / ${number(summary.short_count)}</span></div>
                <div class="metric"><span>平均保有日数</span><span>${finiteValue(summary.avg_holding_days)===null?'未取得':Number(summary.avg_holding_days).toFixed(1)+'日'}</span></div>
                <div class="metric"><span>最大ポジション比率</span><span>${fmt.pct(summary.largest_position_weight)}</span></div>
            </div>
            <div class="card"><h3>⚠️ 集中リスク</h3>
                <div class="metric"><span>Top 5集中度</span><span class="value ${concentration===null?'muted':concentration>0.7?'danger':'success'}">${fmt.pct(concentration)}</span></div>
                <p class="small muted">分母は表示範囲のGross Exposure。対口座資産の上限や注文後集中度とは別。</p>
            </div>
        </div>
        <div class="card" style="margin-top:16px"><h3>📋 現在のポジション（${qualified?rows.length+'件':rows.length+'参照記録・口座件数未確認'}）</h3>
            ${rows.length ? this.renderPositionsTable(sorted) : `<p class="${qualified?'muted':'warn'}">${qualified?'取得範囲内に保有なし':'ポジションの有無は未確認'}</p>`}
        </div>`;
    }

    essCell(ess) {
        if (ess == null) return '<td class="small muted">—</td>';
        const v = parseFloat(ess);
        const cls = v >= 0.80 ? 'success' : v >= 0.60 ? 'warn' : 'danger';
        const bar = Math.round(v * 100);
        return `<td class="small" title="Entry Signal Strength: ${v.toFixed(4)}">
            <span class="${cls}" style="font-variant-numeric:tabular-nums">${v.toFixed(2)}</span>
            <div style="height:3px;margin-top:2px;background:#e5e7eb;border-radius:2px">
                <div style="height:3px;width:${bar}%;background:${v >= 0.80 ? '#10b981' : v >= 0.60 ? '#f59e0b' : '#ef4444'};border-radius:2px"></div>
            </div>
        </td>`;
    }

    renderPositionsTable(data) {
        if (!data || data.length === 0) return '<p class="warn">ポジションの有無は未確認</p>';
        return `<div class="table-wrap"><table><thead><tr>
            <th>シンボル</th><th>数量</th><th>保有日数</th><th>取得価格</th><th>現在価格</th><th>評価損益</th><th>損益率</th><th>ESS</th><th>Peak</th><th>参考ストップ（適用未照合）</th><th>ストップまで</th><th>比率</th>
        </tr></thead><tbody>
        ${data.map(pos => {
            const pnlPct = pos.unrealized_pnl_pct ?? pos.unrealized_return_pct ?? pos.return_pct ?? null;
            const pnlClass = finiteValue(pos.unrealized_pnl) === null ? 'muted' : pos.unrealized_pnl >= 0 ? 'success' : 'danger';
            const pnlPctClass = finiteValue(pnlPct) === null ? 'muted' : pnlPct >= 0 ? 'success' : 'danger';
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
            const assetClass = pos.asset_class || '';
            const assetBadge = assetClass === 'etf'
                ? ' <span class="badge badge-unknown" style="font-size:10px;padding:1px 5px">ETF</span>'
                : assetClass === 'stock'
                ? ' <span class="badge badge-unknown" style="font-size:10px;padding:1px 5px;opacity:.6">STK</span>'
                : '';
            const ess = pos.entry_signal_strength ?? pos.avg_ess ?? null;
            return `
            <tr style="${rowStyle}">
                <td><strong>${this.escapeHtml(pos.symbol)}</strong>${assetBadge}${trailBadge}</td>
                <td>${finiteValue(pos.qty ?? pos.quantity) ?? '未取得'}</td>
                <td>${pos.holding_days != null ? pos.holding_days + '日' : '—'}</td>
                <td>${fmt.usd(pos.entry_price ?? pos.avg_entry_price ?? pos.avg_price ?? null)}</td>
                <td>${fmt.usd(pos.current_price)}</td>
                <td class="${pnlClass}">${fmt.usdSigned(pos.unrealized_pnl)}</td>
                <td class="${pnlPctClass}">${fmt.pctSigned(pnlPct)}</td>
                ${this.essCell(ess)}
                <td class="small">${pos.peak_price ? fmt.usd(pos.peak_price) : '—'}</td>
                <td class="small">${stopPrice ? `<span title="${stopMode}">${stopLabel}</span>` : '—'}</td>
                <td class="${distClass} small">${distLabel}</td>
                <td>${fmt.pct(pos.portfolio_weight)}</td>
            </tr>`;
        }).join('')}
        </tbody></table></div>`;
    }

    cronQualification() {
        const cron=this.data?.cron_jobs || {}, evidence=cron.evidence || {};
        const stamp=Date.parse(evidence.as_of || ''), age=Date.now()-stamp;
        const current=evidence.status==='ok' && evidence.complete===true && Number.isFinite(age) && age>=0 && age<=120000;
        const rows=Array.isArray(cron.jobs) ? cron.jobs : [];
        const known=current && Array.isArray(cron.jobs);
        const activeKnown=known && rows.every(j=>typeof j.enabled==='boolean');
        const lagKnown=activeKnown && rows.every(j=>j.enabled===false || finiteValue(j.lag_seconds)!==null);
        return {cron,evidence,rows,known,total:known?rows.length:null,
            active:activeKnown?rows.filter(j=>j.enabled).length:null,
            lagged:lagKnown?rows.filter(j=>j.enabled && j.lag_seconds>3600).length:null,
            critical:lagKnown?rows.filter(j=>j.enabled && j.lag_seconds>86400).length:null};
    }

    renderCronSummary() {
        const q=this.cronQualification(), n=v=>v===null?'未確認':String(v);
        const metric=(label,value)=>`<div class="metric"><span class="label">${label}</span><span class="value ${value===null?'warn':value>0 && label.includes('遅延')?'danger':'muted'}">${n(value)}</span></div>`;
        const clock=this.data?.market_clock || {}, labels={regular:'通常立会',extended:'時間外予定区分',closed:'休場/時間外',unknown:'未確認'};
        return `<div id="cron-acquisition-evidence"><p class="${q.known?'muted':'warn'}">取得状態: ${this.escapeHtml(q.evidence.status || 'unknown')} ／ 取得元: ${this.escapeHtml(q.evidence.source || '未確認')} ／ 元時刻: ${this.escapeHtml(fmt.dt(q.evidence.as_of))}</p>
            <p class="small">${this.escapeHtml(q.evidence.scope || '取得成否・対象範囲が未確認。空一覧を現在のジョブなしとは認定しません。')}</p>
            ${metric('取得範囲のジョブ数',q.total)}${metric('有効',q.active)}${metric('遅延中 (>1h)',q.lagged)}${metric('重大遅延 (>1d)',q.critical)}
            <p class="small">米国予定区分: ${this.escapeHtml(labels[clock.session] || '未確認')} ／ 基準: America/New_York ／ 画面更新の目安: ${Math.round(Console.pollingDelay(clock)/60000)}分（区分境界で短縮）</p>
            <p class="small muted">画面ポーリングのみ。売買scheduler/停止条件は変更しません。最終状態の申告は履歴固有ID・SELL実行・実効設定の認定ではありません。</p></div>`;
    }

    renderCronJobs() {
        const q=this.cronQualification();
        return `<div class="card"><h3>🔄 定期実行統計</h3>${this.renderCronSummary()}</div>
            <div class="card" style="margin-top:16px"><h3>📊 ジョブ一覧（${q.known?q.total+'件':'参考 '+q.rows.length+'行・現状未確認'}）</h3>
            ${this.renderCronJobsTable(q.rows,q.known)}</div>`;
    }

    renderCronJobsTable(data, qualified = false) {
        if (!data || data.length === 0) return qualified ? '<p class="muted">取得範囲内にジョブなし</p>' : '<p class="warn">現在のジョブの有無は未確認</p>';
        const nowMs = Date.now();
        const fmtNextRun = (nextRunAtMs) => {
            if (!nextRunAtMs) return '—';
            const diffMs = nextRunAtMs - nowMs;
            const diffMin = Math.round(diffMs / 60000);
            const dt = new Date(nextRunAtMs);
            const hhmm = dt.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
            if (diffMs < 0) return `<span class="warn">過ぎ (${hhmm})</span>`;
            if (diffMin < 60) return `<span class="success">あと${diffMin}分 <span class="muted small">(${hhmm})</span></span>`;
            const diffH = Math.floor(diffMin / 60);
            const remMin = diffMin % 60;
            return `あと${diffH}h${remMin}m <span class="muted small">(${hhmm})</span>`;
        };
        return `<div class="table-wrap"><table><thead><tr>
            <th>名前</th><th>スケジュール</th><th>状態</th><th>最終実行</th><th>次回実行</th><th>遅延</th>
        </tr></thead><tbody>
        ${data.map(job => {
            const lagSeconds = qualified ? finiteValue(job.lag_seconds) : null;
            const lagClass = lagSeconds===null ? 'warn' : lagSeconds > 86400 ? 'danger' : lagSeconds > 3600 ? 'warn' : 'muted';
            const lagDisplay = lagSeconds===null ? '未確認' : this.formatDuration(lagSeconds);
            const nextRunAtMs = job.nextRunAtMs || job.next_run_at_ms;
            const lastStatus = job.lastRunStatus || job.last_run_status || 'unknown';
            const statusClass = !qualified ? 'unknown' : lastStatus === 'ok' ? 'muted' : lastStatus === 'error' ? 'danger' : 'unknown';
            return `
            <tr>
                <td><strong>${this.escapeHtml((job.name || '').replace('stock_swing_', ''))}</strong></td>
                <td class="small muted">${this.escapeHtml(job.schedule?.expr || '-')}</td>
                <td><span class="badge badge-${statusClass}">${this.escapeHtml(lastStatus)}</span></td>
                <td class="small muted">${fmt.dt(job.last_run || job.lastRunAt)}</td>
                <td class="small">${qualified ? fmtNextRun(nextRunAtMs) : '保存値・現状未確認'}</td>
                <td class="${lagClass} small">${lagDisplay}</td>
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
                    <h3>🏥 補助API取得ヘルス</h3><p class="small muted">通信・取得の点検。口座整合/売買正常性・SELL実行の認定とは別です。</p>
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
                <div class="metric"><span class="label">最大Drawdown</span><span class="value danger">${summary.max_drawdown_pct == null ? '未計測' : fmt.pct(summary.max_drawdown_pct)}</span></div>
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

        const alphaAvailable = perf.available !== false && alpha.available === true && finiteValue(alpha.alpha) !== null;
        const betaAvailable = perf.available !== false && beta.available === true && finiteValue(beta.beta) !== null;
        const sharpeAvailable = perf.available !== false && sharpe.available === true && finiteValue(sharpe.sharpe_ratio) !== null;

        // Alphaの色分け
        const alphaValue = finiteValue(alpha.alpha);
        const alphaClass = !alphaAvailable ? 'unknown' : alphaValue > 2 ? 'success' : alphaValue > 0 ? 'warn' : 'danger';
        const alphaIcon = !alphaAvailable ? '⏸️' : alphaValue > 0 ? '🚀' : '🐢';

        // Betaの色分け
        const betaValue = finiteValue(beta.beta);
        const betaClass = !betaAvailable ? 'unknown' : betaValue < 0.5 ? 'success' : betaValue < 1 ? 'warn' : 'danger';
        const betaIcon = !betaAvailable ? '⏸️' : betaValue < 0.5 ? '🛡️' : betaValue < 1 ? '⚠️' : '🔥';

        // Sharpeの色分け
        const sharpeValue = finiteValue(sharpe.sharpe_ratio);
        const sharpeClass = !sharpeAvailable ? 'unknown' : sharpeValue > 2 ? 'success' : sharpeValue > 1 ? 'warn' : 'danger';
        const sharpeIcon = !sharpeAvailable ? '⏸️' : sharpeValue > 2 ? '⭐' : sharpeValue > 1 ? '🟡' : '🔴';
        const periodInfo = alpha.period?.start && alpha.period?.end
            ? `${alpha.period.start} → ${alpha.period.end} (${alpha.period.days || 0}点)`
            : `${this.getPeriodLabel(perf.period_filter || this.currentPeriod)} / snapshots=${finiteValue(perf.snapshot_count) ?? '未確認'}`;
        const strategyAttribution = perf.by_strategy || [];

        // 全期間サマリー
        const fp = perf.full_period;
        const fpHtml = fp ? (() => {
            const fpAlpha = finiteValue(fp.alpha);
            const fpPf = finiteValue(fp.portfolio_return_pct);
            const fpBm = finiteValue(fp.benchmark_return_pct);
            const fpSharpe = finiteValue(fp.sharpe);
            const fpClass = fpAlpha == null ? 'unknown' : fpAlpha > 0 ? 'success' : 'danger';
            return `<div class="card" style="margin-bottom:16px;border-left:4px solid #6366f1">
                <h4 style="margin:0 0 8px">📅 全期間サマリー（${this.escapeHtml(String(fp.start || '?'))} → ${this.escapeHtml(String(fp.end || '?'))} / ${finiteValue(fp.days) ?? '?'}点）</h4>
                <div style="display:flex;gap:24px;flex-wrap:wrap">
                    <div class="metric" style="margin:0"><span class="label">Portfolio</span><span class="value ${fpPf === null ? 'muted' : fpPf >= 0 ? 'success' : 'danger'}">${fpPf != null ? (fpPf >= 0 ? '+' : '') + fpPf.toFixed(2) + '%' : '—'}</span></div>
                    <div class="metric" style="margin:0"><span class="label">SPY</span><span class="value">${fpBm != null ? (fpBm >= 0 ? '+' : '') + fpBm.toFixed(2) + '%' : '—'}</span></div>
                    <div class="metric" style="margin:0"><span class="label">Alpha</span><span class="value ${fpClass}">${fpAlpha != null ? (fpAlpha >= 0 ? '+' : '') + fpAlpha.toFixed(2) + '%' : '—'}</span></div>
                    <div class="metric" style="margin:0"><span class="label">Sharpe</span><span class="value">${fpSharpe != null ? fpSharpe.toFixed(2) : '—'}</span></div>
                </div>
            </div>`;
        })() : '';

        return `
        ${this.renderPeriodSelector()}
        <section class="card ops-evidence" id="analysis-qualification">${this.renderMetricQualification()}
            <p class="small">標本: snapshot ${finiteValue(perf.snapshot_count) ?? '未確認'} ／ β ${finiteValue(beta.data_points) ?? '未確認'} ／ Sharpe ${finiteValue(sharpe.data_points) ?? '未確認'}</p>
            <p class="small warn">参考集計。期間・評価時点・費用・同条件比較の資格は未認定。年率換算は将来収益の予測ではありません。</p>
            <p class="small">次の確認：欠測/標本数と対象期間、価格・台帳の評価資格を確認。未評価をゼロで埋めません。</p>
        </section>
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
                <div class="metric"><span class="label">ポートフォリオ</span><span class="value ${alphaAvailable && finiteValue(alpha.portfolio?.return_pct) !== null ? (Number(alpha.portfolio.return_pct)>=0?'success':'danger') : 'muted'}">${alphaAvailable ? fmt.pct((finiteValue(alpha.portfolio?.return_pct) === null ? null : Number(alpha.portfolio?.return_pct) / 100)) : '—'}</span></div>
                <div class="metric"><span class="label">ベンチマーク (${alpha.benchmark?.symbol || 'SPY'})</span><span class="value">${alphaAvailable ? fmt.pct((finiteValue(alpha.benchmark?.return_pct) === null ? null : Number(alpha.benchmark?.return_pct) / 100)) : '—'}</span></div>
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
                <div class="metric"><span class="label">R² (決定係数)</span><span class="value">${betaAvailable ? (finiteValue(beta.r_squared) === null ? '未取得' : Number(beta.r_squared).toFixed(3)) : '—'}</span></div>
                <div class="metric"><span class="label">相関係数</span><span class="value">${betaAvailable ? (finiteValue(beta.correlation) === null ? '未取得' : Number(beta.correlation).toFixed(3)) : '—'}</span></div>
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
                <div class="metric"><span class="label">年率換算リターン（参考）</span><span class="value ${sharpeAvailable && finiteValue(sharpe.annual_return_pct) !== null ? (Number(sharpe.annual_return_pct)>=0?'success':'danger') : 'muted'}">${sharpeAvailable ? fmt.pct((finiteValue(sharpe.annual_return_pct) === null ? null : Number(sharpe.annual_return_pct) / 100)) : '—'}</span></div>
                <div class="metric"><span class="label">年率換算ボラティリティ（参考）</span><span class="value ${sharpeAvailable && finiteValue(sharpe.annual_volatility_pct) !== null ? 'warn' : 'muted'}">${sharpeAvailable ? fmt.pct((finiteValue(sharpe.annual_volatility_pct) === null ? null : Number(sharpe.annual_volatility_pct) / 100)) : '—'}</span></div>
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
            const alphaTxt = (row.alpha?.available === true && finiteValue(row.alpha?.alpha) !== null) ? fmt.pctSigned((row.alpha?.alpha || 0) / 100) : 'N/A';
            const betaTxt = (row.beta?.available === true && finiteValue(row.beta?.beta) !== null) ? Number(row.beta.beta).toFixed(2) : 'N/A';
            const sharpeTxt = (row.sharpe?.available === true && finiteValue(row.sharpe?.sharpe_ratio) !== null) ? Number(row.sharpe.sharpe_ratio).toFixed(2) : 'N/A';
            const alphaCls = (row.alpha?.available === true && finiteValue(row.alpha?.alpha) !== null) ? ((row.alpha?.alpha || 0) >= 0 ? 'success' : 'danger') : 'muted';
            const pnlCls = finiteValue(row.realized_pnl) === null ? 'muted' : Number(row.realized_pnl) >= 0 ? 'success' : 'danger';
            const memo = row.summary || row.alpha?.error || row.beta?.error || row.sharpe?.error || row.approximation || '';
            return `<tr>
                <td class="small">${this.formatStrategyLabel(row.strategy_version_id || '')}</td>
                <td>${row.closed_trades || 0}</td>
                <td>${row.active_days || 0}</td>
                <td>${row.winning_trades || 0} / ${row.losing_trades || 0}</td>
                <td class="${pnlCls}">${fmt.usdSigned(finiteValue(row.realized_pnl))}</td>
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
        
        <div class="grid" style="margin-bottom: 16px;">
            <div class="card" style="grid-column: 1 / 3;">
                <h3>🎯 取引回数推移</h3>
                <canvas id="tradeCountChart" height="80"></canvas>
            </div>
            <div class="card" style="grid-column: 3 / -1;">
                <h3>🏆 勝率推移</h3>
                <canvas id="winRateChart" height="80"></canvas>
            </div>
        </div>

        <div class="grid">
            <div class="card" style="grid-column: 1 / -1;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                    <h3 style="margin:0">📊 Profit Factor 推移 <span class="muted small">Go/No-Go 基準: PF ≥ 1.0</span></h3>
                </div>
                <canvas id="pfChart" height="70"></canvas>
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
        
        <div class="card" style="margin-top:16px">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:6px">
                <h3 style="margin:0">📋 ニュース記事 (${newsArr.length}件)</h3>
                <div style="display:flex;gap:4px;flex-wrap:wrap">
                    <button class="chart-period-btn news-sym-btn${!this._newsSymFilter ? ' active' : ''}" data-sym="">ALL</button>
                    ${[...new Set(newsArr.map(n => n.symbol).filter(Boolean))].slice(0,12).map(sym =>
                        `<button class="chart-period-btn news-sym-btn${this._newsSymFilter === sym ? ' active' : ''}" data-sym="${this.escapeHtml(sym)}">${this.escapeHtml(sym)}</button>`
                    ).join('')}
                </div>
            </div>
            <div id="newsTableContainer">${this.renderNewsTable(newsArr, this._newsSymFilter || '')}</div>
        </div>`;
    }

    _initNewsFilters() {
        if (!this._newsSymFilter) this._newsSymFilter = '';
        const newsArr = (this.data?.news?.items || []);
        document.querySelectorAll('.news-sym-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this._newsSymFilter = btn.dataset.sym || '';
                document.querySelectorAll('.news-sym-btn').forEach(b =>
                    b.classList.toggle('active', b.dataset.sym === this._newsSymFilter));
                const container = document.getElementById('newsTableContainer');
                if (container) container.innerHTML = this.renderNewsTable(newsArr, this._newsSymFilter);
            });
        });
    }

    renderNewsTable(data, filterSymbol = '') {
        if (!data || data.length === 0) return '<p class="muted">ニュースなし</p>';
        const filtered = filterSymbol
            ? data.filter(item => (item.symbol || '').toUpperCase() === filterSymbol.toUpperCase())
            : data;
        if (filtered.length === 0) return `<p class="muted">${this.escapeHtml(filterSymbol)} のニュースなし</p>`;

        return `<div class="table-wrap"><table><thead><tr>
            <th>日付</th><th>シンボル</th><th>ヘッドライン</th><th>センチメント</th><th>インパクト</th>
        </tr></thead><tbody>
        ${filtered.map(item => {
            const headline = item.headline || '';
            const headlineJa = item.headline_ja || '';
            const sentClass = item.sentiment_label === 'positive' ? 'success' : item.sentiment_label === 'negative' ? 'danger' : 'unknown';
            const impClass = item.impact_label === 'high' || item.impact_label === 'critical' ? 'warn' : 'unknown';
            return `
            <tr>
                <td class="small">${fmt.dt(item.published_at)}</td>
                <td><strong>${this.escapeHtml(item.symbol)}</strong></td>
                <td>
                    <a href="${this.escapeHtml(item.url)}" target="_blank" style="font-weight:500">${this.escapeHtml(headline)}</a>
                    ${headlineJa && headlineJa !== headline ? `<div class="small muted" style="margin-top:2px">${this.escapeHtml(headlineJa)}</div>` : ''}
                </td>
                <td><span class="badge badge-${sentClass}">${this.escapeHtml(item.sentiment_label_ja || item.sentiment_label || '—')}</span></td>
                <td><span class="badge badge-${impClass}">${this.escapeHtml(item.impact_label_ja || item.impact_label || '—')}</span></td>
            </tr>`;
        }).join('')}
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
                Chart.getChart(ctx)?.destroy();
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
        
        Chart.getChart(ctx)?.destroy();

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

            Chart.getChart(ctx)?.destroy();

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
            const periodDays = finiteValue(alpha.period?.days) ?? finiteValue(sharpe.data_points) ?? '未確認';
            const portfolioReturnPct = perf.available !== false && alpha.available === true ? finiteValue(alpha.portfolio?.return_pct) : null;
            // Reference conversion only; missing volatility must not become zero risk.
            const portfolioVolPct = perf.available !== false && sharpe.available === true ? finiteValue(sharpe.annual_volatility_pct) : null;

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

            Chart.getChart(ctx)?.destroy();

            new Chart(ctx, {
                type: 'scatter',
                data: {
                    datasets: [{
                        label: 'ポートフォリオ（参考）',
                        data: portfolioVolPct !== null && portfolioVolPct >= 0 && portfolioReturnPct !== null ? [{ x: portfolioVolPct, y: portfolioReturnPct }] : [],
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

                Chart.getChart(equityCtx)?.destroy();

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
                Chart.getChart(ctx4)?.destroy();
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
            
            // Trade Count / Win Rate: build from daily_snapshots (not in charts.overview)
            const allSnapsForCharts = this.data?.trading?.daily_snapshots || [];
            const snapPeriod = this._filterEquityByPeriod(allSnapsForCharts, this._equityChartPeriod);

            const tradeCountData = snapPeriod
                .filter(s => s.date && s.cumulative_closed_trades != null)
                .map(s => ({ date: (s.date || '').slice(0, 10), value: s.cumulative_closed_trades }));
            const winRateData = snapPeriod
                .filter(s => s.date && s.cumulative_win_rate != null)
                .map(s => ({ date: (s.date || '').slice(0, 10), value: s.cumulative_win_rate }));

            // Trade Count Chart
            this.createLineChart('tradeCountChart', tradeCountData, '累積取引回数', '#f59e0b', (v) => v);

            // Win Rate Chart
            this.createLineChart('winRateChart', winRateData, '勝率', '#10b981', (v) => fmt.pct(v));

            // Profit Factor Chart (from daily_snapshots)
            const pfCtx = document.getElementById('pfChart');
            if (pfCtx) {
                const allSnaps = this.data?.trading?.daily_snapshots || [];
                const pfSnaps = this._filterEquityByPeriod(
                    allSnaps.filter(s => s.cumulative_profit_factor != null && s.date),
                    this._equityChartPeriod
                );
                if (pfSnaps.length > 0) {
                    const pfLabels = pfSnaps.map(s => new Date(s.date + 'T00:00:00').toLocaleDateString('ja-JP', {month:'short', day:'numeric'}));
                    const pfValues = pfSnaps.map(s => +s.cumulative_profit_factor);
                    const goalLine = pfSnaps.map(() => 1.0);
                    Chart.getChart(pfCtx)?.destroy();
                    new Chart(pfCtx, {
                        type: 'line',
                        data: {
                            labels: pfLabels,
                            datasets: [
                                {
                                    label: 'Profit Factor',
                                    data: pfValues,
                                    borderColor: '#6366f1',
                                    backgroundColor: 'rgba(99,102,241,0.1)',
                                    fill: true,
                                    tension: 0.3,
                                    borderWidth: 2,
                                    pointRadius: 2,
                                },
                                {
                                    label: 'Go/No-Go 基準 (1.0)',
                                    data: goalLine,
                                    borderColor: '#ef4444',
                                    backgroundColor: 'transparent',
                                    fill: false,
                                    borderDash: [6, 4],
                                    borderWidth: 1.5,
                                    pointRadius: 0,
                                }
                            ]
                        },
                        options: {
                            responsive: true,
                            plugins: {
                                legend: { display: true },
                                tooltip: {
                                    callbacks: {
                                        label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(3)}`
                                    }
                                }
                            },
                            scales: {
                                y: {
                                    min: 0,
                                    ticks: { callback: (v) => v.toFixed(2) }
                                }
                            }
                        }
                    });
                }
            }
        }, 100);
    }

    createLineChart(canvasId, data, label, color, formatter) {
        const ctx = document.getElementById(canvasId);
        if (!ctx || data.length === 0) return;
        
        Chart.getChart(ctx)?.destroy();

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
        // Server's existing ET calendar drives display polling, never local hours.
        const getRefreshInterval = () => Console.pollingDelay(this.data?.market_clock);

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
            
            if (result.data?.market_clock) consoleMarketClock=result.data.market_clock;
            const captured=Date.parse(result.data?.time || '');
            return {
                success: result.success,
                source: result.source || 'api',
                responseTime: duration,
                dataAge: Number.isFinite(captured) ? Date.now()-captured : null,
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
        
        healthMonitor.startMonitoring(() => Console.pollingDelay(consoleMarketClock));
        console.log('✅ Supplemental API monitoring follows server ET calendar');
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
