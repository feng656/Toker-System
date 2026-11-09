/**
 * 线索看板：意向 / 身份 / 负责人 / 状态流转 / 联系记录。
 * 完成标志（《分工》4.2）：销售能快速找到高意向并更新跟进结果。
 */
import { ref, reactive, computed, onMounted } from '../core/vue.js';
import { leadApi, interactionApi } from '../api/business.js';
import { topicApi } from '../api/library.js';
import { authApi } from '../api/auth.js';
import { notify, errorMessage } from '../core/ui.js';
import {
  platformName, intentName, identityName, leadStatusName, fmtDateTime, LEAD_STATUS, INTENT, IDENTITY,
  bizLineName, TOPIC_THEMES,
} from '../core/format.js';
import { isAdmin, canWriteContent } from '../core/store.js';

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
    const interactionDetail = ref(null);
    const interactionLoading = ref(false);
    const noteDlg = ref(false);
    const noteDraft = ref('');
    const simDlg = ref(false);
    const simForm = reactive({ platform: 'douyin', author_name: '', body: '' });
    const simResult = ref(null);

    /* ---------------- 需求转选题（M-R4-06） ---------------- */
    const topicDlg = ref(false);
    const topicSaving = ref(false);
    const topicSource = ref(null);
    const topicCreated = ref(null);
    const topicIndex = ref([]);
    const topicIndexLoading = ref(false);
    const topicDupConfirm = ref(false);
    const topicForm = reactive({ biz_line: 'project', theme: TOPIC_THEMES[0], title: '', angle: '' });

    function sourceMarker(l) {
      return `来源线索 #${l.id}｜${platformName(l.platform)}${l.visitor_name ? `｜${l.visitor_name}` : ''}`;
    }

    const convertedTopics = computed(() => {
      const l = topicSource.value;
      if (!l) return [];
      const marker = `来源线索 #${l.id}｜`;
      return topicIndex.value.filter((t) => (t.angle || '').indexOf(marker) >= 0);
    });

    const sameTitleTopics = computed(() => {
      const title = topicForm.title.trim();
      if (!title) return [];
      const skip = new Set(convertedTopics.value.map((t) => t.id));
      return topicIndex.value.filter((t) => t.title.trim() === title && !skip.has(t.id));
    });

    const topicFinalAngle = computed(() => {
      const l = topicSource.value;
      if (!l) return topicForm.angle;
      const body = topicForm.angle.trim();
      let block = `—— ${sourceMarker(l)}`;
      if (l.need_summary) block += `\n原始需求：${l.need_summary}`;
      if (l.reply_suggestion) block += `\n建议话术：${l.reply_suggestion}`;
      if (body.indexOf(`来源线索 #${l.id}｜`) >= 0) return body.slice(0, 5000);
      const room = Math.max(0, 5000 - block.length - 2);
      const head = body ? `${body.slice(0, room)}\n\n` : '';
      return (head + block).slice(0, 5000);
    });

    async function loadTopicIndex() {
      topicIndexLoading.value = true;
      try {
        const [active, used, archived] = await Promise.all([
          topicApi.list({ status: 'active' }),
          topicApi.list({ status: 'used' }),
          topicApi.list({ status: 'archived' }),
        ]);
        topicIndex.value = [...(active || []), ...(used || []), ...(archived || [])];
      } catch (e) {
        // 查重失败不阻塞转选题，创建时后端仍会校验字段
        topicIndex.value = [];
      } finally {
        topicIndexLoading.value = false;
      }
    }

    async function openTopic(l) {
      topicSource.value = l;
      topicCreated.value = null;
      topicDupConfirm.value = false;
      topicForm.biz_line = 'project';
      topicForm.theme = TOPIC_THEMES[0];
      topicForm.title = (l.need_summary || l.brand_need || `${platformName(l.platform)}线索需求`).slice(0, 200);
      topicForm.angle = l.need_summary
        ? `围绕「${l.need_summary.slice(0, 60)}」切入，先回应具体需求，再给出可执行建议。`
        : '';
      topicDlg.value = true;
      await Promise.all([loadTopicIndex(), ensureInteraction(l)]);
    }

    async function saveTopic() {
      if (!topicSource.value) return;
      if (!topicForm.theme.trim() || !topicForm.title.trim()) {
        notify.err('主题与选题标题为必填');
        return;
      }
      if (convertedTopics.value.length && !topicDupConfirm.value) {
        notify.warn('该线索已生成过选题；如确需换角度新增，请勾选「仍要创建」');
        return;
      }
      topicSaving.value = true;
      try {
        const created = await topicApi.create({
          biz_line: topicForm.biz_line,
          theme: topicForm.theme.trim(),
          title: topicForm.title.trim(),
          angle: topicFinalAngle.value,
        });
        topicCreated.value = created || { id: '', title: topicForm.title.trim() };
        if (created && created.id) topicIndex.value = [created, ...topicIndex.value];
        notify.ok(`已创建选题${created && created.id ? ` #${created.id}` : ''}，来源已写入角度`);
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        topicSaving.value = false;
      }
    }

    function goTopics() {
      topicDlg.value = false;
      window.location.hash = '#/contents?tab=topics';
    }

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

    async function ensureInteraction(l) {
      interactionDetail.value = null;
      if (!l || !l.interaction_id) return;
      interactionLoading.value = true;
      try {
        const list = await interactionApi.list({ limit: 500 });
        interactionDetail.value = (list || []).find((x) => x.id === l.interaction_id) || null;
      } catch (e) {
        interactionDetail.value = null;
      } finally {
        interactionLoading.value = false;
      }
    }

    async function openDetail(l) {
      detail.value = l;
      drawer.value = true;
      await ensureInteraction(l);
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

    onMounted(async () => {
      await load();
      await loadSales();
    });

    return {
      leads, filtered, loading, error, forbidden, filter, busy, salesUsers,
      detail, drawer, noteDlg, noteDraft, simDlg, simForm, simResult, highCount, unassigned,
      interactionDetail, interactionLoading,
      topicDlg, topicSaving, topicSource, topicCreated, topicIndexLoading, topicDupConfirm,
      topicForm, convertedTopics, sameTitleTopics, topicFinalAngle,
      load, updateLead, openDetail, openNote, saveNote, push, addInteraction,
      openTopic, saveTopic, goTopics,
      platformName, intentName, identityName, leadStatusName, fmtDateTime, bizLineName,
      LEAD_STATUS, INTENT, IDENTITY, isAdmin, canWriteContent, TOPIC_THEMES,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">线索看板</div>
    <div class="page-sub">按意向、身份、负责人、状态筛选线索；跟进后务必更新状态并写一条联系记录——没有记录的高意向线索不允许标为「商机」。高意向线索由系统自动推送企微提醒，推送失败可手动重试。</div>
  </div>
  <div class="row">
    <el-button v-if="canWriteContent" size="small" @click="simDlg = true">+ 录入评论 / 私信</el-button>
    <el-button size="small" @click="load" :loading="loading">刷新</el-button>
  </div>
</div>

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
        <el-option v-for="u in salesUsers" :key="u.id"
                   :label="u.name ? u.name + '（' + u.username + '）' : u.username"
                   :value="u.username"></el-option>
      </el-select>
      <el-input v-else :value="l.assignee" size="small" :placeholder="canWriteContent ? '指派销售' : '未指派'" style="width:120px"
                :disabled="busy[l.id] || !canWriteContent" @change="(val) => updateLead(l, { assignee: val })"></el-input>
      <el-button size="small" @click="openNote(l)">联系记录</el-button>
      <el-button v-if="canWriteContent" size="small" type="success" plain @click="openTopic(l)">💡 转选题</el-button>
      <el-button v-if="canWriteContent" size="small" @click="push(l)" :loading="busy[l.id]">推送企微</el-button>
      <el-button size="small" text type="primary" @click="openDetail(l)">详情</el-button>
    </div>
  </div>
</template>

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
  <div v-if="interactionLoading" class="gap-note">正在加载评论 / 私信原文…</div>
  <div v-else-if="interactionDetail" class="mt14">
    <div class="muted mb10">
      评论 / 私信原文 · {{ interactionDetail.kind === 'dm' ? '私信' : '评论' }}
      · {{ fmtDateTime(interactionDetail.created_at) }}
    </div>
    <div class="body-pre">{{ interactionDetail.body }}</div>
  </div>
  <div v-else class="gap-note">该线索未关联可查询的互动原文。后端 interactions 暂无 permalink 字段，无法回链到平台原帖。</div>
  <div v-if="detail && canWriteContent" class="row mt14">
    <el-button type="success" plain @click="openTopic(detail)">💡 用这条需求生成选题</el-button>
  </div>
</el-drawer>

<el-dialog v-model="topicDlg" title="线索转选题" width="620px">
  <div v-if="topicSource" class="alert-strip info">
    来源：{{ platformName(topicSource.platform) }} · {{ topicSource.visitor_name || '未留昵称' }} · 线索 #{{ topicSource.id }}
    <div class="mt6">需求：{{ topicSource.need_summary || '（无摘要，请在选题角度中补充）' }}</div>
    <div v-if="topicSource.contact_info" class="mt6">联系方式：{{ topicSource.contact_info }}</div>
  </div>

  <el-alert v-if="topicIndexLoading" type="info" :closable="false" title="正在检查选题池重复情况…" class="mb10" />
  <el-alert v-else-if="convertedTopics.length" type="error" :closable="false" show-icon class="mb10"
            title="该线索已生成过选题">
    <template #default>
      <div v-for="t in convertedTopics" :key="t.id">#{{ t.id }}「{{ t.title }}」· {{ bizLineName(t.biz_line) }}</div>
      <div class="tiny mt6">默认不再重复创建；确需换一个角度，请勾选下方确认。</div>
    </template>
  </el-alert>
  <el-alert v-else-if="sameTitleTopics.length" type="warning" :closable="false" show-icon class="mb10"
            :title="'选题池已有同名选题 #' + sameTitleTopics[0].id + '，请确认是否仍要创建'" />

  <el-form label-width="86px">
    <el-form-item label="业务线">
      <el-select v-model="topicForm.biz_line">
        <el-option label="甲方线" value="project"/>
        <el-option label="渠道线" value="channel"/>
      </el-select>
    </el-form-item>
    <el-form-item label="主题">
      <el-select v-model="topicForm.theme" filterable allow-create default-first-option>
        <el-option v-for="t in TOPIC_THEMES" :key="t" :label="t" :value="t"></el-option>
      </el-select>
    </el-form-item>
    <el-form-item label="选题">
      <el-input v-model="topicForm.title" placeholder="选题标题（必填）" maxlength="200" show-word-limit></el-input>
    </el-form-item>
    <el-form-item label="角度">
      <el-input v-model="topicForm.angle" type="textarea" :rows="3"
                placeholder="从什么角度写这条内容，避免与历史选题重复"></el-input>
    </el-form-item>
    <el-form-item label="来源追溯">
      <el-input :model-value="topicFinalAngle" type="textarea" :rows="3" readonly></el-input>
      <div class="gap-note">后端选题表暂无来源字段，来源链接/线索号会写入「角度」末尾，创建后可在选题池按「来源线索 #{{ topicSource && topicSource.id }}」检索追溯。</div>
    </el-form-item>
  </el-form>

  <el-checkbox v-if="convertedTopics.length" v-model="topicDupConfirm">已了解重复，仍要创建新选题</el-checkbox>
  <div v-if="topicCreated" class="alert-strip ok mt10">
    已创建选题{{ topicCreated.id ? ' #' + topicCreated.id : '' }}「{{ topicCreated.title }}」，来源信息已保留。
    <el-button size="small" text type="primary" @click="goTopics">去选题池查看</el-button>
  </div>

  <template #footer>
    <el-button @click="topicDlg = false">{{ topicCreated ? '关闭' : '取消' }}</el-button>
    <el-button v-if="!topicCreated" type="primary" :loading="topicSaving" @click="saveTopic">创建选题</el-button>
  </template>
</el-dialog>

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
