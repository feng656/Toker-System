/**
 * 内容生产闭环（后端 /contents、/variants、/confirm/*、/generate/*、/todo/*）
 *
 * 约定：
 *  - 新交互使用变体级 approve/reject/regenerate/history；
 *  - 内容级 review 仅作为整包快捷操作兼容，不再作为主流程；
 *  - 修改/发布带 expected_version，409 时由页面提示刷新；
 *  - 批量接口见 docs/phase2/M-P0-05；后端未上线时页面走逐条兼容模式。
 */
import { http } from '../core/http.js';

export const contentApi = {
  list: (query) => http.get('/contents', query),

  /* -------- 变体级审核 -------- */
  approveVariant: (id, expectedVersion) =>
    http.post(`/variants/${id}/approve`, expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
  rejectVariant: (id, reason, expectedVersion) =>
    http.post(`/variants/${id}/reject`, {
      reason,
      ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
    }),
  regenerate: (id) => http.post(`/variants/${id}/regenerate`),
  history: (id) => http.get(`/variants/${id}/history`),

  /** 批量通过：{variant_ids, expected_versions, note, dry_run} */
  batchApprove: (body) => http.post('/variants/batch-approve', body),
  /** 批量驳回：{variant_ids, reason, expected_versions, dry_run} */
  batchReject: (body) => http.post('/variants/batch-reject', body),

  /* -------- 内容级兼容入口 -------- */
  /** 内容级审核：approve / reject（驳回必须带理由）；新交互请用变体级接口 */
  review: (id, action, note) => http.post(`/contents/${id}/review`, { action, note: note || '' }),

  /** 修改变体文案（保存后后端会重跑一次合规硬检） */
  updateVariant: (id, body, expectedVersion) => http.put(`/variants/${id}`, {
    ...body,
    ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
  }),
  /** 人工回填发布链接 */
  publish: (variantId, url, expectedVersion) => http.post(`/variants/${variantId}/publish`, {
    published_url: url,
    ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
  }),

  /* -------- 待确认 / 生成 / 待办 -------- */
  pending: () => http.get('/confirm/pending'),
  /** 兼容别名：后端新接口是 approve/reject；confirm 仅保留给旧调用 */
  confirm: (variantId) => http.post(`/variants/${variantId}/confirm`),
  confirmReject: (variantId) => http.post(`/variants/${variantId}/confirm-reject`),
  generateDaily: (scheduled) => http.post('/generate/daily', null, { query: { scheduled } }),
  generationStatus: () => http.get('/generate/status'),
  /** 今日待办；传日期可查指定日（后端 /todo/today?scheduled=YYYY-MM-DD） */
  todoToday: (date) => http.get('/todo/today', date ? { scheduled: date } : undefined),

  /* -------- 草稿箱（后端接口未上线时返回 404，页面按未就绪处理） -------- */
  createDraft: (body) => http.post('/contents', body),
  updateDraft: (id, body, expectedVersion) => http.put(`/contents/${id}`, {
    ...body,
    ...(expectedVersion === undefined ? {} : { expected_version: expectedVersion }),
  }),
  submitDraft: (id) => http.post(`/contents/${id}/submit`),
};
