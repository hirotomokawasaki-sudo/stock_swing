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

console.log('✅ api-client.js loaded successfully');
