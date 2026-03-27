// Stock Swing Console Frontend

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
            const status = this.data.system.status;
            const badge = `<span class="status-badge status-${status}">${status.toUpperCase()}</span>`;
            systemStatus.innerHTML = badge;
        }

        if (this.data.time) {
            lastUpdate.textContent = `Last update: ${new Date(this.data.time).toLocaleString()}`;
        }
    }

    render() {
        const content = document.getElementById('content');
        
        if (!this.data) {
            content.innerHTML = '<p>Loading...</p>';
            return;
        }

        if (this.data.error) {
            content.innerHTML = `<div class="card"><p>Error: ${this.data.error}</p></div>`;
            return;
        }

        switch (this.currentTab) {
            case 'overview':
                content.innerHTML = this.renderOverview();
                break;
            case 'cron':
                content.innerHTML = this.renderCronJobs();
                break;
            case 'data':
                content.innerHTML = this.renderDataStatus();
                break;
            case 'logs':
                content.innerHTML = this.renderLogs();
                break;
        }
    }

    renderOverview() {
        const overview = this.data.overview || {};
        const system = this.data.system || {};

        return `
            <div class="grid">
                <div class="card">
                    <h3>System Health</h3>
                    <div class="metric">
                        <span class="metric-label">Health Score</span>
                        <span class="metric-value">${system.score || 0}/100</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Status</span>
                        <span class="status-badge status-${system.status || 'unknown'}">${(system.status || 'unknown').toUpperCase()}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Runtime Mode</span>
                        <span class="metric-value">${system.runtime_mode || 'unknown'}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">API Keys</span>
                        <span class="metric-value">${system.api_keys_configured ? '✅ Configured' : '❌ Missing'}</span>
                    </div>
                </div>

                <div class="card">
                    <h3>Cron Jobs</h3>
                    <div class="metric">
                        <span class="metric-label">Active</span>
                        <span class="metric-value enabled">${overview.cron_jobs_active || 0}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Total</span>
                        <span class="metric-value">${overview.cron_jobs_total || 0}</span>
                    </div>
                </div>

                <div class="card">
                    <h3>Data Counts</h3>
                    ${this.renderDataCounts(overview.data_counts)}
                </div>
            </div>
        `;
    }

    renderDataCounts(counts) {
        if (!counts) return '<p>No data</p>';

        return Object.entries(counts).map(([stage, count]) => `
            <div class="metric">
                <span class="metric-label">${stage}</span>
                <span class="metric-value">${count}</span>
            </div>
        `).join('');
    }

    renderCronJobs() {
        const cronData = this.data.cron_jobs || {};
        const jobs = cronData.jobs || [];

        if (jobs.length === 0) {
            return '<div class="card"><p>No cron jobs found</p></div>';
        }

        return `
            <div class="card">
                <h3>Cron Jobs (${cronData.total || 0})</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Schedule</th>
                            <th>Next Run</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${jobs.map(job => `
                            <tr>
                                <td>${job.name || 'Unknown'}</td>
                                <td>${job.schedule_display || 'N/A'}</td>
                                <td>${job.next_run ? new Date(job.next_run).toLocaleString() : 'N/A'}</td>
                                <td class="${job.enabled ? 'enabled' : 'disabled'}">
                                    ${job.enabled ? '✅ Enabled' : '❌ Disabled'}
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    renderDataStatus() {
        const dataStatus = this.data.data_status || {};
        const counts = dataStatus.counts || {};
        const freshness = dataStatus.freshness || {};

        return `
            <div class="grid">
                <div class="card">
                    <h3>Data Counts</h3>
                    ${this.renderDataCounts(counts)}
                </div>

                <div class="card">
                    <h3>Data Freshness</h3>
                    ${Object.entries(freshness).map(([stage, info]) => `
                        <div class="metric">
                            <span class="metric-label">${stage}</span>
                            <span>
                                <span class="status-badge status-${info.status}">${info.status}</span>
                                ${info.age_hours ? ` (${info.age_hours}h)` : ''}
                            </span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    renderLogs() {
        return `
            <div class="card">
                <h3>Logs</h3>
                <p>Log viewing feature coming soon...</p>
                <p>For now, check: <code>~/stock_swing/logs/</code></p>
            </div>
        `;
    }

    startAutoRefresh() {
        setInterval(async () => {
            await this.loadData();
            this.render();
        }, 30000); // Refresh every 30 seconds
    }
}

// Initialize console when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new Console();
});
