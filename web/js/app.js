/**
 * 应用入口：登录、路由（hash 路由 + 角色守卫）、菜单、全局计数。
 * 只做「壳」与权限，不放业务逻辑；业务逻辑在 js/pages/* 与 js/api/*。
 */
import { createApp, ref, reactive, computed, onMounted } from './core/vue.js';
import { AUTH_EXPIRED_EVENT } from './core/http.js';
import {
  session, setSession, clearSession, visibleMenus, counters, platformModes,
  canAccess, defaultRoute, isAdmin,
} from './core/store.js';
import { notify, errorMessage } from './core/ui.js';
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

const app = createApp({
  setup() {
    const loginForm = reactive({ username: '', password: '' });
    const loginError = ref('');
    const loginLoading = ref(false);
    const route = ref(defaultRoute());
    const routeError = ref(null);

    const currentPage = computed(() => PAGES[route.value] || PageWork);

    /** 菜单（带待办计数红点） */
    const menuItems = computed(() => visibleMenus.value.map((m) => ({
      ...m,
      badge: m.key === 'todo' ? counters.pending : 0,
    })));

    const fallbackRoute = computed(() => defaultRoute());

    const modeSummary = computed(() => {
      const modes = Object.keys(platformModes);
      if (!modes.length) return '平台模式加载中';
      const auto = modes.filter((p) => platformModes[p] === 'auto');
      return auto.length ? `${auto.length} 个平台可自动发布，其余人工发布` : '全部平台：人工发布（复制文案）';
    });

    /* ---------------- 登录 ---------------- */
    async function doLogin() {
      loginError.value = '';
      if (!loginForm.username.trim() || !loginForm.password) {
        loginError.value = '请输入账号与密码';
        return;
      }
      loginLoading.value = true;
      try {
        const d = await window.fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: loginForm.username.trim(), password: loginForm.password }),
        }).then((r) => r.json());
        if (d && d.token) {
          setSession(d.token, d.user || {});
          loginForm.password = '';
          navigate(defaultRoute(), true);
          await afterLogin();
        } else {
          loginError.value = (d && (d.detail || d.msg)) || '登录失败';
        }
      } catch (e) {
        loginError.value = '无法连接后端服务，请确认服务已启动';
      } finally {
        loginLoading.value = false;
      }
    }

    function logout() {
      clearSession();
      counters.pending = 0;
      routeError.value = null;
    }

    /* ---------------- 路由 ---------------- */
    function parseHash() {
      const raw = (window.location.hash || '').replace(/^#\/?/, '').split('?')[0];
      return raw || defaultRoute();
    }

    function navigate(key, replace) {
      if (!PAGES[key]) key = defaultRoute();
      routeError.value = null;
      if (replace) window.location.replace(`#/${key}`);
      else window.location.hash = `#/${key}`;
      route.value = key;
    }

    function applyRoute() {
      const key = parseHash();
      if (!PAGES[key]) {
        routeError.value = { title: '页面不存在', sub: `没有找到「${key}」这个页面。` };
        route.value = defaultRoute();
        return;
      }
      if (!canAccess(key)) {
        routeError.value = {
          title: '没有访问权限',
          sub: `当前角色（${roleName(session.user.role)}）不可访问该页面。可访问页面：${visibleMenus.value.map((m) => m.title).join('、')}。`,
        };
        route.value = key;
        return;
      }
      routeError.value = null;
      route.value = key;
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

    onMounted(async () => {
      window.addEventListener('hashchange', applyRoute);
      window.addEventListener(AUTH_EXPIRED_EVENT, () => {
        clearSession();
        notify.warn('登录已失效，请重新登录');
      });

      if (session.token) {
        try {
          const u = await window.fetch('/api/auth/me', {
            headers: { Authorization: `Bearer ${session.token}` },
          }).then((r) => (r.ok ? r.json() : null));
          if (u && u.role) {
            session.user = u;
            session.loaded = true;
            applyRoute();
            await afterLogin();
          } else {
            clearSession();
          }
        } catch (e) {
          clearSession();
        }
      } else {
        applyRoute();
      }
      window.setInterval(refreshCounters, 60000);
    });

    return {
      session, loginForm, loginError, loginLoading, route, routeError, currentPage,
      visibleMenus, menuItems, fallbackRoute, modeSummary,
      doLogin, logout, navigate, defaultRoute, roleName, isAdmin,
    };
  },
});

app.use(window.ElementPlus, { locale: window.ElementPlusLocaleZhCn });
app.mount('#app');
