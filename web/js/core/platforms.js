/**
 * P0 平台通道规格：四个平台 tab 的字段、复制文案格式、行动引导与免责声明。
 *
 * 依据（均为已确认稿，不在本阶段自行改口径）：
 *  - 《06-系统框架V0.1》2.4「平台 composer（右侧）」字段表
 *  - 《06-系统框架V0.1》0 节「价格口径」：文案不出现价格数字；闲鱼价格走单独字段、不进文案
 *  - 《01-业务口径确认表》三-4「行动引导分平台」
 *  - 《03-合规词-资质-免责声明确认表》4.1 免责声明，人工确认「4.1，统一附」（五-3）
 *
 * 说明：变体接口（app/api.py `_variant_dict`）**不返回** assets_url，
 *      所以媒体字段只能展示「配图建议 + 素材状态」，不伪造图片/视频链接。
 */

/** 4.1 公众号/长图文版免责声明（人工确认：四平台统一附此版） */
export const DISCLAIMER = '本内容用于行业信息分享，不构成任何采购承诺或要约。'
  + '产品参数、价格、交期以正式报价单和合同为准。'
  + '案例信息已做脱敏处理，未经客户授权不披露客户名称、项目金额及现场影像。'
  + '文中涉及的品牌、商标归各自权利人所有，我方仅作代理/服务说明。'
  + '内容如与平台规则冲突，以平台规则为准。';

/** 闲鱼成色选项（平台常见成色档位） */
export const XIANYU_CONDITIONS = ['全新', '几乎全新', '轻微使用痕迹', '明显使用痕迹', '有磨损'];

/** 分平台行动引导（来源：《01-业务口径确认表》三-4「分平台」） */
const CTA = {
  douyin: '抖音私信「LED」获取选型清单与报价',
  xhs: '小红书评论区或私信「LED」领取选型清单',
  gzh: '公众号后台留言或加微信获取方案与报价',
  xianyu: '闲鱼站内信咨询现货与配送',
};

function lines(...parts) {
  return parts
    .map((s) => (s === undefined || s === null ? '' : String(s)).trim())
    .filter((s) => s !== '')
    .join('\n\n');
}

/**
 * 四个平台通道。字段 key 与 composer 草稿对象一一对应。
 * type: text | textarea | select | media（media 为只读状态块，不接受输入）
 */
export const CHANNELS = [
  {
    key: 'douyin',
    name: '抖音',
    home: 'https://creator.douyin.com',
    short: '抖音',
    fields: [
      { key: 'title', label: '标题', type: 'text', placeholder: '一句话钩子（≤ 30 字）' },
      { key: 'script', label: '口播文案', type: 'textarea', rows: 9, placeholder: '开头 3 秒抛痛点，60 秒讲完' },
      { key: 'hashtags', label: '话题', type: 'text', placeholder: '#LED大屏 #报告厅改造' },
      { key: 'cover', label: '封面', type: 'media', hint: '封面图 / 视频首帧（需在素材库补）' },
      { key: 'media', label: '视频或图文', type: 'media', hint: '竖屏视频或图文九宫格（需在素材库补）' },
    ],
  },
  {
    key: 'xhs',
    name: '小红书',
    home: 'https://creator.xiaohongshu.com',
    short: '小红书',
    fields: [
      { key: 'title', label: '标题', type: 'text', placeholder: '≤ 20 字，带一点场景感' },
      { key: 'body', label: '正文', type: 'textarea', rows: 9, placeholder: '分点写，结尾给行动引导' },
      { key: 'hashtags', label: '话题', type: 'text', placeholder: '#弱电智能化 #LED选型' },
      { key: 'images', label: '图片', type: 'media', hint: '至少 1 张（需在素材库补）' },
    ],
  },
  {
    key: 'gzh',
    name: '公众号',
    home: 'https://mp.weixin.qq.com',
    short: '公众号',
    fields: [
      { key: 'title', label: '标题', type: 'text', placeholder: '≤ 30 字' },
      { key: 'body', label: '正文', type: 'textarea', rows: 10, placeholder: '800–1500 字长图文' },
      { key: 'cover', label: '封面', type: 'media', hint: '封面图（需在素材库补）' },
      { key: 'summary', label: '摘要', type: 'textarea', rows: 3, placeholder: '公众号列表页摘要（≤ 120 字）' },
    ],
  },
  {
    key: 'xianyu',
    name: '闲鱼',
    home: 'https://www.goofish.com',
    short: '闲鱼',
    fields: [
      { key: 'title', label: '标题', type: 'text', placeholder: '≤ 30 字，带规格关键词' },
      { key: 'description', label: '描述', type: 'textarea', rows: 9, placeholder: '现货情况、交付范围、服务说明' },
      { key: 'price', label: '价格', type: 'text', placeholder: '只填在闲鱼后台，不进文案', note: '价格口径：文案与标题不出现价格数字，此处只用于后台填价' },
      { key: 'condition', label: '成色', type: 'select', options: XIANYU_CONDITIONS },
      { key: 'images', label: '图片', type: 'media', hint: '实物图（需在素材库补）' },
    ],
  },
];

