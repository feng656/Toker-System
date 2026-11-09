/**
 * 应用入口：登录/注册、路由（hash 路由 + 二级 tab + 角色守卫）、菜单、全局计数。
 * 只做「壳」与权限，不放业务逻辑；业务逻辑在 js/pages/* 与 js/api/*。
 *
 * 二期 R8：一级菜单 6 个；今日待办并入工作台、选题池并入内容、帮助并入设置。
 * 旧 hash（#/todo、#/topics、#/help）自动重定向到新地址。
 */
import { createApp, ref, reactive, computed, onMounted, onUnmounted } from './core/vue.js';
import { AUTH_EXPIRED_EVENT, ApiError } from './core/http.js';
import {
  session, setSession, clearSession, visibleMenus, counters, platformModes,
  canAccess, defaultRoute, isAdmin, tabsFor, LEGACY_ROUTES,
} from './core/store.js';
import { notify, errorMessage, errorInfo } from './core/ui.js';
import { authApi } from './api/auth.js';
import { contentApi } from './api/content.js';
import { platformApi } from './api/platform.js';
import { roleName } from './core/format.js';

import PageWork from './pages/work.js';
import PageTodo from './pages/todo.js';
import PageContents from './pages/contents.js';
import PageMaterials from './pages/materials.js';
import PageTopics from './pages/topics.js';
import PageLeads from './pages/leads.js';
import PageDashboard from './pages/dashboard.js';
import PageSettings from './pages/settings.js';
import PageHelp from './pages/help.js';

const PAGES = {
  work: PageWork,
  todo: PageTodo,
  contents: PageContents,
  materials: PageMaterials,
  topics: PageTopics,
  leads: PageLeads,
  dashboard: PageDashboard,
  settings: PageSettings,
  help: PageHelp,
};

function hashOf(page, tab) {
  return `#/${page}${tab && tab !== page ? `?tab=${tab}` : ''}`;
}

