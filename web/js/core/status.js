/**
 * 状态字典与平台元数据（唯一来源）。
 *
 * 规则：
 *  - 页面不得自行发明状态中文名；一律引用本文件的 *_STATUS / *_LABEL。
 *  - 平台默认四平台固定为 抖音 / 小红书 / 公众号 / 闲鱼；视频号/朋友圈只做迁移期兼容。
 *  - HTTP 错误统一走 httpErrorInfo()，页面只决定展示位置，不改文案口径。
 *
 * 对应文档：docs/phase2/M-P0-01-平台口径对齐表.md、M-P0-06-状态字典与错误码.md
 */

/* ---------------- 平台 ---------------- */

/**
 * 平台元数据。enabled=true 且 template=false 的为默认四平台。
 * code 是前后端兼容键；hasVariant 表示是否生成内容版本；composer 对应工作台通道。
 */
export const PLATFORM_META = [
  {
    code: 'douyin', name: '抖音', short: '抖音', icon: '🎬', category: 'video',
    enabled: true, template: false, hasVariant: true, composer: 'douyin',
    publishMode: 'copy', home: 'https://creator.douyin.com', sort: 10,
  },
  {
    code: 'xhs', name: '小红书', short: '小红书', icon: '📕', category: 'note',
    enabled: true, template: false, hasVariant: true, composer: 'xhs',
    publishMode: 'copy', home: 'https://creator.xiaohongshu.com', sort: 20,
  },
  {
    code: 'gzh', name: '公众号', short: '公众号', icon: '📰', category: 'article',
    enabled: true, template: false, hasVariant: true, composer: 'gzh',
    publishMode: 'copy', home: 'https://mp.weixin.qq.com', sort: 30,
  },
  {
    code: 'xianyu', name: '闲鱼', short: '闲鱼', icon: '🐟', category: 'marketplace',
    enabled: true, template: false, hasVariant: false, composer: 'xianyu',
    publishMode: 'copy', home: 'https://www.goofish.com', sort: 40,
  },
  // 迁移期兼容：历史内容可显示，但默认不新建、不进入默认筛选项。
  {
    code: 'shipinhao', name: '视频号', short: '视频号', icon: '📹', category: 'video',
    enabled: false, template: true, hasVariant: true, composer: '',
    publishMode: 'copy', home: 'https://channels.weixin.qq.com', sort: 90,
  },
  {
    code: 'moments', name: '朋友圈', short: '朋友圈', icon: '💬', category: 'other',
    enabled: false, template: true, hasVariant: true, composer: '',
    publishMode: 'manual', home: '', sort: 91,
  },
];

export const PLATFORM_BY_CODE = PLATFORM_META.reduce((m, p) => {
  m[p.code] = p;
  return m;
}, {});

/** 默认四平台 code（按 sort 排序） */
export const DEFAULT_PLATFORMS = PLATFORM_META
  .filter((p) => p.enabled && !p.template)
  .sort((a, b) => a.sort - b.sort)
  .map((p) => p.code);

/** 迁移期兼容 code（只读历史，不新建） */
export const LEGACY_PLATFORMS = PLATFORM_META
  .filter((p) => p.template)
  .map((p) => p.code);

export const PLATFORM_LABEL = PLATFORM_META.reduce((m, p) => {
  m[p.code] = p.name;
  return m;
}, {});

export const PLATFORM_HOME = PLATFORM_META.reduce((m, p) => {
  if (p.home) m[p.code] = p.home;
  return m;
}, {});

/** 平台下拉选项（默认四平台 + 可选启用的模板） */
export function platformOptions({ includeTemplates = false, includeLegacy = false } = {}) {
  return PLATFORM_META
    .filter((p) => (includeTemplates ? true : (p.enabled && !p.template)))
    .filter((p) => (includeLegacy ? true : !p.template))
    .sort((a, b) => a.sort - b.sort)
    .map((p) => ({ value: p.code, label: p.name, disabled: !p.enabled }));
}

export const PLATFORM_STATUS = {
  enabled: '已启用',
  disabled: '已停用',
};

/* ---------------- 账号 / 会话 ---------------- */

export const ACCOUNT_STATUS = {
  unbound: '未绑定',
  qr_pending: '等待扫码',
  logged_in: '已登录',
  expired: '登录已过期',
  disabled: '已停用',
};

