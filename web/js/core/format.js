/**
 * 业务口径与格式化工具。
 * 这里的枚举值必须与《奇迹于你和浆果的分工》第 8.1 节状态定义、以及后端
 * app/models.py 的字段取值保持一致；前端不自行推断后端状态。
 */

export const PLATFORMS = ['douyin', 'shipinhao', 'gzh', 'xhs', 'moments'];

export const PLATFORM_LABEL = {
  douyin: '抖音', shipinhao: '视频号', gzh: '公众号', xhs: '小红书', moments: '朋友圈',
};

export const PLATFORM_HOME = {
  douyin: 'https://creator.douyin.com',
  shipinhao: 'https://channels.weixin.qq.com',
  gzh: 'https://mp.weixin.qq.com',
  xhs: 'https://creator.xiaohongshu.com',
  moments: '',
};

export const BIZ_LINES = [
  { value: 'project', label: '甲方线' },
  { value: 'channel', label: '渠道线' },
  { value: 'both', label: '通用' },
];

/** 内容状态（contents.status） */
export const CONTENT_STATUS = {
  draft: '待审核', approved: '已通过', rejected: '已驳回', published: '已发布', archived: '已归档',
};

/** 变体人工确认状态（content_variants.confirm_status） */
export const CONFIRM_STATUS = {
  none: '未提交确认', pending: '待人工确认', confirmed: '已确认', rejected: '已驳回',
};

/** 变体发布状态（content_variants.publish_status） */
export const PUBLISH_STATUS = {
  none: '未发布', queued: '排队中', publishing: '发布中', published: '已发布', failed: '发布失败',
};

/** 线索状态（leads.status） */
export const LEAD_STATUS = {
  new: '新线索', contacted: '已联系', wechat_added: '已加微',
  opportunity: '商机', won: '已成交', lost: '已流失',
};

/** 线索意向（leads.intent） */
export const INTENT = {
  high: '高意向', mid: '中意向', low: '低意向', junk: '垃圾/广告',
};

/** 线索身份（leads.identity） */
export const IDENTITY = {
  contractor: '工程商', owner: '甲方', unknown: '未知',
};

/** 素材公开级别（materials.publicity） */
export const PUBLICITY = {
  public: '可公开', masked: '需脱敏', internal: '仅内部',
};

/** 选题状态（topics.status） */
export const TOPIC_STATUS = {
  active: '可用', used: '已使用', archived: '已归档',
};

/** 角色（users.role） */
export const ROLE = {
  admin: '管理员', operator: '运营', sales: '销售',
};

/** 素材分类（materials.category） */
export const MATERIAL_CATEGORIES = [
  '公司简介', '品牌代理', '产品明细', '案例', '工地实拍',
  '资质荣誉', '服务能力', '企业文化', 'FAQ', '其他',
];

/** 选题主题（topics.theme） */
export const TOPIC_THEMES = [
  '方案科普', '案例复盘', '工程商痛点', '新品到货', '招投标知识', '公司动态', '行业观点',
];

export const label = (map, key) => (map && map[key] !== undefined ? map[key] : key || '-');
export const platformName = (p) => label(PLATFORM_LABEL, p);
export const contentStatusName = (s) => label(CONTENT_STATUS, s);
export const confirmStatusName = (s) => label(CONFIRM_STATUS, s);
export const publishStatusName = (s) => label(PUBLISH_STATUS, s);
export const leadStatusName = (s) => label(LEAD_STATUS, s);
export const intentName = (i) => label(INTENT, i);
export const identityName = (i) => label(IDENTITY, i);
export const publicityName = (p) => label(PUBLICITY, p);
export const topicStatusName = (s) => label(TOPIC_STATUS, s);
export const roleName = (r) => label(ROLE, r);
export const bizLineName = (b) => label({ project: '甲方线', channel: '渠道线', both: '通用' }, b);

export function bizLineClass(b) {
  return b === 'project' ? 'line-project' : b === 'channel' ? 'line-channel' : 'line-both';
}

/* ---------------- 日期 ---------------- */

export function todayStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function fmtDate(v) {
  if (!v) return '-';
  return String(v).slice(0, 10);
}

export function fmtDateTime(v) {
  if (!v) return '-';
  const s = String(v);
  if (s.length <= 10) return s;
  return s.slice(0, 16).replace('T', ' ');
}

/* ---------------- 校验 ---------------- */

/**
 * 发布链接校验（对应验收硬门槛「空发布链接不能计入发布量」）。
 * @returns {{ok:boolean, message:string}}
 */
export function validatePublishUrl(url) {
  const v = (url || '').trim();
  if (!v) return { ok: false, message: '发布链接不能为空，未回填链接不会计入发布量' };
  if (/\s/.test(v)) return { ok: false, message: '发布链接不能包含空格' };
  if (!/^https?:\/\//i.test(v)) return { ok: false, message: '发布链接需以 http:// 或 https:// 开头' };
  let host = '';
  try { host = new URL(v).hostname; } catch (e) { return { ok: false, message: '发布链接格式无效' }; }
  if (!host || host.indexOf('.') < 0) return { ok: false, message: '发布链接主机名无效' };
  return { ok: true, message: '' };
}

/* ---------------- 复制 ---------------- */

export async function copyText(text) {
  const value = text || '';
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (e) { /* 退回到 execCommand */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (e) {
    return false;
  }
}

/** 组装可发布的完整文案（正文 + 话题标签） */
export function composeCopyText(variant) {
  const body = variant.body || '';
  const tags = variant.hashtags || '';
  const cover = variant.cover_text ? `【${variant.cover_text}】\n` : '';
  return `${cover}${body}${tags ? '\n' + tags : ''}`;
}
