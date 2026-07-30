/**
 * Stock Swing Console - State Manager
 * Application state management
 */

/**
 * アプリケーション状態管理
 */
class AppStateManager {
  constructor() {
    this.state = {
      lastUpdate: null,
      data: null,
      error: null,
      isLoading: false,
      connectionStatus: 'unknown' // 'connected', 'disconnected', 'unknown'
    };
    this.listeners = [];
    this.updateInterval = null;
    this.autoUpdateEnabled = true;
  }
  
  /**
   * 状態を更新
   * @param {Object} newState - 新しい状態
   */
  setState(newState) {
    const oldState = { ...this.state };
    this.state = { ...this.state, ...newState };
    
    // 状態変更をログ
    if (newState.error) {
      console.error('State error:', newState.error);
    }
    
    // リスナーに通知
    this.notify(oldState);
  }
  
  /**
   * 状態を取得
   * @returns {Object} 現在の状態
   */
  getState() {
    return { ...this.state };
  }
  
  /**
   * 状態変更をリスナーに通知
   * @param {Object} oldState - 変更前の状態
   */
  notify(oldState) {
    this.listeners.forEach(listener => {
      try {
        listener(this.state, oldState);
      } catch (e) {
        console.error('Listener error:', e);
      }
    });
  }
  
  /**
   * リスナーを登録
   * @param {Function} listener - リスナー関数
   * @returns {Function} 登録解除関数
   */
  subscribe(listener) {
    this.listeners.push(listener);
    
    // 即座に現在の状態を通知
    try {
      listener(this.state, {});
    } catch (e) {
      console.error('Initial listener call error:', e);
    }
    
    // 登録解除関数を返す
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }
  
  /**
   * データを更新
   * @returns {Promise<void>}
   */
  async updateData() {
    // 既に読み込み中の場合はスキップ
    if (this.state.isLoading) {
      console.log('Already loading, skipping update');
      return;
    }
    
    this.setState({ isLoading: true, error: null });
    
    try {
      const result = await apiClient.getDashboard();
      
      if (result.success) {
        this.setState({
          data: result.data,
          lastUpdate: result.timestamp,
          isLoading: false,
          error: null,
          connectionStatus: 'connected'
        });
      } else {
        this.setState({
          error: result.error,
          isLoading: false,
          connectionStatus: 'disconnected'
        });
        
        errorHandler.showError(`Failed to load data: ${result.error}`);
      }
    } catch (error) {
      console.error('Update data error:', error);
      
      this.setState({
        error: error.message,
        isLoading: false,
        connectionStatus: 'disconnected'
      });
      
      errorHandler.showError(`Unexpected error: ${error.message}`);
    }
  }
  
  /**
   * 自動更新を開始
   * @param {number} interval - 更新間隔（ミリ秒）
   */
  startAutoUpdate(interval = 30000) {
    this.stopAutoUpdate();
    
    this.autoUpdateEnabled = true;
    
    // 最初の更新を実行
    this.updateData();
    
    // 定期的に更新
    this.updateInterval = setInterval(() => {
      if (this.autoUpdateEnabled) {
        this.updateData();
      }
    }, interval);
    
    console.log(`Auto-update started (interval: ${interval}ms)`);
  }
  
  /**
   * 自動更新を停止
   */
  stopAutoUpdate() {
    if (this.updateInterval) {
      clearInterval(this.updateInterval);
      this.updateInterval = null;
      console.log('Auto-update stopped');
    }
    
    this.autoUpdateEnabled = false;
  }
  
  /**
   * 自動更新を一時停止
   */
  pauseAutoUpdate() {
    this.autoUpdateEnabled = false;
    console.log('Auto-update paused');
  }
  
  /**
   * 自動更新を再開
   */
  resumeAutoUpdate() {
    this.autoUpdateEnabled = true;
    console.log('Auto-update resumed');
  }
  
  /**
   * 手動で更新（ボタンクリック時など）
   */
  async manualUpdate() {
    errorHandler.showInfo('Updating...');
    await this.updateData();
  }
  
  /**
   * 状態をリセット
   */
  reset() {
    this.stopAutoUpdate();
    
    this.setState({
      lastUpdate: null,
      data: null,
      error: null,
      isLoading: false,
      connectionStatus: 'unknown'
    });
    
    console.log('State reset');
  }
  
  /**
   * データの一部を取得（便利メソッド）
   * @param {string} path - パス（例: 'positions.summary.position_count'）
   * @param {*} defaultValue - デフォルト値
   * @returns {*} 値
   */
  getData(path, defaultValue = null) {
    if (!this.state.data) {
      return defaultValue;
    }
    
    return safeGet(this.state.data, path, defaultValue);
  }
  
  /**
   * 接続状態を確認
   * @returns {boolean} 接続中かどうか
   */
  isConnected() {
    return this.state.connectionStatus === 'connected';
  }
  
  /**
   * 最終更新からの経過時間（ミリ秒）
   * @returns {number} 経過時間
   */
  getTimeSinceLastUpdate() {
    if (!this.state.lastUpdate) {
      return Infinity;
    }
    
    return Date.now() - this.state.lastUpdate.getTime();
  }
}

// グローバルインスタンス
const appState = new AppStateManager();

console.log('✅ state-manager.js loaded successfully');
