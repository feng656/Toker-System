/**
 * 认证与用户（对应后端 app/api.py 的 /auth/* 与 /users）
 */
import { http } from '../core/http.js';

export const authApi = {
  /**
   * 登录。extra 可带 challenge_token / challenge_answer，用于 429 后的安全验证。
   */
  login: (username, password, extra) =>
    http.post('/auth/login', { username, password, ...(extra || {}) }),
  me: () => http.get('/auth/me'),
  /**
   * 注册开关与默认角色。后端未实现时返回 404，页面按「未开放」处理。
   * 约定响应：{enabled, invite_required, default_role, approval_required, reason}
   */
  registerConfig: () => http.get('/auth/register/config'),
  /** 邀请码注册：{username, password, invite_code, name} */
  register: (body) => http.post('/auth/register', body),
  listUsers: () => http.get('/users'),
  createUser: (body) => http.post('/users', body),
};
