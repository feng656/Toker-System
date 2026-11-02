/**
 * 数据看板：发布 / 曝光 / 互动 / 线索漏斗 + 异常状态 + 数字与明细一致性核对。
 * 完成标志（《分工》4.2）：看板数字与明细操作一致。
 */
import { ref, reactive, computed, onMounted } from '../core/vue.js';
import { dashboardApi, metricApi } from '../api/business.js';
import { contentApi } from '../api/content.js';
import { leadApi } from '../api/business.js';
import { notify, errorMessage } from '../core/ui.js';
import { todayStr, platformName, fmtDate } from '../core/format.js';

export default {
  name: 'PageDashboard',
  setup() {
    const funnel = reactive({ published: 0, views: 0, interactions: 0, leads: 0, high_intent: 0 });
    const contents = ref([]);
    const leads = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);
    const metricForm = reactive({
      variant_id: undefined, stat_date: todayStr(),
      views: undefined, likes: undefined, comments: undefined, collects: undefined,
      shares: undefined, new_fans: undefined, dm_inquiries: undefined,
    });
    const saving = ref(false);

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        const [fun, cs, ls] = await Promise.all([
          dashboardApi.funnel(),
          contentApi.list(),
          leadApi.list(),
        ]);
        Object.assign(funnel, fun || {});
        contents.value = cs || [];
        leads.value = ls || [];
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
      } finally {
        loading.value = false;
      }
    }

    const allVariants = computed(() => {
      const out = [];
      contents.value.forEach((c) => {
        (c.variants || []).forEach((v) => out.push({ ...v, content_title: c.title, biz_line: c.biz_line }));
      });
      return out;
    });

    const publishedVariants = computed(() => allVariants.value.filter((v) => !!v.published_url));

    /** 一致性核对：后端漏斗 published 与前端明细口径比对 */
    const consistency = computed(() => {
      const detail = publishedVariants.value.length;
      const server = Number(funnel.published || 0);
      return { detail, server, same: detail === server };
    });

    /** 异常状态统计 */
    const anomalies = computed(() => {
      const vs = allVariants.value;
      return {
        blocked: vs.filter((v) => v.compliance_ok === false).length,
        failed: vs.filter((v) => v.publish_status === 'failed').length,
        pendingConfirm: vs.filter((v) => v.confirm_status === 'pending').length,
        noLink: vs.filter((v) => !v.published_url).length,
        unassigned: leads.value.filter((l) => !l.assignee).length,
        noContact: leads.value.filter((l) => !l.contact_info).length,
        highIntentNoOwner: leads.value.filter((l) => l.intent === 'high' && !l.assignee).length,
      };
    });

    /** 30 天内重复联系方式：前端只做提示，后端去重未实现（GAP-08） */
    const duplicateContacts = computed(() => {
      const map = new Map();
      const dup = [];
      leads.value.forEach((l) => {
        const c = (l.contact_info || '').trim();
        if (!c) return;
        const key = c.replace(/\s+/g, '');
        if (map.has(key)) {
          dup.push({ contact: c, first: map.get(key), second: l.id });
        } else {
          map.set(key, l.id);
        }
      });
      return dup;
    });

    /** 近 7 天发布趋势：后端无 /dashboard/trend（GAP-05），此处由明细本地聚合 */
    const trend = computed(() => {
      const days = [];
      const base = new Date();
      for (let i = 6; i >= 0; i -= 1) {
        const d = new Date(base.getTime() - i * 86400000);
        const p = (n) => String(n).padStart(2, '0');
        const key = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
        const n = publishedVariants.value.filter((v) => (v.published_at || '').slice(0, 10) === key).length;
        days.push({ date: key.slice(5), count: n });
      }
      return days;
    });

    const maxTrend = computed(() => Math.max(1, ...trend.value.map((d) => d.count)));

    async function saveMetric() {
      if (!metricForm.variant_id) { notify.err('请填写版本 ID'); return; }
      saving.value = true;
      try {
        await metricApi.save({
          ...metricForm,
          variant_id: Number(metricForm.variant_id),
          stat_date: metricForm.stat_date,
          views: metricForm.views || 0, likes: metricForm.likes || 0, comments: metricForm.comments || 0,
          collects: metricForm.collects || 0, shares: metricForm.shares || 0,
          new_fans: metricForm.new_fans || 0, dm_inquiries: metricForm.dm_inquiries || 0,
        });
        notify.ok('指标已录入（同一版本 + 同一天会覆盖更新）');
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        saving.value = false;
      }
    }

    onMounted(load);

    return {
      funnel, contents, leads, loading, error, forbidden, metricForm, saving,
      allVariants, publishedVariants, consistency, anomalies, duplicateContacts, trend, maxTrend,
      load, saveMetric, platformName, fmtDate,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">数据看板</div>
    <div class="page-sub">漏斗口径：<b>已发布 = 有有效发布链接的版本数</b>；曝光 = 人工确认后录入的 metrics 合计；互动 = 已录入的评论 / 私信条数；线索 = 已生成的销售线索条数。页面下方有「数字 vs 明细」的一致性核对。</div>
  </div>
  <div class="row"><el-button size="small" @click="load" :loading="loading">刷新</el-button></div>
</div>

<div v-if="forbidden" class="page-state">
  <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可查看数据看板，请联系管理员。"></el-result>
</div>
<div v-else-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
</div>
<div v-else-if="loading" class="card"><el-skeleton :rows="8" animated /></div>

<template v-else>
  <div class="grid5">
    <div class="card stat"><div class="n">{{ funnel.published }}</div><div class="l">已发布内容</div><div class="d">有发布链接的版本</div></div>
    <div class="card stat"><div class="n">{{ funnel.views }}</div><div class="l">总曝光</div><div class="d">人工确认后录入</div></div>
    <div class="card stat"><div class="n">{{ funnel.interactions }}</div><div class="l">评论 / 私信</div><div class="d">已录入互动</div></div>
    <div class="card stat"><div class="n">{{ funnel.leads }}</div><div class="l">线索总数</div><div class="d">AI 打标生成</div></div>
    <div class="card stat"><div class="n g-hot">{{ funnel.high_intent }}</div><div class="l">高意向线索</div><div class="d">需优先跟进</div></div>
  </div>

  <div class="card" v-if="!consistency.same">
    <div class="alert-strip error">
      ⚠ 数字与明细不一致：看板「已发布」= {{ consistency.server }}，明细中带链接的版本 = {{ consistency.detail }}。
      多半是发布量口径或回填数据问题，请先核对「今日待办」的回填记录（见《接口缺口清单》GAP-14）。
    </div>
  </div>
  <div class="card" v-else>
    <div class="alert-strip ok">✓ 数字与明细一致：已发布 {{ consistency.server }} 条 = 明细中带有效链接的版本 {{ consistency.detail }} 条。</div>
  </div>

  <div class="grid3">
    <div class="card">
      <h4 class="card-title">近 7 天发布趋势</h4>
      <div class="row" style="align-items:flex-end;gap:10px;height:120px">
        <div v-for="d in trend" :key="d.date" style="flex:1;text-align:center">
          <div :style="'height:' + Math.round(d.count / maxTrend * 90) + 'px;background:#409eff;border-radius:4px 4px 0 0'" v-if="d.count"></div>
          <div class="muted tiny">{{ d.date }}</div>
          <div class="tiny"><b>{{ d.count }}</b></div>
        </div>
      </div>
      <div class="gap-note">后端暂无 /dashboard/trend 接口（《接口缺口清单》GAP-05），此处按「内容明细里的发布时间」在前端本地聚合，仅供趋势参考。</div>
    </div>

    <div class="card">
      <h4 class="card-title">异常状态</h4>
      <div class="kv">
        <span class="k">命中红线</span><span>{{ anomalies.blocked }} 个版本（禁止发布）</span>
        <span class="k">发布失败</span><span>{{ anomalies.failed }} 个版本</span>
        <span class="k">待人工确认</span><span>{{ anomalies.pendingConfirm }} 个版本</span>
        <span class="k">未回填链接</span><span>{{ anomalies.noLink }} 个版本（不计入发布量）</span>
        <span class="k">未指派线索</span><span>{{ anomalies.unassigned }} 条</span>
        <span class="k">高意向未指派</span><span :style="anomalies.highIntentNoOwner ? 'color:#f56c6c' : ''">{{ anomalies.highIntentNoOwner }} 条（优先处理）</span>
        <span class="k">无联系方式</span><span>{{ anomalies.noContact }} 条</span>
      </div>
    </div>

    <div class="card">
      <h4 class="card-title">线索质量提示</h4>
      <div v-if="duplicateContacts.length" class="alert-strip warn">
        发现 {{ duplicateContacts.length }} 组重复联系方式（例：{{ duplicateContacts[0].contact }}）。
        <b>后端 30 天去重尚未实现</b>（《接口缺口清单》GAP-08），请人工合并后再新建。
      </div>
      <div v-else class="alert-strip ok">当前未发现重复联系方式。</div>
      <div class="gap-note">线索去重规则（业务口径）：联系方式优先，作者 + 平台其次，需求相似度兜底；同一联系方式 30 天内不得重复建线索。</div>
    </div>
  </div>

  <div class="card">
    <h4 class="card-title">录入效果数据（截图 OCR 尚未接入，先手工录入）</h4>
    <div class="row">
      <el-input-number v-model="metricForm.variant_id" :min="1" placeholder="版本 ID" size="small" controls-position="right"></el-input-number>
      <el-date-picker v-model="metricForm.stat_date" type="date" value-format="YYYY-MM-DD" size="small" placeholder="统计日期"></el-date-picker>
      <el-input-number v-model="metricForm.views" :min="0" placeholder="曝光" size="small" controls-position="right"></el-input-number>
      <el-input-number v-model="metricForm.likes" :min="0" placeholder="点赞" size="small" controls-position="right"></el-input-number>
      <el-input-number v-model="metricForm.comments" :min="0" placeholder="评论" size="small" controls-position="right"></el-input-number>
      <el-input-number v-model="metricForm.collects" :min="0" placeholder="收藏" size="small" controls-position="right"></el-input-number>
      <el-input-number v-model="metricForm.shares" :min="0" placeholder="转发" size="small" controls-position="right"></el-input-number>
      <el-input-number v-model="metricForm.dm_inquiries" :min="0" placeholder="私信询价" size="small" controls-position="right"></el-input-number>
      <el-button size="small" type="primary" :loading="saving" @click="saveMetric">保存指标</el-button>
    </div>
    <div class="gap-note">
      版本 ID 可以在「内容管理」展开任一版本后查看（悬停状态标签可见），或在「今日待办」的条目上查看。
      同一「版本 + 同一天」重复录入会覆盖更新，不会重复累加。
    </div>
  </div>

  <div class="card">
    <h4 class="card-title">已发布明细（与上方数字同源）</h4>
    <el-table :data="publishedVariants" size="small" empty-text="暂无已发布内容">
      <el-table-column label="平台" width="90">
        <template #default="s"><span class="pf" :class="'pf-' + s.row.platform">{{ platformName(s.row.platform) }}</span></template>
      </el-table-column>
      <el-table-column prop="content_title" label="内容" min-width="200"></el-table-column>
      <el-table-column label="发布链接" min-width="220">
        <template #default="s"><a :href="s.row.published_url" target="_blank">{{ s.row.published_url }}</a></template>
      </el-table-column>
      <el-table-column label="发布时间" width="130">
        <template #default="s">{{ fmtDate(s.row.published_at) }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>
`,
};
