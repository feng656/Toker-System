/**
 * 统一 HTTP 层。
 * 职责：
 *  1. 注入登录令牌（与后端 app/auth.py 的 Bearer 约定一致）
 *  2. 归一化错误（网络异常 / 4xx / 5xx → ApiError），供页面按四态渲染
 *  3. 401 统一处理：清会话 + 广播会话失效事件（仅当请求确实带过令牌）
 *  4. 默认前缀 /api/v1；保留 /api 过渡开关，见 docs/phase2/M-P0-03-api-v1迁移清单.md
 *  5. 错误附带 code / retry_after / challenge / request_id，供 429、409 等精细处理
 */

const DEFAULT_API_PREFIX = '/api/v1';
const ALLOWED_PREFIXES = ['/api/v1', '/api'];
const PREFIX_KEY = 'tk_api_prefix';
const TOKEN_KEY = 'tk_token';

/** 会话失效事件名（app.js 订阅后跳登录页） */
export const AUTH_EXPIRED_EVENT = 'tk:auth-expired';

/* ---------------- 前缀（过渡开关） ---------------- */

function normalizePrefix(value) {
  return ALLOWED_PREFIXES.indexOf(value) >= 0 ? value : '';
}

/** 当前 API 前缀；localStorage 优先，其次 window 覆盖，最后默认 /api/v1 */
export function getApiPrefix() {
  try {
    const stored = normalizePrefix(localStorage.getItem(PREFIX_KEY));
    if (stored) return stored;
  } catch (e) { /* 隐私模式 */ }
  try {
    const injected = normalizePrefix(window.__TK_API_PREFIX__);
    if (injected) return injected;
  } catch (e) { /* 忽略 */ }
  return DEFAULT_API_PREFIX;
}

/** 临时切回旧前缀：setApiPrefix('/api')；传空值恢复默认 */
export function setApiPrefix(prefix) {
  try {
    if (prefix === DEFAULT_API_PREFIX || !prefix) localStorage.removeItem(PREFIX_KEY);
    else if (normalizePrefix(prefix)) localStorage.setItem(PREFIX_KEY, prefix);
  } catch (e) { /* 忽略 */ }
}

export { DEFAULT_API_PREFIX };

/* ---------------- 错误对象 ---------------- */

export class ApiError extends Error {
  constructor(status, detail, url, meta = {}) {
    super(detail || `请求失败（${status}）`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail || '';
    this.url = url || '';
    this.code = meta.code || '';
    this.retryAfter = meta.retryAfter !== undefined && meta.retryAfter !== null
      ? Number(meta.retryAfter) : null;
    this.challenge = meta.challenge || null;
    this.requestId = meta.requestId || '';
    this.currentVersion = meta.currentVersion;
    this.expectedVersion = meta.expectedVersion;
    this.payload = meta.payload;
  }

  /** 是否为「无权限」 */
  get forbidden() { return this.status === 403; }
  /** 是否为「未登录 / 会话失效」 */
  get unauthorized() { return this.status === 401; }
  /** 是否为网络层异常（服务未起 / 断网 / 超时） */
  get offline() { return this.status === 0; }
  /** 是否限流 */
  get rateLimited() { return this.status === 429; }
  /** 是否状态/乐观锁冲突 */
  get conflict() { return this.status === 409; }
  /** 是否参数校验失败 */
  get validation() { return this.status === 422; }
  /** 是否依赖不可用 */
  get unavailable() { return this.status === 503; }
}

/* ---------------- 令牌 ---------------- */

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* 隐私模式下 localStorage 不可用，忽略 */ }
}

/* ---------------- 请求 ---------------- */

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
    if (typeof body.detail === 'object') {
      return String(body.detail.message || body.detail.msg || body.detail.code || '');
    }
    return String(body.detail);
  }
  if (body.message) return String(body.message);
  if (body.msg) return String(body.msg);
  return '';
}

function extractMeta(body, res) {
  const obj = body && typeof body === 'object' ? body : {};
  const detailObj = obj.detail && typeof obj.detail === 'object' ? obj.detail : {};
  const headerRetry = res.headers.get('Retry-After');
  const rawRetry = headerRetry !== null ? headerRetry
    : (obj.retry_after !== undefined ? obj.retry_after : detailObj.retry_after);
  return {
    code: obj.code || detailObj.code || '',
    retryAfter: rawRetry !== undefined && rawRetry !== null ? rawRetry : null,
    challenge: obj.challenge || detailObj.challenge || null,
    requestId: res.headers.get('X-Request-Id') || res.headers.get('x-request-id') || obj.request_id || '',
    currentVersion: obj.current_version !== undefined ? obj.current_version : detailObj.current_version,
    expectedVersion: obj.expected_version !== undefined ? obj.expected_version : detailObj.expected_version,
    payload: obj,
  };
}

/**
 * 发起请求。
 * @param {string} path 以 / 开头的接口路径，如 '/contents'
 * @param {{method?:string, body?:any, query?:object, headers?:object, form?:boolean, raw?:boolean, timeoutMs?:number}} options
 */
export async function request(path, options = {}) {
  const {
    method = 'GET', body, query, headers = {}, form = false, raw = false,
    timeoutMs = 30000,
  } = options;

  const prefix = getApiPrefix();
  const url = prefix + path + buildQuery(query);
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

  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  let timer = null;
  if (controller && timeoutMs > 0) {
    timer = window.setTimeout(() => controller.abort(), timeoutMs);
  }

  let res;
  try {
    res = await fetch(url, {
      method, headers: h, body: payload, signal: controller ? controller.signal : undefined,
    });
  } catch (e) {
    if (e && e.name === 'AbortError') {
      throw new ApiError(0, '请求超时，请稍后重试', url, { code: 'timeout' });
    }
    throw new ApiError(0, '网络异常，请检查后端服务是否已启动', url, { code: 'network_error' });
  } finally {
    if (timer) window.clearTimeout(timer);
  }

  if (res.status === 401) {
    const body401 = await readBody(res);
    const meta401 = extractMeta(body401, res);
    if (token) {
      setToken('');
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    }
    throw new ApiError(401, extractDetail(body401) || '登录已失效，请重新登录', url, meta401);
  }

  if (raw) {
    if (!res.ok) {
      const bodyRaw = await readBody(res);
      throw new ApiError(res.status, extractDetail(bodyRaw), url, extractMeta(bodyRaw, res));
    }
    return res;
  }

  const data = await readBody(res);
  if (!res.ok) {
    const meta = extractMeta(data, res);
    throw new ApiError(
      res.status,
      extractDetail(data) || `请求失败（${res.status}）`,
      url,
      meta,
    );
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
