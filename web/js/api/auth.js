/**
 * 认证与用户（对应后端 app/api.py 的 /auth/* 与 /users）
 */
import { http } from '../core/http.js';

export const authApi = {
  login: (username, password) =>
    http.post('/auth/login', { username, password }),
  me: () => http.get('/auth/me'),
  listUsers: () => http.get('/users'),
  createUser: (body) => http.post('/users', body),
};
