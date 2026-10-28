/**
 * Stock Swing Console - Error Handler
 * UI error display and handling
 */

/**
 * UIエラー表示
 */
class UIErrorHandler {
  constructor() {
    this.errorContainer = null;
    this.currentToast = null;
    this.init();
  }
  
  /**
   * 初期化
   */
  init() {
    // エラー表示用コンテナを作成
    this.errorContainer = document.createElement('div');
    this.errorContainer.id = 'error-toast-container';
    this.errorContainer.className = 'error-toast-container';
    document.body.appendChild(this.errorContainer);
  }
  
  /**
   * トーストを表示
   * @param {string} message - メッセージ
   * @param {string} type - タイプ（'error', 'warning', 'info', 'success'）
   * @param {number} duration - 表示時間（ミリ秒、0で自動非表示なし）
   */
  show(message, type = 'error', duration = 5000) {
    // 既存のトーストを削除
    if (this.currentToast) {
      this.currentToast.remove();
    }
    
    // 新しいトーストを作成
    const toast = document.createElement('div');
    toast.className = `error-toast ${type}`;
    
    // アイコンを追加
    const icon = this.getIcon(type);
    
    toast.innerHTML = `
      <div class="error-toast-content">
        <span class="error-toast-icon">${icon}</span>
        <span class="error-toast-message">${escapeHtml(message)}</span>
        <button class="error-toast-close" onclick="errorHandler.hide()">&times;</button>
      </div>
    `;
    
    this.errorContainer.appendChild(toast);
    this.currentToast = toast;
    
    // アニメーション
    setTimeout(() => {
      toast.classList.add('show');
    }, 10);
    
    // 自動で非表示
    if (duration > 0) {
      setTimeout(() => this.hide(), duration);
    }
  }
  
  /**
   * トーストを非表示
   */
  hide() {
    if (this.currentToast) {
      this.currentToast.classList.remove('show');
      setTimeout(() => {
        if (this.currentToast) {
          this.currentToast.remove();
          this.currentToast = null;
        }
      }, 300);
    }
  }
  
  /**
   * エラーを表示
   * @param {string} message - メッセージ
   * @param {number} duration - 表示時間（ミリ秒）
   */
  showError(message, duration = 5000) {
    this.show(message, 'error', duration);
  }
  
  /**
   * 警告を表示
   * @param {string} message - メッセージ
   * @param {number} duration - 表示時間（ミリ秒）
   */
  showWarning(message, duration = 5000) {
    this.show(message, 'warning', duration);
  }
  
  /**
   * 情報を表示
   * @param {string} message - メッセージ
   * @param {number} duration - 表示時間（ミリ秒）
   */
  showInfo(message, duration = 3000) {
    this.show(message, 'info', duration);
  }
  
  /**
   * 成功メッセージを表示
   * @param {string} message - メッセージ
   * @param {number} duration - 表示時間（ミリ秒）
   */
  showSuccess(message, duration = 3000) {
    this.show(message, 'success', duration);
  }
  
  /**
   * ローディング表示
   * @param {string} message - メッセージ
   */
  showLoading(message = 'Loading...') {
    this.show(message, 'info', 0);
  }
  
  /**
   * タイプに応じたアイコンを取得
   * @param {string} type - タイプ
   * @returns {string} アイコンHTML
   */
  getIcon(type) {
    const icons = {
      error: '❌',
      warning: '⚠️',
      info: 'ℹ️',
      success: '✅'
    };
    return icons[type] || '📢';
  }
  
  /**
   * セクションエラーを表示（データ取得失敗時など）
   * @param {string} containerId - コンテナID
   * @param {string} message - メッセージ
   * @param {Function} retryCallback - リトライ時のコールバック
   */
  showSectionError(containerId, message, retryCallback = null) {
    const container = document.getElementById(containerId);
    if (!container) {
      console.warn(`Container not found: ${containerId}`);
      return;
    }
    
    const retryButton = retryCallback 
      ? `<button class="btn btn-sm btn-outline-primary ms-2" onclick="${retryCallback}">Retry</button>`
      : '';
    
    container.innerHTML = `
      <div class="alert alert-warning" role="alert">
        <i class="bi bi-exclamation-triangle"></i>
        ${escapeHtml(message)}
        ${retryButton}
      </div>
    `;
  }
  
  /**
   * セクション読み込み中表示
   * @param {string} containerId - コンテナID
   * @param {string} message - メッセージ
   */
  showSectionLoading(containerId, message = 'Loading...') {
    const container = document.getElementById(containerId);
    if (!container) {
      console.warn(`Container not found: ${containerId}`);
      return;
    }
    
    container.innerHTML = `
      <div class="text-center text-muted p-4">
        <div class="spinner-border spinner-border-sm me-2" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
        ${escapeHtml(message)}
      </div>
    `;
  }
  
  /**
   * セクションの空状態表示
   * @param {string} containerId - コンテナID
   * @param {string} message - メッセージ
   */
  showSectionEmpty(containerId, message = 'No data available') {
    const container = document.getElementById(containerId);
    if (!container) {
      console.warn(`Container not found: ${containerId}`);
      return;
    }
    
    container.innerHTML = `
      <div class="text-center text-muted p-4">
        <i class="bi bi-inbox"></i>
        <p class="mt-2 mb-0">${escapeHtml(message)}</p>
      </div>
    `;
  }
}

// グローバルインスタンス
const errorHandler = new UIErrorHandler();

console.log('✅ error-handler.js loaded successfully');
