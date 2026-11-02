/**
 * 帮助：一期范围边界、每日操作 SOP、常见异常与处理、状态口径速查表、找谁处理。
 * 完成标志（《分工》4.2）：不会把实验能力误认为一期必需能力。
 */
import { CONTENT_STATUS, CONFIRM_STATUS, PUBLISH_STATUS, LEAD_STATUS, INTENT, IDENTITY, PUBLICITY } from '../core/format.js';

export default {
  name: 'PageHelp',
  setup() {
    const faq = [
      {
        q: '今天的内容从哪里来？',
        a: '系统每天 08:00 自动生成次日内容包（1 个甲方线选题 + 1 个渠道线选题，各 4 个平台版本，共 8 条）；也可以在「今日待办」手动点「生成明日内容包」。生成依赖大模型 API，未配置 Key 时会失败。',
      },
      {
        q: '为什么待办里看不到某些版本？',
        a: '① 被驳回或非草稿/已通过状态的内容不进待办；② 已回填链接的版本不再出现在待办；③ 人工确认被拦截（confirm_status=rejected）的版本需要人工修订后再提交。',
      },
      {
        q: '点「确认发布」后为什么还是失败？',
        a: '两种情况：① 平台未配置官方凭据或未登录（此时系统会复制文案并打开后台，请人工粘贴发布）；② 公众号未完成企业认证 / 未把服务器 IP 加入白名单。前端会显示具体失败原因，可重试。',
      },
      {
        q: '发布后忘记回填链接会怎样？',
        a: '该版本仍算「未发布」，不会计入看板的已发布数量，也不会出现在「今日待办」的完成判定里。这是硬门槛：空链接不能计入发布量。',
      },
      {
        q: '截图上传后为什么没有自动识别数据？',
        a: '截图 OCR 尚未接入（一期不含），截图只做留档，数据需要在「数据看板」手工录入；低置信度不入库的规则在 OCR 接入后才会生效。',
      },
      {
        q: '线索重复了怎么办？',
        a: '系统目前没有自动去重能力。发现重复联系方式时请人工合并（保留最早一条，跟进记录写在同一条上），不要新建重复线索。',
      },
    ];

    const exceptions = [
      { scene: '生成任务无响应', cause: '大模型限流 / Key 未配置 / 定时任务未跑', action: '先看「今日待办 → 生成内容包」的返回提示；等待 5 分钟后刷新「内容管理」；仍失败找后端同学查 AI 调用日志。' },
      { scene: '待确认里为空', cause: '本批内容质检分 < 70 或命中红线', action: '到「内容管理」展开版本看质检评语，改写后再保存（保存会重新跑合规检查）。' },
      { scene: '发布失败', cause: '平台凭据缺失 / 未登录 / 公众号未认证', action: '按提示改用人工发布；需自动发布时在「设置」补齐凭据并完成平台侧认证。' },
      { scene: '回填链接报错', cause: '链接为空或格式非 http(s)', action: '必须粘贴以 http:// 或 https:// 开头的完整链接，系统会校验后才写入。' },
      { scene: '企微收不到高意向提醒', cause: '未配置 WECOM_WEBHOOK 或推送失败', action: '在「线索看板」对该线索手动点「推送企微」重试；同时通知后端同学检查企微配置。' },
      { scene: '工作台拖不动 / 拖过去没反应', cause: '窄屏或手机没有拖拽能力；或拖的不是内容卡本身', action: '用卡片上的「复制到…」下拉选平台（与拖动等价）；桌面端请拖内容卡主体。' },
      { scene: '拖到别的平台弹出确认', cause: '内容版本平台与目标通道不一致，防错投提示', action: '确认后按目标平台重排字段；不想投就点「取消」。' },
      { scene: '素材不足 / 文案里没有图', cause: '素材库还没补图（或当前是「先用文字版」状态）', action: '图片在平台后台上传；工作台的媒体字段只提示素材状态，不阻塞投放。' },
      { scene: '「发布（API）」按钮点不动', cause: '真实平台发布 API 属 P1 阶段', action: '一期用「复制文案 + 打开后台」人工发布；标记已发需粘贴发布链接。' },
      { scene: '页面空白 / 一直加载', cause: '后端服务未启动或网络不通', action: '页面会给出错误提示并提供「重试」按钮；确认服务已启动后重试。' },
    ];

    const sop = [
      { role: '运营', items: ['① 打开「工作台」，左侧看今天的内容卡（右侧有抖音/小红书/公众号/闲鱼四个平台通道）', '② 把内容卡拖到目标平台 tab 松手：自动复制该平台格式文案并填好 composer（手机用卡片上的「复制到…」下拉）', '③ 在 composer 里微调 → 「复制文案」/「打开 XX 后台」→ 人工发布', '④ 回到「标记已发」粘贴发布链接，或在「今日待办」里「确认回填」', '⑤ 发布 24 小时后上传数据截图，并在「数据看板」录入曝光/点赞等指标'] },
      { role: '销售', items: ['① 打开「线索看板」，筛选「高意向」', '② 指派负责人并把状态改为「已联系」', '③ 每次沟通在「联系记录」里写一条', '④ 推进到「商机」，成交标「已成交」，无效标「已流失」'] },
      { role: '负责人 / 产品', items: ['① 打开「数据看板」核对漏斗与明细', '② 看异常状态（红线 / 发布失败 / 未回填 / 高意向未指派）', '③ 对照《九步验收脚本与结果》核对当次演示', '④ 把业务判定写进问题清单，交后端同学排期'] },
    ];

    return {
      faq, exceptions, sop,
      CONTENT_STATUS, CONFIRM_STATUS, PUBLISH_STATUS, LEAD_STATUS, INTENT, IDENTITY, PUBLICITY,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">帮助</div>
    <div class="page-sub">一页说清：一期做什么、不做什么、每天怎么干、遇到异常找谁。</div>
  </div>
</div>

<div class="card">
  <h4 class="card-title">一期范围</h4>
  <div class="grid3">
    <div>
      <b class="ok">✅ 一期包含</b>
      <div class="muted tiny mt6" style="line-height:1.9">
        · 内容包生成（AI 写稿 + 合规硬检 + 质量打分）<br/>
        · 人工审核 / 驳回（含理由）<br/>
        · 工作台拖动投放：四平台（抖音/小红书/公众号/闲鱼）通道 + 平台 composer<br/>
        · 人工发布 + 发布链接回填<br/>
        · 素材库 / 选题池维护<br/>
        · 评论私信 AI 打标 → 线索看板<br/>
        · 数据看板与周复盘<br/>
        · 企微高意向提醒（可重试）
      </div>
    </div>
    <div>
      <b class="err">❌ 一期不包含</b>
      <div class="muted tiny mt6" style="line-height:1.9">
        · 平台全自动发布（凭据到位时可试，但不作为验收前提）<br/>
        · 竞品账号爬取 / 达人管理<br/>
        · 多组织、多品牌、多租户<br/>
        · 截图 OCR 自动识别（截图仅留档）<br/>
        · 线索自动去重（需人工合并）<br/>
        · 素材批量导入接口（现为脚本）
      </div>
    </div>
    <div>
      <b>🧭 硬门槛（不可绕过）</b>
      <div class="muted tiny mt6" style="line-height:1.9">
        · 空发布链接不能计入发布量<br/>
        · 命中红线的版本不能直接放行<br/>
        · OCR 低置信度数据不能直接入库<br/>
        · 同一联系方式 30 天内不得重复建线索
      </div>
    </div>
  </div>
</div>

<div class="card">
  <h4 class="card-title">每天怎么做</h4>
  <div class="grid3">
    <div v-for="s in sop" :key="s.role" class="stat" style="text-align:left">
      <b>{{ s.role }}</b>
      <div class="muted tiny mt6" style="line-height:1.9">
        <div v-for="(it, i) in s.items" :key="i">{{ it }}</div>
      </div>
    </div>
  </div>
</div>

<div class="card">
  <h4 class="card-title">常见问题</h4>
  <el-collapse>
    <el-collapse-item v-for="(f, i) in faq" :key="i" :title="f.q" :name="i">
      <div class="tiny" style="line-height:1.9;color:#606266">{{ f.a }}</div>
    </el-collapse-item>
  </el-collapse>
</div>

<div class="card">
  <h4 class="card-title">异常与处理（找谁）</h4>
  <el-table :data="exceptions" size="small">
    <el-table-column prop="scene" label="场景" width="140"></el-table-column>
    <el-table-column prop="cause" label="常见原因" width="220"></el-table-column>
    <el-table-column prop="action" label="处理动作"></el-table-column>
  </el-table>
  <div class="gap-note">
    页面 / 交互 / 业务口径问题 → 找产品与前端负责人（本文档与《业务规则与状态口径说明》同步维护）；
    接口 / 数据 / AI / OCR / 企微 / 部署问题 → 找后端负责人，问题需附：复现步骤、预期、实际、截图。
  </div>
</div>

<div class="card">
  <h4 class="card-title">状态口径速查（与《业务规则与状态口径说明》一致）</h4>
  <div class="grid3">
    <div>
      <b class="tiny">内容状态 contents.status</b>
      <div class="muted tiny mt6" v-for="(v, k) in CONTENT_STATUS" :key="k">{{ k }} = {{ v }}</div>
    </div>
    <div>
      <b class="tiny">变体确认 / 发布状态</b>
      <div class="muted tiny mt6" v-for="(v, k) in CONFIRM_STATUS" :key="'c' + k">confirm: {{ k }} = {{ v }}</div>
      <div class="muted tiny" v-for="(v, k) in PUBLISH_STATUS" :key="'p' + k">publish: {{ k }} = {{ v }}</div>
    </div>
    <div>
      <b class="tiny">线索 / 素材</b>
      <div class="muted tiny mt6" v-for="(v, k) in LEAD_STATUS" :key="'l' + k">线索 {{ k }} = {{ v }}</div>
      <div class="muted tiny" v-for="(v, k) in INTENT" :key="'i' + k">意向 {{ k }} = {{ v }}</div>
      <div class="muted tiny" v-for="(v, k) in IDENTITY" :key="'d' + k">身份 {{ k }} = {{ v }}</div>
      <div class="muted tiny" v-for="(v, k) in PUBLICITY" :key="'y' + k">公开级 {{ k }} = {{ v }}</div>
    </div>
  </div>
</div>
`,
};
