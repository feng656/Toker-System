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

/** 菜单定义（图标沿用原型版） */
export const MENUS = [
  { key: 'work', title: '工作台', icon: '⚡', roles: PAGE_ROLES.work },
  { key: 'todo', title: '今日待办', icon: '📋', roles: PAGE_ROLES.todo },
  { key: 'contents', title: '内容管理', icon: '📝', roles: PAGE_ROLES.contents },
  { key: 'materials', title: '素材库', icon: '📚', roles: PAGE_ROLES.materials },
  { key: 'topics', title: '选题池', icon: '💡', roles: PAGE_ROLES.topics },
  { key: 'leads', title: '线索看板', icon: '🎯', roles: PAGE_ROLES.leads },
  { key: 'dashboard', title: '数据看板', icon: '📊', roles: PAGE_ROLES.dashboard },
  { key: 'settings', title: '设置', icon: '⚙️', roles: PAGE_ROLES.settings },
  { key: 'help', title: '帮助', icon: '❓', roles: PAGE_ROLES.help },
];

export const visibleMenus = computed(() =>
  MENUS.filter((m) => m.roles.indexOf(session.user.role) >= 0));

/** 首页（按角色落地页） */
export function defaultRoute() {
  if (session.user.role === 'sales') return 'leads';
  return 'work';
}

/** 全局计数：待办条数（菜单红点） */
export const counters = reactive({ pending: 0 });

export const platformModes = reactive({}); // platform → 'auto' | 'copy'
