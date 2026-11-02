/**
 * 线索 / 互动 / 指标 / 看板（后端 /leads、/interactions、/metrics、/dashboard/*、/reports/*）
 *
 * 已知后端缺口（见《接口缺口清单.md》）：
 *  - GAP-05 /dashboard/trend、/dashboard/topics 不存在 → 看板趋势由前端从 /contents 明细本地聚合
 *  - GAP-06 无 GET /interactions 列表 → 线索详情看不到评论原文
 *  - GAP-07 无 GET /metrics 列表 → 指标明细只能按版本回查
 *  - GAP-08 线索 30 天去重未实现 → 前端只做重复提示，不代替后端判定
 */
import { http } from '../core/http.js';

export const leadApi = {
  list: (query) => http.get('/leads', query),
  update: (id, body) => http.put(`/leads/${id}`, body),
  push: (id) => http.post(`/leads/${id}/push`),
};

export const interactionApi = {
  create: (body) => http.post('/interactions', body),
};

export const metricApi = {
  save: (body) => http.post('/metrics', body),
};

export const dashboardApi = {
  funnel: () => http.get('/dashboard/funnel'),
  weeklyReports: () => http.get('/reports/weekly'),
};
