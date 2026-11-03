/**
 * 页面通用能力：四态数据加载（loading / error / empty / forbidden）与轻量反馈。
 * 所有列表页统一走 createAsyncState，保证每个页面都有可见的加载态、错误态（含重试）、
 * 空态与无权限态。
 */
import { reactive } from './vue.js';
import { ApiError } from './http.js';

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

export function errorMessage(e) {
  if (e instanceof ApiError) {
    if (e.offline) return '网络异常：连不上后端服务，请确认服务已启动后重试';
    if (e.forbidden) return '当前角色没有该操作的权限';
    if (e.unauthorized) return '登录已失效，请重新登录';
    return e.detail || `请求失败（${e.status}）`;
  }
  return (e && e.message) || '未知错误';
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
