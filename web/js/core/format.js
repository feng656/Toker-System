/**
 * 业务口径与格式化工具。
 *
 * 状态与平台字典的唯一来源是 core/status.js；本文件只做兼容再导出与格式化，
 * 页面应从 status.js 或本文件引用，不得另写一份中文映射。
 */
import {
  PLATFORM_META, DEFAULT_PLATFORMS, LEGACY_PLATFORMS, PLATFORM_LABEL, PLATFORM_HOME,
  CONTENT_STATUS, VARIANT_STATUS, CONFIRM_STATUS, PUBLISH_STATUS,
  LEAD_STATUS, INTENT, IDENTITY, PUBLICITY, TOPIC_STATUS, ROLE,
  label, platformName, contentStatusName, variantStatusName, confirmStatusName,
  publishStatusName, leadStatusName, intentName, identityName, publicityName,
  topicStatusName, roleName,
} from './status.js';

export {
  PLATFORM_META, PLATFORM_LABEL, PLATFORM_HOME,
  CONTENT_STATUS, VARIANT_STATUS, CONFIRM_STATUS, PUBLISH_STATUS,
  LEAD_STATUS, INTENT, IDENTITY, PUBLICITY, TOPIC_STATUS, ROLE, LEGACY_PLATFORMS,
  platformName, contentStatusName, variantStatusName, confirmStatusName,
  publishStatusName, leadStatusName, intentName, identityName, publicityName,
  topicStatusName, roleName,
};

/** 默认四平台（抖音 / 小红书 / 公众号 / 闲鱼） */
export const PLATFORMS = DEFAULT_PLATFORMS;

export const BIZ_LINES = [
  { value: 'project', label: '甲方线' },
  { value: 'channel', label: '渠道线' },
  { value: 'both', label: '通用' },
];

/** 素材分类（materials.category） */
export const MATERIAL_CATEGORIES = [
  '公司简介', '品牌代理', '产品明细', '案例', '工地实拍',
  '资质荣誉', '服务能力', '企业文化', 'FAQ', '其他',
];

/** 选题主题（topics.theme） */
export const TOPIC_THEMES = [
  '方案科普', '案例复盘', '工程商痛点', '新品到货', '招投标知识', '公司动态', '行业观点',
];

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
