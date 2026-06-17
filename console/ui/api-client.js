/**
 * Stock Swing Console - API Client
 * Robust API client with retry logic and error handling
 */

/**
 * 堅牢なAPIクライアント
 */
class RobustAPIClient {
  constructor(baseURL = '') {
    this.baseURL = baseURL;
    this.retryAttempts = 3;
    this.retryDelay = 1000; // 1秒
    this.timeout = 10000; // 10秒
  }
  
  /**
   * データを取得（リトライ付き）
   * @param {string} url - URL
   * @param {Object} options - fetchオプション
   * @param {number} attempts - 残りの試行回数
   * @returns {Promise<Object>} result
   */
  async fetchWithRetry(url, options = {}, attempts = this.retryAttempts) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);
    
    try {
      const response = await fetch(this.baseURL + url, {
        ...options,
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      return { success: true, data };
      
    } catch (error) {
      clearTimeout(timeoutId);
      
      const errorMessage = error.name === 'AbortError' 
        ? 'Request timeout'
        : error.message;
      
      console.error(`Fetch error (${attempts} attempts left):`, errorMessage);
      
      if (attempts > 1) {
        await this.sleep(this.retryDelay);
        return this.fetchWithRetry(url, options, attempts - 1);
      }
      
      return { success: false, error: errorMessage };
    }
  }
  
  /**
   * ダッシュボードデータを取得
   * @returns {Promise<Object>} result
   */
  async getDashboard() {
    const startTime = Date.now();
    const result = await this.fetchWithRetry('/api/dashboard');
    const endTime = Date.now();
    
    // パフォーマンス測定
    if (typeof performanceMonitor !== 'undefined') {
      performanceMonitor.measureAPICall('/api/dashboard', startTime, endTime, result.success);
    }
    
    if (result.success) {
      // データを検証・正規化
      const validatedData = dataValidator.validate(result.data);
      
      // キャッシュに保存（recoveryManager利用可能な場合）
      if (typeof recoveryManager !== 'undefined') {
        recoveryManager.cacheData('dashboard', validatedData);
      }
      
      return {
        success: true,
        data: validatedData,
        timestamp: new Date()
      };
    }
    
    // エラー追跡
    if (typeof errorTracker !== 'undefined') {
      errorTracker.trackAPIError('/api/dashboard', 0, result.error);
    }
    
    // キャッシュからフォールバック
    if (typeof recoveryManager !== 'undefined') {
      const cached = recoveryManager.getCachedData('dashboard');
      if (cached) {
        console.warn('Using cached dashboard data');
        return {
          success: true,
          data: cached,
          source: 'cache',
          timestamp: new Date()
        };
      }
    }
    
    // エラー時はデフォルトデータを返す
    console.warn('Failed to fetch dashboard, using default data');
    
    return {
      success: false,
      error: result.error,
      data: dataValidator.getDefaultData(),
      timestamp: new Date()
    };
  }
  
  /**
   * ヘルスチェック
   * @returns {Promise<Object>} result
   */
  async checkHealth() {
    const result = await this.fetchWithRetry('/api/health', {}, 1);
    return result;
  }
  
  /**
   * スリープ
   * @param {number} ms - ミリ秒
   * @returns {Promise<void>}
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
  
  /**
   * リトライ設定を変更
   * @param {number} attempts - 試行回数
   * @param {number} delay - 遅延（ミリ秒）
   */
  setRetryConfig(attempts, delay) {
    this.retryAttempts = attempts;
    this.retryDelay = delay;
  }
  
  /**
   * タイムアウト設定を変更
   * @param {number} timeout - タイムアウト（ミリ秒）
   */
  setTimeout(timeout) {
    this.timeout = timeout;
  }
}

// グローバルインスタンス
const apiClient = new RobustAPIClient();

// ─────────────────────────────────────────────────────────────────────────────
// fetchJsonStable — CF-2 安定 fetch wrapper
//   - AbortController 8秒タイムアウト
//   - 指数バックオフリトライ (最大3回)
//   - inflight Map で同一 URL の重複リクエスト排除
//   - lastGood Map で最後の成功レスポンスをキャッシュ
//   - 失敗時は { data: lastGood, stale: true, error } を返す (UI を白くしない)
// ─────────────────────────────────────────────────────────────────────────────
const _stableFetch = (() => {
  /** @type {Map<string, Promise>} */
  const inflight = new Map();
  /** @type {Map<string, any>} */
  const lastGood = new Map();

  const TIMEOUT_MS   = 8000;
  const MAX_RETRIES  = 3;
  const BASE_DELAY   = 500; // ms, doubles each retry

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /**
   * Single attempt with AbortController timeout.
   * @param {string} url
   * @param {RequestInit} options
   * @returns {Promise<any>} Parsed JSON
   */
  async function attemptFetch(url, options) {
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const resp = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(tid);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      return await resp.json();
    } catch (err) {
      clearTimeout(tid);
      throw err;
    }
  }

  /**
   * Fetch with retries + exponential backoff.
   * @param {string} url
   * @param {RequestInit} options
   * @returns {Promise<any>}
   */
  async function fetchWithRetry(url, options) {
    let lastErr;
    for (let i = 0; i < MAX_RETRIES; i++) {
      try {
        return await attemptFetch(url, options);
      } catch (err) {
        lastErr = err;
        const delay = BASE_DELAY * Math.pow(2, i);
        console.warn(`[fetchJsonStable] attempt ${i + 1}/${MAX_RETRIES} failed for ${url}: ${err.message}. Retrying in ${delay}ms...`);
        if (i < MAX_RETRIES - 1) await sleep(delay);
      }
    }
    throw lastErr;
  }

  /**
   * Public stable fetch entry point.
   * Returns { data, stale, error } — data is always present (falls back to last good).
   * @param {string} url
   * @param {RequestInit} [options]
   * @returns {Promise<{ data: any, stale: boolean, error: string|null }>}
   */
  async function fetchJsonStable(url, options = {}) {
    // Dedup: if same URL is already in flight, reuse the same promise
    if (inflight.has(url)) {
      return inflight.get(url);
    }

    const promise = (async () => {
      try {
        const data = await fetchWithRetry(url, options);
        lastGood.set(url, data);
        return { data, stale: false, error: null };
      } catch (err) {
        const cached = lastGood.get(url) ?? null;
        const msg = err.name === 'AbortError' ? 'Request timed out' : err.message;
        console.error(`[fetchJsonStable] all retries failed for ${url}: ${msg}`);
        return { data: cached, stale: true, error: msg };
      } finally {
        inflight.delete(url);
      }
    })();

    inflight.set(url, promise);
    return promise;
  }

  /** Expose lastGood for testing / diagnostics */
  fetchJsonStable._lastGood = lastGood;
  fetchJsonStable._inflight = inflight;

  return fetchJsonStable;
})();

console.log('✅ api-client.js loaded successfully');
