/**
 * 线索看板：意向 / 身份 / 负责人 / 状态流转 / 联系记录。
 * 完成标志（《分工》4.2）：销售能快速找到高意向并更新跟进结果。
 */
import { ref, reactive, computed, onMounted } from '../core/vue.js';
import { leadApi, interactionApi } from '../api/business.js';
import { phase2Api } from '../api/phase2.js';
import { authApi } from '../api/auth.js';
import { notify, errorMessage } from '../core/ui.js';
import {
  platformName, intentName, identityName, leadStatusName, fmtDateTime, LEAD_STATUS, INTENT, IDENTITY,
} from '../core/format.js';
import { isAdmin } from '../core/store.js';

export default {
  name: 'PageLeads',
  setup() {
    const leads = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);
    const filter = reactive({ intent: '', identity: '', status: '', assignee: '', keyword: '' });
    const busy = reactive({});

    const salesUsers = ref([]);
    const detail = ref(null);
    const drawer = ref(false);
    const noteDlg = ref(false);
    const noteDraft = ref('');
    const simDlg = ref(false);
    const simForm = reactive({ platform: 'douyin', author_name: '', body: '' });
    const simResult = ref(null);

    /* ---- 二期 R7/R11：评论互动 + 私信接管 ---- */
    const ltab = ref('leads');
    const wsAccs = ref([]);
    const dmTmpls = ref([]);
    const dmProvs = ref([]);
    const dmMsgs = ref([]);
    const ctasks = ref([]);
    const p2Loading = ref(false);
    const ctForm = reactive({ account_id: null, keyword: '', mode: 'manual', draft: '', video_limit: 5, comments_per_video: 10, date_from: '', sort_order: 'latest' });
    const ctBusy = reactive({});
    const tplForm = reactive({ name: '', body: '', enabled: true });
    const dmForm = reactive({ account_id: null, mode: 'fixed', template_id: null, provider_id: null, persona: '', window_start: '09:00', window_end: '18:00', scope: '', enabled: false });
    const dmBusy = reactive({});

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        leads.value = await leadApi.list() || [];
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
        leads.value = [];
      } finally {
        loading.value = false;
      }
    }

    async function loadSales() {
      if (!isAdmin()) return;
      try {
        const users = await authApi.listUsers();
        salesUsers.value = (users || []).filter((u) => u.role === 'sales');
      } catch (e) { /* 非管理员或无权限，忽略 */ }
    }

    const filtered = computed(() => {
      const kw = filter.keyword.trim();
      return leads.value.filter((l) => {
        if (filter.intent && l.intent !== filter.intent) return false;
        if (filter.identity && l.identity !== filter.identity) return false;
        if (filter.status && l.status !== filter.status) return false;
        if (filter.assignee && l.assignee !== filter.assignee) return false;
        if (kw) {
          const hay = `${l.visitor_name || ''}${l.need_summary || ''}${l.contact_info || ''}${l.brand_need || ''}`;
          if (hay.indexOf(kw) < 0) return false;
        }
        return true;
      });
    });

    const highCount = computed(() => filtered.value.filter((l) => l.intent === 'high').length);
    const unassigned = computed(() => filtered.value.filter((l) => !l.assignee).length);

    async function updateLead(l, patch) {
      busy[l.id] = true;
      try {
        const updated = await leadApi.update(l.id, patch);
        Object.assign(l, updated);
        notify.ok('已更新');
      } catch (e) {
        notify.err(errorMessage(e));
        await load();
      } finally {
        busy[l.id] = false;
      }
    }

    function openDetail(l) {
      detail.value = l;
      drawer.value = true;
    }

    function openNote(l) {
      detail.value = l;
      noteDraft.value = l.follow_notes || '';
      noteDlg.value = true;
    }

    async function saveNote() {
      if (!detail.value) return;
      await updateLead(detail.value, { follow_notes: noteDraft.value });
      noteDlg.value = false;
    }

    async function push(l) {
      busy[l.id] = true;
      try {
        const d = await leadApi.push(l.id);
        if (d && d.pushed) notify.ok('企微提醒已发送');
        else notify.warn('企微推送未成功：未配置 WECOM_WEBHOOK 或网络失败（失败可重试，GAP-10）');
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[l.id] = false;
      }
    }

    async function addInteraction() {
      if (!simForm.body.trim()) { notify.err('请填写评论 / 私信原文'); return; }
      try {
        const d = await interactionApi.create({ ...simForm, auto_classify: true });
        const lead = d && d.lead;
        simResult.value = lead || null;
        notify.ok(lead ? `已打标：${intentName(lead.intent)} / ${identityName(lead.identity)}` : '已录入');
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    /* ---- 二期 R7/R11 逻辑 ---- */
    async function loadPhase2() {
      p2Loading.value = true;
      try {
        const [accs, tmpls, provs, tasks, msgs] = await Promise.all([
          phase2Api.wsAccounts().catch(() => []),
          phase2Api.replyTemplates().catch(() => []),
          phase2Api.providers().catch(() => []),
          phase2Api.commentTasks().catch(() => []),
          phase2Api.dmMessages().catch(() => []),
        ]);
        wsAccs.value = accs || [];
        dmTmpls.value = tmpls || [];
        dmProvs.value = (provs || []).filter((p) => p.enabled);
        ctasks.value = tasks || [];
        dmMsgs.value = msgs || [];
        if (!ctForm.account_id && wsAccs.value.length) ctForm.account_id = wsAccs.value[0].id;
        if (!dmForm.account_id && wsAccs.value.length) dmForm.account_id = wsAccs.value[0].id;
      } catch (e) { /* 二期数据失败不阻塞线索页 */ } finally {
        p2Loading.value = false;
      }
    }

    function accLabel(id) {
      const a = wsAccs.value.find((x) => x.id === id);
      return a ? a.label : '账号#' + id;
    }

    async function createCommentTask() {
      if (!ctForm.account_id) { notify.err('请先在「工作台」添加并登录平台账号'); return; }
      if (!ctForm.keyword.trim()) { notify.err('搜索关键词必填'); return; }
      if ((ctForm.mode === 'manual' || ctForm.mode === 'polish') && !ctForm.draft.trim()) {
        notify.err('自写 / 润色模式需要填写评论草稿'); return;
      }
      try {
        const t = await phase2Api.createCommentTask({
          account_id: ctForm.account_id, keyword: ctForm.keyword.trim(), mode: ctForm.mode,
          draft: ctForm.draft, video_limit: ctForm.video_limit, comments_per_video: ctForm.comments_per_video,
          date_from: ctForm.date_from || null, sort_order: ctForm.sort_order,
        });
        notify.ok(`任务 #${t.id} 已创建：关键词「${ctForm.keyword.trim()}」，${ctForm.video_limit} 个视频 × ${ctForm.comments_per_video} 条评论`);
        await loadPhase2();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    async function taskAction(t, action) {
      ctBusy[t.id] = true;
      try {
        let d = null;
        if (action === 'discover') d = await phase2Api.commentTaskDiscover(t.id);
        else if (action === 'prepare') d = await phase2Api.commentTaskPrepare(t.id);
        else if (action === 'approve') d = await phase2Api.commentTaskApprove(t.id);
        else if (action === 'run') d = await phase2Api.commentTaskRun(t.id);
        else if (action === 'stop') d = await phase2Api.commentTaskStop(t.id);
        else if (action === 'collect') d = await phase2Api.commentTaskCollect(t.id);
        const tname = { discover: '视频发现', prepare: '评论生成', approve: '人工批准', run: '执行发送', stop: '停止', collect: '需求收集' }[action];
        notify.ok(`${tname}已完成`);
        if (action === 'collect') notify.info(d && d.collected !== undefined ? `已收集 ${d.collected} 条需求入线索库` : '需求已收集');
        await loadPhase2();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        ctBusy[t.id] = false;
      }
    }

    async function addTemplate() {
      if (!tplForm.name.trim() || !tplForm.body.trim()) { notify.err('模板名称与内容必填'); return; }
      try {
        await phase2Api.addReplyTemplate({ name: tplForm.name.trim(), body: tplForm.body, enabled: tplForm.enabled });
        notify.ok('话术模板已保存');
        Object.assign(tplForm, { name: '', body: '', enabled: true });
        await loadPhase2();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    async function saveDmPolicy() {
      if (!dmForm.account_id) { notify.err('请先选择平台账号'); return; }
      if (dmForm.mode === 'fixed' && !dmForm.template_id) { notify.err('固定话术模式必须选择模板'); return; }
      dmBusy.policy = true;
      try {
        await phase2Api.saveDmPolicy({
          account_id: dmForm.account_id, mode: dmForm.mode,
          template_id: dmForm.mode === 'fixed' ? dmForm.template_id : null,
          provider_id: dmForm.mode === 'ai' ? dmForm.provider_id : null,
          persona: dmForm.persona,
          window_start: dmForm.window_start, window_end: dmForm.window_end,
          scope: dmForm.scope.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
          enabled: dmForm.enabled,
        });
        notify.ok('私信接管策略已保存');
        await loadPhase2();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        dmBusy.policy = false;
      }
    }

    async function dmAction(m, action) {
      dmBusy[m.id] = true;
      try {
        if (action === 'prepare') await phase2Api.dmPrepare(m.id);
        else if (action === 'approve') await phase2Api.dmApprove(m.id);
        else if (action === 'send') await phase2Api.dmSend(m.id);
        notify.ok('操作完成');
        await loadPhase2();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        dmBusy[m.id] = false;
      }
    }

    const ctStatusName = (s) => ({ queued: '排队中', discovering: '发现视频', prepared: '评论已生成', approved: '已批准', running: '发送中', succeeded: '已完成', failed: '失败', cancelled: '已停止' }[s] || s);
    const dmStatusName = (s) => ({ received: '待处理', prepared: '回复已生成', approved: '待发送', sent: '已发送', review: '转人工' }[s] || s);

    onMounted(async () => {
      await load();
      await loadSales();
      loadPhase2();
    });

    return {
      leads, filtered, loading, error, forbidden, filter, busy, salesUsers,
      detail, drawer, noteDlg, noteDraft, simDlg, simForm, simResult, highCount, unassigned,
      load, updateLead, openDetail, openNote, saveNote, push, addInteraction,
      platformName, intentName, identityName, leadStatusName, fmtDateTime,
      LEAD_STATUS, INTENT, IDENTITY, isAdmin,
      ltab, wsAccs, dmTmpls, dmProvs, dmMsgs, ctasks, p2Loading, ctForm, ctBusy,
      tplForm, dmForm, dmBusy,
      loadPhase2, accLabel, createCommentTask, taskAction, addTemplate, saveDmPolicy, dmAction,
      ctStatusName, dmStatusName,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">线索看板</div>
    <div class="page-sub">按意向、身份、负责人、状态筛选线索；跟进后务必更新状态并写一条联系记录——没有记录的高意向线索不允许标为「商机」。高意向线索由系统自动推送企微提醒，推送失败可手动重试。</div>
  </div>
  <div class="row">
    <el-button size="small" @click="simDlg = true">+ 录入评论 / 私信</el-button>
    <el-button size="small" @click="load" :loading="loading">刷新</el-button>
  </div>
</div>

<el-tabs v-model="ltab">
  <el-tab-pane label="线索看板" name="leads">
    <div class="toolbar">
  <el-select v-model="filter.intent" placeholder="全部意向" clearable size="small" style="width:120px">
    <el-option v-for="(v, k) in INTENT" :key="k" :label="v" :value="k"></el-option>
  </el-select>
  <el-select v-model="filter.identity" placeholder="全部身份" clearable size="small" style="width:110px">
    <el-option v-for="(v, k) in IDENTITY" :key="k" :label="v" :value="k"></el-option>
  </el-select>
  <el-select v-model="filter.status" placeholder="全部状态" clearable size="small" style="width:120px">
    <el-option v-for="(v, k) in LEAD_STATUS" :key="k" :label="v" :value="k"></el-option>
  </el-select>
  <el-input v-model="filter.assignee" placeholder="负责人" size="small" clearable style="width:110px"></el-input>
  <el-input v-model="filter.keyword" placeholder="搜索访客 / 需求 / 联系方式" size="small" clearable style="width:220px"></el-input>
  <span class="muted">共 {{ filtered.length }} 条 · 高意向 {{ highCount }} 条 · 未指派 {{ unassigned }} 条</span>
</div>

<div v-if="forbidden" class="page-state">
  <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可查看线索看板，请联系管理员。"></el-result>
</div>
<div v-else-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
</div>
<div v-else-if="loading" class="card"><el-skeleton :rows="6" animated /></div>

<template v-else>
  <div v-if="!filtered.length" class="card">
    <div class="state-box"><el-icon><i class="el-icon-user" /></el-icon>暂无符合条件的线索</div>
  </div>

  <div class="card leadcard" :class="l.intent" v-for="l in filtered" :key="l.id">
    <div class="row">
      <span class="pf" :class="'pf-' + l.platform">{{ platformName(l.platform) }}</span>
      <b>{{ l.visitor_name || '未留昵称' }}</b>
      <span :class="'intent-' + l.intent">{{ intentName(l.intent) }}</span>
      <el-tag size="small">{{ identityName(l.identity) }}</el-tag>
      <el-tag size="small" type="info">{{ leadStatusName(l.status) }}</el-tag>
      <el-tag v-if="!l.assignee" size="small" type="warning">未指派</el-tag>
      <span class="muted right">{{ fmtDateTime(l.created_at) }}</span>
    </div>
    <div class="mt10" style="font-size:14px">{{ l.need_summary || '（AI 未提取到需求摘要）' }}</div>
    <div v-if="l.contact_info" class="mt6" style="color:#e6792f;font-size:13px">📞 {{ l.contact_info }}</div>
    <div v-if="l.brand_need" class="mt6 muted">提及品牌：{{ l.brand_need }}</div>
    <div v-if="l.reply_suggestion" class="mt6" style="color:#67c23a;font-size:13px">💬 建议话术：{{ l.reply_suggestion }}</div>
    <div v-if="l.follow_notes" class="mt6 muted">跟进记录：{{ l.follow_notes }}</div>

    <div class="row mt14">
      <el-select :value="l.status" size="small" style="width:130px" :disabled="busy[l.id]"
                 @change="(v) => updateLead(l, { status: v })">
        <el-option v-for="(v, k) in LEAD_STATUS" :key="k" :label="v" :value="k"></el-option>
      </el-select>
      <el-select v-if="isAdmin && salesUsers.length" :value="l.assignee" size="small" style="width:140px"
                 placeholder="指派销售" filterable clearable :disabled="busy[l.id]"
                 @change="(v) => updateLead(l, { assignee: v || '' })">
        <el-option v-for="u in salesUsers" :key="u.id" :label="u.name || u.username" :value="u.name || u.username"></el-option>
      </el-select>
      <el-input v-else :value="l.assignee" size="small" placeholder="指派销售" style="width:120px"
                :disabled="busy[l.id]" @change="(val) => updateLead(l, { assignee: val })"></el-input>
      <el-button size="small" @click="openNote(l)">联系记录</el-button>
      <el-button size="small" @click="push(l)" :loading="busy[l.id]">推送企微</el-button>
      <el-button size="small" text type="primary" @click="openDetail(l)">详情</el-button>
    </div>
  </div>
</template>
  </el-tab-pane>

  <el-tab-pane label="评论互动（二期 · 授权评论）" name="comments">
    <div class="card">
      <h4 class="card-title">新建评论任务</h4>
      <div class="row">
        <el-select v-model="ctForm.account_id" size="small" style="width:170px" placeholder="平台账号">
          <el-option v-for="a in wsAccs" :key="a.id" :label="accLabel(a.id) + (a.status === 'connected' ? '（已登录）' : '（未登录）')" :value="a.id"></el-option>
        </el-select>
        <el-input v-model="ctForm.keyword" size="small" style="width:200px" placeholder="搜索关键词（必填）"></el-input>
        <el-select v-model="ctForm.mode" size="small" style="width:130px">
          <el-option label="自写评论" value="manual"/>
          <el-option label="AI 润色" value="polish"/>
          <el-option label="AI 帮写" value="ai"/>
        </el-select>
        <el-select v-model="ctForm.sort_order" size="small" style="width:110px">
          <el-option label="按最新" value="latest"/>
          <el-option label="按热门" value="popular"/>
        </el-select>
        <el-date-picker v-model="ctForm.date_from" type="date" size="small" value-format="YYYY-MM-DD" placeholder="发布时间从" style="width:140px"></el-date-picker>
        <el-input-number v-model="ctForm.video_limit" size="small" :min="1" :max="5" style="width:130px"></el-input-number>
        <span class="muted">个视频 ×</span>
        <el-input-number v-model="ctForm.comments_per_video" size="small" :min="1" :max="10" style="width:130px"></el-input-number>
        <span class="muted">条评论（默认 10）</span>
      </div>
      <el-input v-model="ctForm.draft" type="textarea" :rows="3" class="mt10" placeholder="评论草稿（自写 / 润色模式必填；AI 帮写模式留空，由系统按关键词生成）"></el-input>
      <div class="row mt10">
        <el-button type="primary" size="small" @click="createCommentTask">保存配置并创建任务</el-button>
        <span class="muted">启用后请到平台网页版搜索栏填入关键词，确认后系统自动发现视频 → 生成评论 → 人工批准 → 发送。</span>
      </div>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h4 class="card-title" style="margin:0">评论任务列表</h4>
        <el-button size="small" @click="loadPhase2" :loading="p2Loading">刷新</el-button>
      </div>
      <el-table :data="ctasks" size="small" empty-text="暂无评论任务">
        <el-table-column prop="id" label="ID" width="70"></el-table-column>
        <el-table-column prop="keyword" label="关键词" min-width="130"></el-table-column>
        <el-table-column label="账号" width="140">
          <template #default="s"><span>{{ accLabel(s.row.account_id) }}</span></template>
        </el-table-column>
        <el-table-column label="模式" width="90">
          <template #default="s"><span>{{ {manual:'自写',polish:'润色',ai:'帮写'}[s.row.mode] || s.row.mode }}</span></template>
        </el-table-column>
        <el-table-column label="规模" width="120">
          <template #default="s"><span class="muted">{{ s.row.video_limit }} 视频 × {{ s.row.comments_per_video }} 条</span></template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="s"><el-tag size="small">{{ ctStatusName(s.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" min-width="300">
          <template #default="s">
            <el-button size="small" text type="primary" :loading="ctBusy[s.row.id]" @click="taskAction(s.row, 'discover')">发现视频</el-button>
            <el-button size="small" text type="primary" :loading="ctBusy[s.row.id]" @click="taskAction(s.row, 'prepare')">生成评论</el-button>
            <el-button size="small" text type="warning" :loading="ctBusy[s.row.id]" @click="taskAction(s.row, 'approve')">批准</el-button>
            <el-button size="small" text type="success" :loading="ctBusy[s.row.id]" @click="taskAction(s.row, 'run')">执行</el-button>
            <el-button size="small" text type="danger" :loading="ctBusy[s.row.id]" @click="taskAction(s.row, 'stop')">停止</el-button>
            <el-button size="small" text :loading="ctBusy[s.row.id]" @click="taskAction(s.row, 'collect')">收集需求</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="gap-note">流程：发现视频 → 生成评论（去重 + 去 AI 味）→ 人工批准 → 执行发送 → 收集评论中的需求入线索库。发送默认关闭，需管理员在配置中启用。</div>
    </div>
  </el-tab-pane>

  <el-tab-pane label="私信接管（二期）" name="dm">
    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h4 class="card-title" style="margin:0">接管策略（按平台账号）</h4>
      </div>
      <div class="row">
        <el-select v-model="dmForm.account_id" size="small" style="width:170px" placeholder="平台账号">
          <el-option v-for="a in wsAccs" :key="a.id" :label="accLabel(a.id)" :value="a.id"></el-option>
        </el-select>
        <el-select v-model="dmForm.mode" size="small" style="width:140px">
          <el-option label="固定话术" value="fixed"/>
          <el-option label="AI 接管（自选智能体）" value="ai"/>
        </el-select>
        <el-select v-if="dmForm.mode === 'fixed'" v-model="dmForm.template_id" size="small" style="width:180px" placeholder="选择话术模板">
          <el-option v-for="t in dmTmpls" :key="t.id" :label="t.name" :value="t.id"></el-option>
        </el-select>
        <el-select v-if="dmForm.mode === 'ai'" v-model="dmForm.provider_id" size="small" style="width:180px" placeholder="选择 AI（文本）">
          <el-option v-for="p in dmProvs.filter(x => x.capability === 'text')" :key="p.id" :label="p.name" :value="p.id"></el-option>
        </el-select>
        <el-time-select v-model="dmForm.window_start" size="small" start="00:00" step="00:30" end="23:30" style="width:110px"></el-time-select>
        <span class="muted">至</span>
        <el-time-select v-model="dmForm.window_end" size="small" start="00:00" step="00:30" end="23:30" style="width:110px"></el-time-select>
        <el-switch v-model="dmForm.enabled" active-text="启用"></el-switch>
      </div>
      <el-input v-if="dmForm.mode === 'ai'" v-model="dmForm.persona" class="mt10" placeholder="人设提示词（例：你是自由光公司客服，专业、简洁，不承诺价格）"></el-input>
      <el-input v-model="dmForm.scope" class="mt10" placeholder="接管范围（发送者关键词，逗号分隔，如：LED,大屏；留空表示需人工明确范围）"></el-input>
      <div class="row mt10">
        <el-button type="primary" size="small" :loading="dmBusy.policy" @click="saveDmPolicy">保存策略</el-button>
        <span class="muted">启用需要明确发送者范围与有效时间窗；高风险私信自动转人工。</span>
      </div>
    </div>

    <div class="card">
      <h4 class="card-title">话术模板</h4>
      <div class="row">
        <el-input v-model="tplForm.name" size="small" style="width:160px" placeholder="模板名称"></el-input>
        <el-input v-model="tplForm.body" size="small" style="width:360px" placeholder="话术内容"></el-input>
        <el-button size="small" type="primary" @click="addTemplate">添加模板</el-button>
      </div>
      <el-table :data="dmTmpls" size="small" empty-text="暂无模板" class="mt10">
        <el-table-column prop="name" label="名称" width="160"></el-table-column>
        <el-table-column prop="body" label="内容" min-width="300" show-overflow-tooltip></el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="s"><el-tag size="small" :type="s.row.enabled ? 'success' : 'info'">{{ s.row.enabled ? '是' : '否' }}</el-tag></template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card">
      <h4 class="card-title">私信消息（留痕可回溯）</h4>
      <el-table :data="dmMsgs" size="small" empty-text="暂无私信消息">
        <el-table-column prop="id" label="ID" width="70"></el-table-column>
        <el-table-column label="账号" width="140">
          <template #default="s"><span>{{ accLabel(s.row.account_id) }}</span></template>
        </el-table-column>
        <el-table-column prop="sender_id" label="发送者" width="140"></el-table-column>
        <el-table-column prop="body" label="内容" min-width="220" show-overflow-tooltip></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="s"><el-tag size="small">{{ dmStatusName(s.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="s">
            <el-button size="small" text type="primary" :loading="dmBusy[s.row.id]" @click="dmAction(s.row, 'prepare')">生成回复</el-button>
            <el-button size="small" text type="warning" :loading="dmBusy[s.row.id]" @click="dmAction(s.row, 'approve')">批准</el-button>
            <el-button size="small" text type="success" :loading="dmBusy[s.row.id]" @click="dmAction(s.row, 'send')">发送</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </el-tab-pane>
</el-tabs>

<el-dialog v-model="noteDlg" title="联系记录" width="520px">
  <div class="muted mb10">记录与该线索的最新沟通情况（当前后端只保存最新一条，不保留历史，见《接口缺口清单》GAP-13）。</div>
  <el-input v-model="noteDraft" type="textarea" :rows="5" placeholder="例：已电话沟通，对方需要 3 米 P2.0，报价走私信；约定周三发方案"></el-input>
  <template #footer>
    <el-button @click="noteDlg = false">取消</el-button>
    <el-button type="primary" @click="saveNote">保存记录</el-button>
  </template>
</el-dialog>

<el-drawer v-model="drawer" title="线索详情" size="460px">
  <div v-if="detail" class="kv">
    <span class="k">平台</span><span>{{ platformName(detail.platform) }}</span>
    <span class="k">访客</span><span>{{ detail.visitor_name || '-' }}</span>
    <span class="k">意向</span><span>{{ intentName(detail.intent) }}</span>
    <span class="k">身份</span><span>{{ identityName(detail.identity) }}</span>
    <span class="k">需求摘要</span><span>{{ detail.need_summary || '-' }}</span>
    <span class="k">联系方式</span><span>{{ detail.contact_info || '未留' }}</span>
    <span class="k">品牌需求</span><span>{{ detail.brand_need || '-' }}</span>
    <span class="k">建议话术</span><span>{{ detail.reply_suggestion || '-' }}</span>
    <span class="k">负责人</span><span>{{ detail.assignee || '未指派' }}</span>
    <span class="k">状态</span><span>{{ leadStatusName(detail.status) }}</span>
    <span class="k">跟进记录</span><span>{{ detail.follow_notes || '暂无' }}</span>
    <span class="k">创建时间</span><span>{{ fmtDateTime(detail.created_at) }}</span>
  </div>
  <div class="gap-note">评论 / 私信原文：后端暂未提供互动查询接口（《接口缺口清单》GAP-06），此处暂缺。</div>
</el-drawer>

<el-dialog v-model="simDlg" title="录入评论 / 私信（AI 自动打标）" width="540px">
  <el-form label-width="86px">
    <el-form-item label="平台">
      <el-select v-model="simForm.platform">
        <el-option label="抖音" value="douyin"/>
        <el-option label="视频号" value="shipinhao"/>
        <el-option label="公众号" value="gzh"/>
        <el-option label="小红书" value="xhs"/>
      </el-select>
    </el-form-item>
    <el-form-item label="昵称"><el-input v-model="simForm.author_name" placeholder="可选"></el-input></el-form-item>
    <el-form-item label="内容">
      <el-input v-model="simForm.body" type="textarea" :rows="4" placeholder="粘贴评论或私信原文，AI 会判断身份、意向与需求"></el-input>
    </el-form-item>
  </el-form>
  <div v-if="simResult" class="alert-strip ok">
    打标结果：{{ intentName(simResult.intent) }} / {{ identityName(simResult.identity) }}<br/>
    需求：{{ simResult.need_summary || '-' }}<br/>
    联系方式：{{ simResult.contact_info || '未留' }}
  </div>
  <template #footer>
    <el-button @click="simDlg = false">关闭</el-button>
    <el-button type="primary" @click="addInteraction">提交并 AI 打标</el-button>
  </template>
</el-dialog>
`,
};
