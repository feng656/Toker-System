/**
 * 页面通用能力：四态数据加载（loading / error / empty / forbidden）与轻量反馈。
 * 所有列表页统一走 createAsyncState，保证每个页面都有可见的加载态、错误态（含重试）、
 * 空态与无权限态。
 */
import { reactive } from './vue.js';
import { ApiError } from './http.js';
import { httpErrorInfo } from './status.js';

const EP = () => window.ElementPlus;

export function toast(type, message) {
  const ep = EP();
  if (!ep || !ep.ElMessage) return;
  // ElMessage 是带 success/error/warning/info 静态方法的函数，必须以 ElMessage 为 this 调用
  const fn = ep.ElMessage[type] || ep.ElMessage.info;
  fn.call(ep.ElMessage, message);
}

export const notify = {
  ok: (m) => toast('success', m),
  err: (m) => toast('error', m),
  warn: (m) => toast('warning', m),
  info: (m) => toast('info', m),
};

/**
 * 错误的完整展示信息（标题 / 主文案 / 下一步 / 是否可重试）。
 * 页面需要倒计时或挑战时用本函数；只展示一行时用 errorMessage()。
 */
export function errorInfo(e) {
  if (e instanceof ApiError) {
    const info = httpErrorInfo(e.status, e.code, e.detail);
    if (e.rateLimited && Number.isFinite(e.retryAfter) && e.retryAfter > 0) {
      info.text = `${info.text}（约 ${e.retryAfter} 秒后可重试）`;
      info.retryAfter = e.retryAfter;
    }
    if ((e.unavailable || e.status === 503) && Number.isFinite(e.retryAfter) && e.retryAfter > 0) {
      info.next = `约 ${e.retryAfter} 秒后重试`;
    }
    return info;
  }
  return {
    code: 'unknown_error',
    title: '未知错误',
    text: (e && e.message) || '未知错误',
    next: '稍后重试；持续失败请联系管理员',
  };
}

export function errorMessage(e) {
  return errorInfo(e).text;
}

/**
 * 创建一个带四态的数据源。
 * @param {() => Promise<any>} fetcher
 * @param {any} initial 初值
 */
export function createAsyncState(fetcher, initial = null) {
  const state = reactive({
    loading: false,
    error: '',
    forbidden: false,
    loaded: false,
    data: initial,
  });

  async function reload() {
    state.loading = true;
    state.error = '';
    state.forbidden = false;
    try {
      const data = await fetcher();
      state.data = data;
      state.loaded = true;
      return data;
    } catch (e) {
      state.error = errorMessage(e);
      state.forbidden = !!(e && e.forbidden);
      state.loaded = true;
      throw e;
    } finally {
      state.loading = false;
    }
  }

  /** 静默刷新：失败只提示，不把页面打成错误态 */
  async function reloadQuiet() {
    try { return await reload(); } catch (e) { notify.warn(errorMessage(e)); return null; }
  }

  return { state, reload, reloadQuiet };
}

/** 数组型数据的空态判断 */
export function isEmpty(data) {
  if (data === null || data === undefined) return true;
  if (Array.isArray(data)) return data.length === 0;
  return false;
}
