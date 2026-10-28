/**
 * Stock Swing Console - Utility Functions
 * Safe data access and formatting utilities
 */

/**
 * 安全にネストされたプロパティを取得する
 * @param {Object} obj - オブジェクト
 * @param {string} path - パス（'a.b.c'形式）
 * @param {*} defaultValue - デフォルト値
 * @returns {*} 値またはデフォルト値
 */
function safeGet(obj, path, defaultValue = null) {
  try {
    if (!obj || typeof obj !== 'object') {
      return defaultValue;
    }
    
    const keys = path.split('.');
    let result = obj;
    
    for (const key of keys) {
      if (result === null || result === undefined) {
        return defaultValue;
      }
      result = result[key];
    }
    
    return result !== undefined && result !== null ? result : defaultValue;
  } catch (e) {
    console.warn(`safeGet error for path "${path}":`, e);
    return defaultValue;
  }
}

/**
 * 安全に数値に変換する
 * @param {*} value - 値
 * @param {number} defaultValue - デフォルト値
 * @returns {number} 数値
 */
function safeNumber(value, defaultValue = 0) {
  if (value === null || value === undefined || value === '') {
    return defaultValue;
  }
  
  const num = parseFloat(value);
  return isNaN(num) ? defaultValue : num;
}

/**
 * 安全にパーセンテージをフォーマットする
 * @param {*} value - 値（0.05 = 5%）
 * @param {number} decimals - 小数点以下の桁数
 * @returns {string} フォーマット済み文字列
 */
function safePercent(value, decimals = 2) {
  const num = safeNumber(value, 0);
  return (num * 100).toFixed(decimals) + '%';
}

/**
 * 安全に通貨をフォーマットする
 * @param {*} value - 値
 * @param {number} decimals - 小数点以下の桁数
 * @returns {string} フォーマット済み文字列
 */
function safeCurrency(value, decimals = 2) {
  const num = safeNumber(value, 0);
  return '$' + num.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

/**
 * 安全に配列を取得する
 * @param {*} value - 値
 * @returns {Array} 配列（空配列をデフォルト）
 */
function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

/**
 * 安全に整数をフォーマットする
 * @param {*} value - 値
 * @returns {string} フォーマット済み文字列
 */
function safeInt(value) {
  const num = safeNumber(value, 0);
  return Math.floor(num).toLocaleString('en-US');
}

/**
 * HTMLをエスケープする（改善版）
 * @param {*} value - 値
 * @returns {string} エスケープ済み文字列
 */
function escapeHtml(value) {
  if (value === null || value === undefined) {
    return '';
  }
  
  const str = String(value);
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  
  return str.replace(/[&<>"']/g, m => map[m]);
}

/**
 * 日時を安全にフォーマットする
 * @param {*} value - ISO文字列または Date オブジェクト
 * @param {boolean} includeTime - 時刻を含めるか
 * @returns {string} フォーマット済み文字列
 */
function safeDate(value, includeTime = false) {
  if (!value) return 'N/A';
  
  try {
    const date = typeof value === 'string' ? new Date(value) : value;
    
    if (isNaN(date.getTime())) {
      return 'Invalid Date';
    }
    
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    
    if (!includeTime) {
      return `${year}-${month}-${day}`;
    }
    
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
    
  } catch (e) {
    console.warn('safeDate error:', e);
    return 'N/A';
  }
}

/**
 * 相対時間をフォーマットする（"2 hours ago"など）
 * @param {*} value - ISO文字列または Date オブジェクト
 * @returns {string} フォーマット済み文字列
 */
function safeRelativeTime(value) {
  if (!value) return 'N/A';
  
  try {
    const date = typeof value === 'string' ? new Date(value) : value;
    
    if (isNaN(date.getTime())) {
      return 'Invalid Date';
    }
    
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);
    
    if (diffDay > 0) return `${diffDay}d ago`;
    if (diffHour > 0) return `${diffHour}h ago`;
    if (diffMin > 0) return `${diffMin}m ago`;
    return `${diffSec}s ago`;
    
  } catch (e) {
    console.warn('safeRelativeTime error:', e);
    return 'N/A';
  }
}

/**
 * 色分けクラスを取得（数値に応じて）
 * @param {number} value - 数値
 * @param {number} threshold - 閾値（デフォルト0）
 * @returns {string} CSSクラス名
 */
function getColorClass(value, threshold = 0) {
  const num = safeNumber(value, 0);
  
  if (num > threshold) return 'text-success';
  if (num < -threshold) return 'text-danger';
  return 'text-muted';
}

/**
 * バッジクラスを取得（数値に応じて）
 * @param {number} value - 数値
 * @returns {string} CSSクラス名
 */
function getBadgeClass(value) {
  const num = safeNumber(value, 0);
  
  if (num > 0) return 'badge bg-success';
  if (num < 0) return 'badge bg-danger';
  return 'badge bg-secondary';
}

// テスト用のログ関数
if (typeof console !== 'undefined' && console.log) {
  console.log('✅ utils.js loaded successfully');
}