/** 通道 key → 通道对象 */
export const CHANNEL_MAP = CHANNELS.reduce((m, c) => {
  m[c.key] = c;
  return m;
}, {});

/** 通道 key → 中文名（内容版本平台名与通道名一致，闲鱼无内容版本） */
export const channelName = (key) => (CHANNEL_MAP[key] ? CHANNEL_MAP[key].name : key || '-');

/** 空草稿（composer 初值） */
export function emptyDraft(channel) {
  const d = { sourceId: null, sourcePlatform: '', textOnly: false };
  channel.fields.forEach((f) => {
    d[f.key] = f.type === 'select' ? (f.options && f.options[0]) || '' : '';
  });
  return d;
}

/** 初始四通道草稿 */
export function emptyDrafts() {
  const out = {};
  CHANNELS.forEach((c) => { out[c.key] = emptyDraft(c); });
  return out;
}

/** 从内容版本填充草稿（按平台差异重排字段） */
export function fillDraft(channel, variant) {
  const d = emptyDraft(channel);
  const body = variant.body || '';
  const title = variant.content_title || variant.cover_text || '';
  const tags = variant.hashtags || '';
  const shot = variant.image_prompt || '';
  d.sourceId = variant.id;
  d.sourcePlatform = variant.platform || '';
  switch (channel.key) {
    case 'douyin':
      d.title = title;
      d.script = body;
      d.hashtags = tags;
      d.cover = shot || '';
      d.media = shot || '';
      break;
    case 'xhs':
      d.title = title;
      d.body = body;
      d.hashtags = tags;
      d.images = shot || '';
      break;
    case 'gzh':
      d.title = title;
      d.body = body;
      d.cover = shot || '';
      d.summary = body.slice(0, 120);
      break;
    case 'xianyu':
      d.title = title;
      d.description = body;
      d.price = '';
      d.condition = XIANYU_CONDITIONS[0];
      d.images = shot || '';
      break;
    default:
      break;
  }
  return d;
}

/**
 * 组装「该平台格式」的完整文案（复制到剪贴板的内容）。
 * 口径：免责声明统一附 4.1；闲鱼价格不进文案；封面/图片不进文案（后台单独上传）。
 */
export function buildCopy(channel, draft) {
  const d = draft || {};
  const cta = CTA[channel.key] || '';
  switch (channel.key) {
    case 'douyin':
      return lines(d.title, d.script, d.hashtags, cta, DISCLAIMER);
    case 'xhs':
      return lines(d.title, d.body, d.hashtags, cta, DISCLAIMER);
    case 'gzh':
      return lines(d.title, d.body, cta, DISCLAIMER);
    case 'xianyu':
      return lines(d.title, d.description, d.condition ? `成色：${d.condition}` : '', cta, DISCLAIMER);
    default:
      return lines(d.title, d.body, DISCLAIMER);
  }
}

/** 平台标签对应的内容版本平台名（闲鱼无 AI 内容版本，返回 null） */
export function contentPlatformOf(channelKey) {
  return channelKey === 'xianyu' ? null : channelKey;
}
