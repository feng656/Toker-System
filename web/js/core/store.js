/**
 * 全局会话与权限状态。
 * 角色可见范围与《分工》文档 4.2「设置与帮助：角色可见范围」一致：
 *   admin    —— 全部页面 + 平台凭据 / 合规红线 / 用户管理
 *   operator —— 业务页面（工作台 / 待办 / 内容 / 素材 / 选题 / 线索 / 看板）
 *   sales    —— 线索看板 + 数据看板（只读）+ 设置与帮助
 */
import { reactive, computed } from './vue.js';
import { getToken, setToken } from './http.js';

export const session = reactive({
  token: getToken(),
  user: { id: null, name: '', role: '' },
  loaded: false,
});

export function setSession(token, user) {
  session.token = token || '';
  session.user = user || { id: null, name: '', role: '' };
  session.loaded = true;
  setToken(session.token);
}

export function clearSession() {
  session.token = '';
  session.user = { id: null, name: '', role: '' };
  session.loaded = false;
  setToken('');
}

export function isAdmin() { return session.user.role === 'admin'; }
export function isOperator() { return session.user.role === 'operator'; }
export function isSales() { return session.user.role === 'sales'; }
export function canWriteContent() { return isAdmin() || isOperator(); }

/** 页面级权限表：key → 允许访问的角色 */
export const PAGE_ROLES = {
  work: ['admin', 'operator'],
  todo: ['admin', 'operator'],
  contents: ['admin', 'operator'],
  materials: ['admin', 'operator'],
  topics: ['admin', 'operator'],
  leads: ['admin', 'operator', 'sales'],
  dashboard: ['admin', 'operator', 'sales'],
  settings: ['admin', 'operator', 'sales'],
  help: ['admin', 'operator', 'sales'],
};

export function canAccess(pageKey) {
  const roles = PAGE_ROLES[pageKey];
  if (!roles) return false;
  return roles.indexOf(session.user.role) >= 0;
}

/**
 * 二期 R8 一级菜单：6 个。
 * 今日待办并入工作台、选题池并入内容、帮助并入设置；旧 hash 仍可跳转。
 */
export const MENUS = [
  { key: 'work', title: '工作台', icon: '⚡', roles: PAGE_ROLES.work, badge: 'pending' },
  { key: 'contents', title: '内容', icon: '📝', roles: PAGE_ROLES.contents },
  { key: 'materials', title: '素材', icon: '📚', roles: PAGE_ROLES.materials },
  { key: 'leads', title: '线索', icon: '🎯', roles: PAGE_ROLES.leads },
  { key: 'dashboard', title: '数据', icon: '📊', roles: PAGE_ROLES.dashboard },
  { key: 'settings', title: '设置', icon: '⚙️', roles: PAGE_ROLES.settings },
];

/** 二级 tab：key 同时是页面组件 key（PAGES[key]） */
export const PAGE_TABS = {
  work: [
    { key: 'work', title: '投放工作台', roles: PAGE_ROLES.work },
    { key: 'todo', title: '今日待办', roles: PAGE_ROLES.todo },
  ],
  contents: [
    { key: 'contents', title: '内容管理', roles: PAGE_ROLES.contents },
    { key: 'topics', title: '选题池', roles: PAGE_ROLES.topics },
  ],
  settings: [
    { key: 'settings', title: '设置', roles: PAGE_ROLES.settings },
    { key: 'help', title: '帮助', roles: PAGE_ROLES.help },
  ],
  materials: [],
  leads: [],
  dashboard: [],
};

/** 旧 hash → 新页面/二级 tab */
export const LEGACY_ROUTES = {
  todo: { page: 'work', tab: 'todo' },
  topics: { page: 'contents', tab: 'topics' },
  help: { page: 'settings', tab: 'help' },
};

export const visibleMenus = computed(() =>
  MENUS.filter((m) => m.roles.indexOf(session.user.role) >= 0));

/** 当前角色可见的二级 tab；无 tab 的页面返回空数组 */
export function tabsFor(pageKey) {
  const tabs = PAGE_TABS[pageKey] || [];
  return tabs.filter((t) => t.roles.indexOf(session.user.role) >= 0);
}

/** 页面默认 tab（页面本身） */
export function defaultTab(pageKey) {
  return pageKey;
}

/** 首页（按角色落地页） */
export function defaultRoute() {
  if (session.user.role === 'sales') return 'leads';
  return 'work';
}

/** 全局计数：待办条数（菜单红点） */
export const counters = reactive({ pending: 0 });

export const platformModes = reactive({}); // platform → 'auto' | 'copy'
