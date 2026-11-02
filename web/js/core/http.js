/**
 * 统一 HTTP 层。
 * 职责：
 *  1. 注入登录令牌（与后端 app/auth.py 的 Bearer 约定一致）
 *  2. 归一化错误（网络异常 / 4xx / 5xx → ApiError），供页面按四态渲染
 *  3. 401 统一处理：清会话 + 广播会话失效事件
 *  4. 统一前缀 /api（后端 app/main.py 的 include_router(prefix="/api")）
 */

const API_PREFIX = '/api';
const TOKEN_KEY = 'tk_token';

/** 会话失效事件名（app.js 订阅后跳登录页） */
export const AUTH_EXPIRED_EVENT = 'tk:auth-expired';

export class ApiError extends Error {
  constructor(status, detail, url) {
    super(detail || `请求失败（${status}）`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail || '';
    this.url = url || '';
  }

  /** 是否为「无权限」 */
  get forbidden() { return this.status === 403; }
  /** 是否为「未登录 / 会话失效」 */
  get unauthorized() { return this.status === 401; }
  /** 是否为网络层异常（服务未起 / 断网） */
  get offline() { return this.status === 0; }
}

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* 隐私模式下 localStorage 不可用，忽略 */ }
}

function buildQuery(query) {
  if (!query) return '';
  const usp = new URLSearchParams();
  Object.keys(query).forEach((k) => {
    const v = query[k];
    if (v === undefined || v === null || v === '') return;
    usp.append(k, v);
  });
  const s = usp.toString();
  return s ? `?${s}` : '';
}

async function readBody(res) {
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    try { return await res.json(); } catch (e) { return null; }
  }
  try { return await res.text(); } catch (e) { return null; }
}

function extractDetail(body) {
  if (body == null) return '';
  if (typeof body === 'string') return body.slice(0, 300);
  if (body.detail) {
    if (Array.isArray(body.detail)) {
      // FastAPI 参数校验错误
      return body.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
    }
    return String(body.detail);
  }
  if (body.msg) return String(body.msg);
  return '';
}

/**
 * 发起请求。
 * @param {string} path 以 / 开头的接口路径，如 '/contents'
 * @param {{method?:string, body?:any, query?:object, headers?:object, form?:boolean, raw?:boolean}} options
 */
export async function request(path, options = {}) {
  const { method = 'GET', body, query, headers = {}, form = false, raw = false } = options;
  const url = API_PREFIX + path + buildQuery(query);
  const h = { ...headers };
  const token = getToken();
  if (token) h.Authorization = `Bearer ${token}`;
  let payload;
  if (form) {
    payload = body; // FormData，交给浏览器自动带 boundary
  } else if (body !== undefined && body !== null) {
    h['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(url, { method, headers: h, body: payload });
  } catch (e) {
    throw new ApiError(0, '网络异常，请检查后端服务是否已启动', url);
  }

  if (res.status === 401) {
    setToken('');
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new ApiError(401, extractDetail(await readBody(res)) || '登录已失效，请重新登录', url);
  }

  if (raw) {
    if (!res.ok) throw new ApiError(res.status, extractDetail(await readBody(res)), url);
    return res;
  }

  const data = await readBody(res);
  if (!res.ok) {
    throw new ApiError(res.status, extractDetail(data) || `请求失败（${res.status}）`, url);
  }
  return data;
}

export const http = {
  get: (path, query, options) => request(path, { ...options, method: 'GET', query }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
  put: (path, body, options) => request(path, { ...options, method: 'PUT', body }),
  del: (path, options) => request(path, { ...options, method: 'DELETE' }),
  upload: (path, formData, options) => request(path, { ...options, method: 'POST', body: formData, form: true }),
};
