/**
 * 二期后端接口（/platforms、/variants 筛选批量、/assets、/workspace/*、/comment-tasks、/dm/*、/ai/providers、/video-jobs）
 * 对应《二次分工方案》R1/R2/R3/R4/R6/R7/R9/R11 的后端契约。
 */
import { http } from '../core/http.js';

export const phase2Api = {
  /* ---- R1 动态平台 ---- */
  platforms: () => http.get('/platforms'),
  platformTemplates: () => http.get('/platforms/templates'),
  addPlatform: (body) => http.post('/platforms', body),
  editPlatform: (pid, body) => http.put(`/platforms/${pid}`, body),

  /* ---- R4 版本筛选 / 批量审核 / 草稿 ---- */
  variants: (query) => http.get('/variants', query),
  bulkReview: (body) => http.post('/variants/bulk-review', body),
  createDraft: (body) => http.post('/contents/drafts', body),

  /* ---- R9 AI 供应商 ---- */
  providers: () => http.get('/ai/providers'),
  addProvider: (body) => http.post('/ai/providers', body),
  editProvider: (pid, body) => http.put(`/ai/providers/${pid}`, body),
  testProvider: (pid) => http.post(`/ai/providers/${pid}/test`),

  /* ---- R3 素材（图片媒体，MinIO） ---- */
  assets: (query) => http.get('/assets', query),
  uploadAssets: (fd) => http.upload('/assets/upload', fd),
  editAsset: (aid, body) => http.put(`/assets/${aid}`, body),
  assetUrl: (aid) => http.get(`/assets/${aid}/url`),
  generateContent: (body) => http.post('/assets/generate-content', body),

  /* ---- R2/R6 工作空间与扫码登录 ---- */
  wsAccounts: () => http.get('/workspace/accounts'),
  addWsAccount: (body) => http.post('/workspace/accounts', body),
  wsLogin: (aid, body) => http.post(`/workspace/accounts/${aid}/login`, body),
  wsSession: (aid) => http.get(`/workspace/accounts/${aid}/session`),
  wsRefresh: (aid) => http.post(`/workspace/accounts/${aid}/refresh`),
  wsLogout: (aid) => http.post(`/workspace/accounts/${aid}/logout`),
  wsOverview: () => http.get('/workspace/overview'),
  publishJob: (body) => http.post('/workspace/publish-jobs', body),
  publishJobGet: (jid) => http.get(`/workspace/publish-jobs/${jid}`),
  publishJobRun: (jid) => http.post(`/workspace/publish-jobs/${jid}/run`),
  publishJobConfirm: (jid) => http.post(`/workspace/publish-jobs/${jid}/confirm`),
  publishJobCancel: (jid) => http.post(`/workspace/publish-jobs/${jid}/cancel`),

  /* ---- R7 授权评论任务 ---- */
  commentTasks: () => http.get('/comment-tasks'),
  commentTaskDetail: (tid) => http.get(`/comment-tasks/${tid}`),
  createCommentTask: (body) => http.post('/comment-tasks', body),
  commentTaskDiscover: (tid) => http.post(`/comment-tasks/${tid}/discover`, { search_confirmed: true }),
  commentTaskPrepare: (tid) => http.post(`/comment-tasks/${tid}/prepare`),
  commentTaskApprove: (tid) => http.post(`/comment-tasks/${tid}/approve`),
  commentTaskRun: (tid) => http.post(`/comment-tasks/${tid}/run`),
  commentTaskStop: (tid) => http.post(`/comment-tasks/${tid}/stop`),
  commentTaskCollect: (tid) => http.post(`/comment-tasks/${tid}/collect`),

  /* ---- R11 私信接管 ---- */
  replyTemplates: () => http.get('/reply-templates'),
  addReplyTemplate: (body) => http.post('/reply-templates', body),
  editReplyTemplate: (tid, body) => http.put(`/reply-templates/${tid}`, body),
  dmPolicies: () => http.get('/dm-policies'),
  saveDmPolicy: (body) => http.post('/dm-policies', body),
  dmMessages: () => http.get('/dm/messages'),
  dmPrepare: (mid) => http.post(`/dm/messages/${mid}/prepare`),
  dmApprove: (mid) => http.post(`/dm/messages/${mid}/approve`),
  dmSend: (mid) => http.post(`/dm/messages/${mid}/send`),

  /* ---- R9 视频生成 ---- */
  videoJobs: () => http.get('/video-jobs'),
  createVideo: (body) => http.post('/video-jobs', body),
  runVideo: (jid) => http.post(`/video-jobs/${jid}/run`),

  /* ---- R10 登录策略 ---- */
  authPolicy: () => http.get('/auth/policy'),
  authChallenge: () => http.post('/auth/challenge'),

  /* ---- 需求反哺 ---- */
  suggestions: () => http.get('/topic-suggestions'),
  convertSuggestion: (sid) => http.post(`/topic-suggestions/${sid}/convert`),
};