export const ACCOUNT_STATUS_NEXT = {
  unbound: '绑定账号或扫码登录',
  qr_pending: '打开二维码或取消',
  logged_in: '可执行任务',
  expired: '重新扫码',
  disabled: '联系管理员启用',
};

export const SESSION_STATUS = {
  active: '有效',
  expired: '已过期',
  revoked: '已失效',
};

/* ---------------- 内容 / 审核 ---------------- */

export const CONTENT_STATUS = {
  draft: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  published: '已发布',
  archived: '已归档',
};

/** 内容版本状态（content_variants.status） */
export const VARIANT_STATUS = {
  draft: '草稿 / 待质检',
  blocked: '已拦截',
  pending: '待人工确认',
  published: '已发布',
};

export const CONFIRM_STATUS = {
  none: '未提交确认',
  pending: '待人工确认',
  confirmed: '已确认',
  rejected: '已驳回',
};

export const PUBLISH_STATUS = {
  none: '未发布',
  queued: '排队中',
  publishing: '发布中',
  filled: '已填充',
  submitted: '已提交',
  published: '已发布',
  failed: '发布失败',
};

/* ---------------- 沙盒 / 评论 / 私信 ---------------- */

export const SANDBOX_STATUS = {
  queued: '排队中',
  running: '执行中',
  waiting_confirm: '等待人工确认',
  paused: '已暂停',
  succeeded: '已完成',
  partial: '部分完成',
  failed: '失败',
  cancelled: '已取消',
};

export const SANDBOX_STEP_STATUS = {
  pending: '待执行',
  running: '执行中',
  waiting_confirm: '等待确认',
  succeeded: '已完成',
  failed: '失败',
  skipped: '已跳过',
};

export const SANDBOX_CONFIRM_POINTS = {
  open_platform: '打开平台 / 搜索词',
  first_comments: '首批评论',
  before_publish: '发布 / 发送前',
};

export const COMMENT_TASK_STATUS = {
  draft: '草稿',
  queued: '排队中',
  running: '采集中',
  waiting_confirm: '等待确认',
  succeeded: '已完成',
  partial: '部分完成',
  failed: '失败',
  cancelled: '已取消',
};

export const DM_TASK_STATUS = {
  draft: '草稿',
  queued: '排队中',
  sending: '发送中',
  waiting_confirm: '等待确认',
  sent: '已发送',
  failed: '发送失败',
  blocked: '已拦截',
  cancelled: '已取消',
};

/* ---------------- AI / 视频 ---------------- */

export const AI_JOB_STATUS = {
  queued: '排队中',
  running: '生成中',
  succeeded: '已生成',
  failed: '生成失败',
  timeout: '已超时',
  cancelled: '已取消',
};

