/**
 * 内容生产闭环（后端 /contents、/variants、/confirm/*、/generate/*、/todo/*）
 *
 * 已知后端缺口（前端以占位处理，见《接口缺口清单.md》）：
 *  - GAP-03 变体级驳回 / 重新生成：后端只有内容级 review，无变体重生成接口
 *  - GAP-04 待办按日期查询：/todo/today 固定「今天」，其他日期由前端用 /contents?scheduled= 派生
 */
import { http } from '../core/http.js';

export const contentApi = {
  list: (query) => http.get('/contents', query),
  /** 内容级审核：approve / reject（驳回必须带理由） */
  review: (id, action, note) => http.post(`/contents/${id}/review`, { action, note: note || '' }),
  /** 修改变体文案（保存后后端会重跑一次合规硬检） */
  updateVariant: (id, body) => http.put(`/variants/${id}`, body),
  /** 人工回填发布链接 */
  publish: (variantId, url) => http.post(`/variants/${variantId}/publish`, { published_url: url }),
  /** 待确认列表（AI 质检达标，等人工确认） */
  pending: () => http.get('/confirm/pending'),
  confirm: (variantId) => http.post(`/variants/${variantId}/confirm`),
  confirmReject: (variantId) => http.post(`/variants/${variantId}/confirm-reject`),
  /** 触发每日内容包生成（后台线程，2-4 分钟） */
  generateDaily: (scheduled) => http.post('/generate/daily', null, { query: { scheduled } }),
  generationStatus: () => http.get('/generate/status'),
  /** 今日待办 */
  todoToday: () => http.get('/todo/today'),
};