const app = createApp({
  setup() {
    /* ---------------- 登录 ---------------- */
    const loginForm = reactive({ username: '', password: '', challenge_answer: '' });
    const loginError = ref('');
    const loginLoading = ref(false);
    const retryLeft = ref(0);
    const challenge = ref(null);
    let retryTimer = null;

    /* ---------------- 注册 ---------------- */
    const registerMode = ref(false);
    const regForm = reactive({ username: '', password: '', confirm: '', invite_code: '', name: '' });
    const regLoading = ref(false);
    const regError = ref('');
    const regNotice = ref('');
    const regRetryLeft = ref(0);
    let regRetryTimer = null;
    const regConfig = reactive({
      enabled: false,
      invite_required: true,
      default_role: 'sales',
      approval_required: true,
      checked: false,
      reason: '当前未开放自主注册，请联系管理员开通。',
    });

    const passwordStrength = computed(() => {
      const p = regForm.password || '';
      let score = 0;
      if (p.length >= 8) score += 1;
      if (/[A-Za-z]/.test(p) && /\d/.test(p)) score += 1;
      if (p.length >= 12 || /[^A-Za-z0-9]/.test(p)) score += 1;
      const labels = ['太弱', '较弱', '可用', '较强'];
      return {
        score,
        label: labels[score] || '太弱',
        ok: p.length >= 8 && /[A-Za-z]/.test(p) && /\d/.test(p) && p !== regForm.username,
      };
    });

    const canSubmitRegister = computed(() => (
      regConfig.enabled
      && !regLoading.value
      && regRetryLeft.value === 0
      && regForm.username.trim().length >= 2
      && passwordStrength.value.ok
      && regForm.password === regForm.confirm
      && (!regConfig.invite_required || regForm.invite_code.trim().length > 0)
    ));

    /* ---------------- 路由 ---------------- */
    const route = ref(defaultRoute());
    const routeTab = ref(defaultRoute());
    const routeError = ref(null);

    const currentPage = computed(() => PAGES[routeTab.value] || PAGES[route.value] || PageWork);
    const currentTabs = computed(() => tabsFor(route.value));
    const currentMenuTitle = computed(() => {
      const m = visibleMenus.value.find((x) => x.key === route.value);
      return m ? m.title : '';
    });
    const currentTabTitle = computed(() => {
      const t = currentTabs.value.find((x) => x.key === routeTab.value);
      return t ? t.title : currentMenuTitle.value;
    });

    const menuItems = computed(() => visibleMenus.value.map((m) => ({
      ...m,
      badge: m.badge === 'pending' ? counters.pending : 0,
    })));

    const fallbackRoute = computed(() => defaultRoute());

    const modeSummary = computed(() => {
      const modes = Object.keys(platformModes);
      if (!modes.length) return '平台模式加载中';
      const auto = modes.filter((p) => platformModes[p] === 'auto');
      return auto.length ? `${auto.length} 个平台可自动发布，其余人工发布` : '全部平台：人工发布（复制文案）';
    });

    function parseHash() {
      const raw = (window.location.hash || '').replace(/^#\/?/, '');
      const q = raw.indexOf('?');
      const pathPart = (q >= 0 ? raw.slice(0, q) : raw) || defaultRoute();
      const params = new URLSearchParams(q >= 0 ? raw.slice(q + 1) : '');
      return { page: pathPart, tab: params.get('tab') || '' };
    }

    function resolveRoute() {
      const parsed = parseHash();
      let page = parsed.page;
      let tab = parsed.tab;
      let legacy = false;
      const mapped = LEGACY_ROUTES[page];
      if (mapped) {
        page = mapped.page;
        tab = mapped.tab;
        legacy = true;
      }
      return { page, tab, legacy };
    }

    function applyRoute() {
      const r = resolveRoute();
      if (!PAGES[r.page]) {
        routeError.value = { title: '页面不存在', sub: `没有找到「${r.page}」这个页面。` };
        route.value = defaultRoute();
        routeTab.value = defaultRoute();
        return;
      }
      if (!canAccess(r.page)) {
        routeError.value = {
          title: '没有访问权限',
          sub: `当前角色（${roleName(session.user.role)}）不可访问该页面。可访问页面：${visibleMenus.value.map((m) => m.title).join('、')}。`,
        };
        route.value = r.page;
        routeTab.value = r.page;
        return;
      }
      routeError.value = null;
      route.value = r.page;

      const tabs = tabsFor(r.page);
      let tab = r.tab;
      if (tabs.length) {
        if (!tab || !tabs.some((t) => t.key === tab)) tab = tabs[0].key;
        if (!canAccess(tab)) tab = r.page;
      } else {
        tab = r.page;
      }
      routeTab.value = tab;

      // 保留非 tab 的查询参数（内容管理筛选条件、外部深链参数），
      // 只规范化页面与 tab；否则刷新时会把 R4 的 URL 筛选清空。
      const current = (window.location.hash || '').replace(/^#/, '');
      const qIndex = current.indexOf('?');
      const extra = new URLSearchParams(qIndex >= 0 ? current.slice(qIndex + 1) : '');
      extra.delete('tab');
      const extraQs = extra.toString();
      const base = hashOf(r.page, tab);
      const expected = extraQs ? `${base}${base.indexOf('?') >= 0 ? '&' : '?'}${extraQs}` : base;
      if (r.legacy || current !== expected.slice(1)) {
        try { history.replaceState(null, '', expected); } catch (e) { /* 忽略 */ }
      }
    }

    function navigate(key, tab, replace) {
      // 兼容旧签名 navigate(key, true)
      if (typeof tab === 'boolean') { replace = tab; tab = ''; }
      const page = PAGES[key] ? key : defaultRoute();
      if (!canAccess(page)) {
        routeError.value = {
          title: '没有访问权限',
          sub: `当前角色（${roleName(session.user.role)}）不可访问该页面。`,
        };
        route.value = page;
        routeTab.value = page;
        return;
      }
      const tabs = tabsFor(page);
      let target = tab || (tabs.length ? tabs[0].key : page);
      if (tabs.length && !tabs.some((t) => t.key === target)) target = tabs[0].key;
      if (!canAccess(target)) target = page;
      routeError.value = null;
      const hash = hashOf(page, target);
      if (replace) {
        try { history.replaceState(null, '', hash); } catch (e) { /* 忽略 */ }
      } else {
        window.location.hash = hash;
      }
      route.value = page;
      routeTab.value = target;
    }

    /* ---------------- 登录逻辑 ---------------- */
    function stopRetry() {
      if (retryTimer) window.clearInterval(retryTimer);
      retryTimer = null;
      retryLeft.value = 0;
    }

    function startRetry(seconds) {
      stopRetry();
      const total = Math.max(1, Math.ceil(Number(seconds) || 30));
      retryLeft.value = total;
      retryTimer = window.setInterval(() => {
        retryLeft.value = Math.max(0, retryLeft.value - 1);
        if (retryLeft.value === 0) stopRetry();
      }, 1000);
    }

    function stopRegRetry() {
      if (regRetryTimer) window.clearInterval(regRetryTimer);
      regRetryTimer = null;
      regRetryLeft.value = 0;
    }

    function startRegRetry(seconds) {
      stopRegRetry();
      const total = Math.max(1, Math.ceil(Number(seconds) || 30));
      regRetryLeft.value = total;
      regRetryTimer = window.setInterval(() => {
        regRetryLeft.value = Math.max(0, regRetryLeft.value - 1);
        if (regRetryLeft.value === 0) stopRegRetry();
      }, 1000);
    }

    function applyChallenge(e) {
      if (e && e.challenge && typeof e.challenge === 'object') {
        challenge.value = { ...e.challenge };
        loginForm.challenge_answer = '';
      }
    }

    function handleLoginError(e) {
      const info = errorInfo(e);
      if (e instanceof ApiError) {
        if (e.status === 429) {
          applyChallenge(e);
          if (e.retryAfter) startRetry(e.retryAfter);
          loginError.value = challenge.value
            ? `${info.text}，请完成安全验证后重试`
            : info.text;
          return;
        }
        if (e.status === 401) {
          loginError.value = '账号或密码错误';
          return;
        }
        if (e.status === 403) {
          loginError.value = '账号已被停用，请联系管理员';
          return;
        }
        if (e.status === 404) {
          loginError.value = '登录接口不可用，请确认前后端版本一致';
          return;
        }
      }
      loginError.value = info.text || '登录失败，请稍后重试';
    }

    async function doLogin() {
      loginError.value = '';
      if (retryLeft.value > 0) return;
      if (!loginForm.username.trim() || !loginForm.password) {
        loginError.value = '请输入账号与密码';
        return;
      }
      loginLoading.value = true;
      try {
        const extra = {};
        if (challenge.value && challenge.value.token) {
          extra.challenge_token = challenge.value.token;
          extra.challenge_answer = loginForm.challenge_answer;
        }
        const d = await authApi.login(loginForm.username.trim(), loginForm.password, extra);
        if (d && d.token) {
          setSession(d.token, d.user || {});
          loginForm.password = '';
          loginForm.challenge_answer = '';
          challenge.value = null;
          registerMode.value = false;
          stopRetry();
          navigate(defaultRoute(), '', true);
          await afterLogin();
        } else {
          loginError.value = '登录失败：服务返回缺少令牌';
        }
      } catch (e) {
        handleLoginError(e);
      } finally {
        loginLoading.value = false;
      }
    }

    function logout() {
      clearSession();
      counters.pending = 0;
      routeError.value = null;
      stopRetry();
    }

    /* ---------------- 注册逻辑 ---------------- */
    async function loadRegisterConfig() {
      try {
        const cfg = await authApi.registerConfig();
        regConfig.enabled = !!cfg.enabled;
        regConfig.invite_required = cfg.invite_required !== false;
        regConfig.default_role = cfg.default_role || 'sales';
        regConfig.approval_required = cfg.approval_required !== false;
        regConfig.reason = cfg.reason || '';
        regConfig.checked = true;
      } catch (e) {
        regConfig.enabled = false;
        regConfig.checked = true;
        if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 405)) {
          regConfig.reason = '注册配置加载失败，当前按「未开放」处理；请联系管理员。';
        }
      }
    }

    function openRegister() {
      registerMode.value = true;
      regError.value = '';
      regNotice.value = '';
      if (!regConfig.checked) loadRegisterConfig();
    }

    function backToLogin() {
      registerMode.value = false;
      regError.value = '';
      regNotice.value = '';
    }

    function handleRegisterError(e) {
      const info = errorInfo(e);
      if (e instanceof ApiError) {
        if (e.status === 429) {
          if (e.retryAfter) startRegRetry(e.retryAfter);
          regError.value = info.text;
          return;
        }
        if (e.status === 403) {
          regError.value = '邀请码无效或已过期，请联系管理员';
          return;
        }
        if (e.status === 409) {
          regError.value = '账号已存在，请直接登录或更换账号';
          return;
        }
        if (e.status === 422) {
          regError.value = e.detail || '注册信息有误，请检查后重试';
          return;
        }
        if (e.status === 404) {
          regError.value = '自主注册未开放，请联系管理员开通。';
          return;
        }
      }
      regError.value = info.text || '注册失败，请稍后重试';
    }

    async function doRegister() {
      regError.value = '';
      regNotice.value = '';
      if (!regConfig.enabled) {
        regError.value = regConfig.reason || '自主注册未开放，请联系管理员。';
        return;
      }
      if (regRetryLeft.value > 0) return;
      if (regForm.username.trim().length < 2) {
        regError.value = '账号至少 2 个字符';
        return;
      }
      if (!passwordStrength.value.ok) {
        regError.value = '密码至少 8 位，且必须同时包含字母和数字';
        return;
      }
      if (regForm.password !== regForm.confirm) {
        regError.value = '两次输入的密码不一致';
        return;
      }
      if (regConfig.invite_required && !regForm.invite_code.trim()) {
        regError.value = '请填写邀请码';
        return;
      }
      regLoading.value = true;
      try {
        const d = await authApi.register({
          username: regForm.username.trim(),
          password: regForm.password,
          invite_code: regForm.invite_code.trim(),
          name: regForm.name.trim(),
        });
        const pending = d && (d.status === 'pending_approval' || d.approval_required === true);
        regNotice.value = pending
          ? `注册成功，账号待管理员审批。默认角色：${roleName(regConfig.default_role)}；审批通过后即可登录。`
          : `注册成功，已按「${roleName(regConfig.default_role)}」角色开通，请使用新账号登录。`;
        loginForm.username = regForm.username.trim();
        regForm.password = '';
        regForm.confirm = '';
        regForm.invite_code = '';
        window.setTimeout(() => { registerMode.value = false; }, 1200);
      } catch (e) {
        handleRegisterError(e);
      } finally {
        regLoading.value = false;
      }
    }

    /* ---------------- 会话与全局数据 ---------------- */
    async function afterLogin() {
      try {
        const st = await platformApi.status();
        (st || []).forEach((a) => { platformModes[a.platform] = a.mode; });
      } catch (e) { /* 平台模式不影响主流程 */ }
      await refreshCounters();
    }

    async function refreshCounters() {
      if (!session.token) return;
      if (!canAccess('todo')) { counters.pending = 0; return; }
      try {
        const d = await contentApi.todoToday();
        counters.pending = (d.pending || []).length;
      } catch (e) { /* 计数失败不阻塞页面 */ }
    }

    let counterTimer = null;

    onMounted(async () => {
      window.addEventListener('hashchange', applyRoute);
      window.addEventListener(AUTH_EXPIRED_EVENT, () => {
        clearSession();
        notify.warn('登录已失效，请重新登录');
      });

      loadRegisterConfig();

      if (session.token) {
        try {
          const u = await authApi.me();
          if (u && u.role) {
            session.user = u;
            session.loaded = true;
            applyRoute();
            await afterLogin();
          } else {
            clearSession();
          }
        } catch (e) {
          // 令牌无效、后端不可达或服务版本不一致时都回登录页；错误在登录页可重试。
          clearSession();
        }
      } else {
        applyRoute();
      }
      counterTimer = window.setInterval(refreshCounters, 60000);
    });

    onUnmounted(() => {
      window.removeEventListener('hashchange', applyRoute);
      if (counterTimer) window.clearInterval(counterTimer);
      stopRetry();
      stopRegRetry();
    });

    return {
      session, loginForm, loginError, loginLoading, retryLeft, challenge,
      registerMode, regForm, regLoading, regError, regNotice, regRetryLeft,
      regConfig, passwordStrength, canSubmitRegister,
      doLogin, doRegister, openRegister, backToLogin, logout,
      route, routeTab, routeError, currentPage, currentTabs,
      currentMenuTitle, currentTabTitle,
      visibleMenus, menuItems, fallbackRoute, modeSummary,
      navigate, defaultRoute, roleName, isAdmin,
    };
  },
});

app.use(window.ElementPlus, { locale: window.ElementPlusLocaleZhCn });
app.mount('#app');