export const VIDEO_JOB_STATUS = {
  queued: '排队中',
  submitting: '提交中',
  rendering: '渲染中',
  downloading: '下载中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

/* ---------------- 一期已有字典 ---------------- */

export const LEAD_STATUS = {
  new: '新线索',
  contacted: '已联系',
  wechat_added: '已加微',
  opportunity: '商机',
  won: '已成交',
  lost: '已流失',
  invalid: '无效',
};

export const INTENT = {
  high: '高意向',
  mid: '中意向',
  low: '低意向',
  junk: '垃圾 / 广告',
};

export const IDENTITY = {
  contractor: '工程商',
  owner: '甲方',
  unknown: '未知',
};

export const PUBLICITY = {
  public: '可公开',
  masked: '需脱敏',
  internal: '仅内部',
};

export const TOPIC_STATUS = {
  active: '可用',
  used: '已使用',
  archived: '已归档',
};

export const ROLE = {
  admin: '管理员',
  operator: '运营',
  sales: '销售',
};

export const TASK_STATUS = {
  queued: '排队中',
  running: '执行中',
  succeeded: '已完成',
  failed: '失败',
};

/* ---------------- 通用取值 ---------------- */

export function label(map, key, fallback = '-') {
  if (key === undefined || key === null || key === '') return fallback;
  return map && map[key] !== undefined ? map[key] : `${key}（未知状态）`;
}

export const platformName = (code) => label(PLATFORM_LABEL, code);
export const accountStatusName = (s) => label(ACCOUNT_STATUS, s);
export const sessionStatusName = (s) => label(SESSION_STATUS, s);
export const contentStatusName = (s) => label(CONTENT_STATUS, s);
export const variantStatusName = (s) => label(VARIANT_STATUS, s);
export const confirmStatusName = (s) => label(CONFIRM_STATUS, s);
export const publishStatusName = (s) => label(PUBLISH_STATUS, s);
export const sandboxStatusName = (s) => label(SANDBOX_STATUS, s);
export const sandboxStepStatusName = (s) => label(SANDBOX_STEP_STATUS, s);
export const commentTaskStatusName = (s) => label(COMMENT_TASK_STATUS, s);
export const dmTaskStatusName = (s) => label(DM_TASK_STATUS, s);
export const aiJobStatusName = (s) => label(AI_JOB_STATUS, s);
export const videoJobStatusName = (s) => label(VIDEO_JOB_STATUS, s);
export const leadStatusName = (s) => label(LEAD_STATUS, s);
export const intentName = (i) => label(INTENT, i);
export const identityName = (i) => label(IDENTITY, i);
export const publicityName = (p) => label(PUBLICITY, p);
export const topicStatusName = (s) => label(TOPIC_STATUS, s);
export const roleName = (r) => label(ROLE, r);
export const taskStatusName = (s) => label(TASK_STATUS, s);

/* ---------------- HTTP 错误 ---------------- */

/**
 * HTTP 状态码 → 前端文案与下一步。
 * 页面不得直接写「请求失败」；至少给用户一个可执行下一步。
 */
export const HTTP_ERRORS = {
  0: { code: 'network_error', title: '网络异常', text: '连不上后端服务，请确认服务已启动后重试', next: '检查服务或网络后重试' },
  400: { code: 'bad_request', title: '请求有误', text: '提交的请求参数有误', next: '检查填写内容后重试' },
  401: { code: 'unauthorized', title: '登录已失效', text: '登录已失效，请重新登录', next: '回到登录页' },
  403: { code: 'forbidden', title: '无权限', text: '当前角色没有该操作的权限', next: '联系管理员或切换账号' },
  404: { code: 'not_found', title: '数据不存在', text: '数据不存在或已被删除', next: '刷新列表后重试' },
  409: { code: 'conflict', title: '状态冲突', text: '数据已被他人更新或当前状态不允许此操作', next: '刷新后重试，不要覆盖他人修改' },
  422: { code: 'validation_error', title: '提交内容有误', text: '提交内容有误，请按提示修改', next: '修正字段后重试' },
  429: { code: 'rate_limited', title: '操作过于频繁', text: '操作过于频繁，请稍后重试', next: '按倒计时等待，或完成安全验证' },
  500: { code: 'server_error', title: '服务异常', text: '服务内部错误', next: '稍后重试；持续失败请联系管理员' },
  503: { code: 'service_unavailable', title: '服务暂不可用', text: '依赖服务暂不可用', next: '稍后重试；保留已填内容' },
};

/** 业务 code → 更精确的文案（优先于 HTTP 状态）。 */
export const ERROR_CODE_OVERRIDES = {
  batch_precheck_failed: { title: '批量预检未通过', text: '存在未通过预检的版本，整批未写入', next: '查看逐项原因后单条处理' },
  version_conflict: { title: '数据已更新', text: '数据已被他人更新，请刷新后重试', next: '刷新后重试' },
  account_not_ready: { title: '平台账号未就绪', text: '平台账号未登录或已过期', next: '重新扫码登录' },
  platform_mismatch: { title: '平台不匹配', text: '账号所属平台与任务平台不一致', next: '选择正确账号' },
  invalid_reason: { title: '驳回理由缺失', text: '驳回必须填写理由', next: '填写理由后重试' },
  bitable_duplicate: { title: '数据重复', text: '该记录已存在', next: '刷新列表查看' },
};

/**
 * 取错误展示信息。
 * @param {number} status HTTP 状态；0 表示网络异常
 * @param {string} code 业务错误码，可选
 * @param {string} detail 后端 detail，优先展示
 */
export function httpErrorInfo(status, code, detail) {
  const base = HTTP_ERRORS[status] || {
    code: 'unknown_error',
    title: '请求失败',
    text: `请求失败（${status}）`,
    next: '稍后重试',
  };
  const override = code ? ERROR_CODE_OVERRIDES[code] : null;
  const info = override ? { ...base, ...override, code } : { ...base, code: code || base.code };
  if (detail) info.text = detail;
  return info;
}
