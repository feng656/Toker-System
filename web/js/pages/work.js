/**
 * P0 工作台：左侧内容池 + 右侧平台通道（拖动投放）。
 *
 * 主链路（运营日常）：左侧看今日内容卡 → 拖到右侧平台 tab → 自动复制该平台格式文案
 * 并填充右栏 composer → 微调 → 复制文案 / 打开平台后台 → 人工发布 → 回填链接并标记已发。
 *
 * 约束：
 *  - 拖动只做「复制 + 填充」，不直接发布（沿用《06-系统框架V0.1》2.2）；
 *  - 「沙盒发布」仅在内容版本已填充、同平台账号已连接且版本可发布时启用；
 *    执行只上传与填稿并留截图，真实发布必须人工确认；
 *  - 「标记已发」必须回填发布链接（延续「空链接不计入发布量」硬门槛）；
 *  - 素材不足不阻塞工作台，给「去素材库补充 / 先用文字版」入口。
 */
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from '../core/vue.js';
import { contentApi } from '../api/content.js';
import { platformApi } from '../api/platform.js';
import { phase2Api } from '../api/phase2.js';
import { dashboardApi } from '../api/business.js';
import { materialApi } from '../api/library.js';
import { notify, errorMessage } from '../core/ui.js';
import {
  platformName, copyText, composeCopyText, PLATFORM_HOME, bizLineClass, bizLineName, validatePublishUrl,
} from '../core/format.js';
import {
  CHANNELS, CHANNEL_MAP, channelName, emptyDrafts, fillDraft, buildCopy,
} from '../core/platforms.js';
import { isAdmin } from '../core/store.js';
import PlatformAccounts from '../components/platform-accounts.js';

const EP = () => window.ElementPlus;

export default {
  name: 'PageWork',
  components: { PlatformAccounts },
  setup() {
    /* ---------------- 内容池 ---------------- */
    const items = ref([]);
    const loading = ref(false);
    const error = ref('');
    const busy = reactive({});

    /* ---------------- 素材覆盖 ---------------- */
    const materials = ref([]);
    const materialError = ref('');

    /* ---------------- 右侧数据速览 / 平台登录 ---------------- */
    const funnel = reactive({ published: 0, views: 0, interactions: 0, leads: 0, high_intent: 0 });
    const platStatus = ref([]);
    const platMode = reactive({});
    const selPlatform = ref('gzh');
    const brImg = ref('');
    const brLogged = ref(false);
    const brLoading = ref(false);
    const brError = ref('');

    /* ---------------- 平台通道与 composer ---------------- */
    const active = ref('douyin');
    const drafts = reactive(emptyDrafts());
    const dragOver = ref('');
    const dragging = ref(null);
    const textOnly = ref(false);
    const assigned = reactive({}); // variantId → 通道 key（卡片显示「已复制到 XX」）
    const platformAccounts = ref(null);

    function openAddPlatform() {
      platformAccounts.value?.openAdd();
    }

    let timer = null;

    /* ---------------- 数据加载 ---------------- */
    async function loadAll() {
      loading.value = true;
      error.value = '';
      try {
        const [pending, todo, acc, fun] = await Promise.all([
          contentApi.pending(),
          contentApi.todoToday(),
          platformApi.status(),
          dashboardApi.funnel(),
        ]);
        const todoPending = (todo.pending || []).filter((x) => x.confirm_status !== 'pending' && !x.published_url);
        items.value = [...pending, ...todoPending];
        platStatus.value = acc || [];
        (acc || []).forEach((a) => { platMode[a.platform] = a.mode; });
        Object.assign(funnel, fun || {});
      } catch (e) {
        error.value = errorMessage(e);
        items.value = [];
      } finally {
        loading.value = false;
      }
    }

    /** 素材覆盖统计：失败不阻塞工作台 */
    async function loadMaterials() {
      materialError.value = '';
      try {
        const list = await materialApi.list();
        materials.value = list || [];
      } catch (e) {
        materials.value = [];
        materialError.value = errorMessage(e);
      }
    }

    const coverage = computed(() => {
      const c = { public: 0, masked: 0, internal: 0, total: 0 };
      (materials.value || []).forEach((m) => {
        const k = m.publicity || 'internal';
        if (c[k] === undefined) c[k] = 0;
        c[k] += 1;
        c.total += 1;
      });
      return c;
    });

    const materialEmpty = computed(() => coverage.value.total === 0);

    /* ---------------- 二期：平台工作空间（R2/R6 扫码登录 + 沙盒发布） ---------------- */
    const wsJobs = ref([]);
    const wsAccounts = ref([]);
    const wsLoading = ref(false);
    const wsError = ref('');
    const jobHighlight = ref(0);
    const jobStatusName = (s) => ({ queued: '排队中', running: '执行中', awaiting_confirmation: '待人工确认', succeeded: '已发布', failed: '失败', cancelled: '已取消' }[s] || s);
    const jobStatusTag = (s) => ({ queued: 'info', running: 'primary', awaiting_confirmation: 'warning', succeeded: 'success', failed: 'danger', cancelled: 'info' }[s] || 'info');
    const accountStatusName = (s) => ({ connected: '已连接', awaiting_scan: '待扫码', expired: '登录已过期', disconnected: '未登录' }[s] || s);

    async function loadWorkspace() {
      wsLoading.value = true;
      wsError.value = '';
      try {
        const ov = await phase2Api.wsOverview();
        wsJobs.value = ov.jobs || [];
        wsAccounts.value = ov.accounts || [];
      } catch (e) {
        wsError.value = errorMessage(e);
      } finally {
        wsLoading.value = false;
      }
    }

    /** 创建任务后把视线带到「沙盒发布任务」卡片，并短暂高亮新任务 */
    function scrollToJobs(jobId = 0) {
      const el = document.getElementById('ws-jobs-card');
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (jobId) {
        jobHighlight.value = jobId;
        window.setTimeout(() => { if (jobHighlight.value === jobId) jobHighlight.value = 0; }, 4000);
      }
    }

    async function jobRun(j) {
      try { await phase2Api.publishJobRun(j.id); notify.ok('任务已提交沙盒执行'); await loadWorkspace(); }
      catch (e) { notify.err(errorMessage(e)); }
    }

    async function jobConfirm(j) {
      try { await phase2Api.publishJobConfirm(j.id); notify.ok('已确认，继续发布流程'); await loadWorkspace(); }
      catch (e) { notify.err(errorMessage(e)); }
    }

    async function jobCancel(j) {
      try { await phase2Api.publishJobCancel(j.id); notify.info('任务已取消'); await loadWorkspace(); }
      catch (e) { notify.err(errorMessage(e)); }
    }

    /* ---------------- 平台登录（浏览器代理，沿用原工作台能力） ---------------- */
    async function openBrowser() {
      brLoading.value = true;
      brError.value = '';
      brImg.value = '';
      brLogged.value = false;
      try {
        const d = await platformApi.browserOpen(selPlatform.value);
        if (d && d.error) {
          brError.value = `平台窗口加载失败：${d.error}`;
        } else {
          brImg.value = (d && d.img) || '';
          brLogged.value = !!(d && d.logged_in);
        }
      } catch (e) {
        brError.value = errorMessage(e);
      } finally {
        brLoading.value = false;
      }
    }

    async function refreshShot() {
      try {
        const d = await platformApi.browserShot(selPlatform.value);
        if (d && d.img) brImg.value = d.img;
        brLogged.value = !!(d && d.logged_in);
      } catch (e) { /* 轮询失败静默，等下一次 */ }
    }

    /* ---------------- 投放（拖动 / 移动端下拉） ---------------- */
    function onDragStart(v, ev) {
      dragging.value = v;
      if (ev && ev.dataTransfer) {
        ev.dataTransfer.effectAllowed = 'copy';
        try { ev.dataTransfer.setData('text/plain', String(v.id)); } catch (e) { /* 忽略 */ }
      }
    }

    function onDragEnd() {
      dragging.value = null;
      dragOver.value = '';
    }

    function onDragOver(key) {
      if (dragging.value) dragOver.value = key;
    }

    function onDragOut(key) {
      if (dragOver.value === key) dragOver.value = '';
    }

    function onDrop(key, ev) {
      if (ev && ev.dataTransfer) {
        try { ev.preventDefault(); } catch (e) { /* 忽略 */ }
      }
      dragOver.value = '';
      const raw = ev && ev.dataTransfer ? ev.dataTransfer.getData('text/plain') : '';
      let variant = dragging.value;
      if (!variant && raw) variant = items.value.find((x) => String(x.id) === String(raw));
      if (!variant) {
        notify.warn('没有识别到要投放的内容，请从左侧内容池拖动');
        return;
      }
      assign(key, variant);
    }

    /** 移动端「复制到…」下拉 */
    function onPick(key, variant) {
      assign(key, variant);
    }

    /** 跨平台投放确认（内容版本平台与目标通道不一致时提示） */
    function needConfirm(key, variant) {
      if (!variant.platform) return false;
      if (variant.platform === key) return false;
      // 闲鱼与朋友圈/视频号没有一一对应关系，同样需要提示
      return true;
    }

    async function assign(key, variant) {
      const channel = CHANNEL_MAP[key];
      if (!channel) return;
      if (needConfirm(key, variant)) {
        const from = platformName(variant.platform);
        try {
          await EP().ElMessageBox.confirm(
            `这是「${from}」版本，拖到「${channel.name}」会按${channel.name}格式重排（标题/正文/话题/媒体字段不同）。是否继续？`,
            '平台不一致，确认投放？',
            { confirmButtonText: '继续投放', cancelButtonText: '取消', type: 'warning' },
          );
        } catch (e) {
          notify.info('已取消投放');
          return;
        }
      }
      const draft = fillDraft(channel, variant);
      if (textOnly.value) {
        channel.fields.forEach((f) => { if (f.type === 'media') draft[f.key] = ''; });
        draft.textOnly = true;
      }
      draft.sourceVariant = variant;
      drafts[key] = draft;
      active.value = key;
      assigned[variant.id] = key;
      const ok = await copyText(buildCopy(channel, draft));
      notify.ok(ok
        ? `${channel.name}格式文案已复制，右侧 composer 已填充，可直接微调后发布`
        : `已填充${channel.name} composer；复制失败，请手动选中文案复制`);
    }

    /** 手动切换到某个通道（tab 点击） */
    function switchChannel(key) {
      active.value = key;
    }

    /* ---------------- composer 操作 ---------------- */
    const cur = computed(() => drafts[active.value] || {});
    const curChannel = computed(() => CHANNEL_MAP[active.value] || CHANNELS[0]);
    const curFields = computed(() => curChannel.value.fields);

    /* ---------------- 沙盒发布（工作台 composer，复用二期发布任务） ---------------- */
    const sandbox = reactive({
      open: false, loading: false, accounts: [], accountId: null, busy: false, error: '', job: null, variant: null,
    });

    /** 当前 composer 的来源版本；列表刷新后优先用最新数据，找不到时回退投放时的快照 */
    const curVariant = computed(() => {
      const id = cur.value.sourceId;
      if (!id) return null;
      return items.value.find((x) => x.id === id) || cur.value.sourceVariant || null;
    });

    const sandboxAccounts = computed(() => {
      const pid = sandbox.variant ? sandbox.variant.platform_id : null;
      return (sandbox.accounts || [])
        .filter((a) => !a.deleted_at && a.platform_id === pid)
        .sort((a, b) => (a.status === 'connected' ? 0 : 1) - (b.status === 'connected' ? 0 : 1));
    });

    const sandboxHasConnected = computed(() => sandboxAccounts.value.some((a) => a.status === 'connected'));

    const sandboxCanSubmit = computed(() => {
      const a = (sandbox.accounts || []).find((x) => x.id === sandbox.accountId);
      return !!(a && a.status === 'connected');
    });

    /** 非空即禁用；文案同时作为按钮 tooltip */
    const sandboxBlock = computed(() => {
      if (!cur.value.sourceId) return '先把左侧内容拖进来';
      const v = curVariant.value;
      if (!v) return '内容版本信息未加载，请点右上「刷新」后重试';
      if (cur.value.sourcePlatform && cur.value.sourcePlatform !== active.value) {
        return `跨平台改写的版本不能直接沙盒发布，请切回「${channelName(cur.value.sourcePlatform)}」通道`;
      }
      if (v.status !== 'pending' || v.confirm_status !== 'confirmed' || v.published_url) {
        return '该内容版本尚未审核确认或已发布，请先在内容管理完成审核';
      }
      if (v.compliance_ok === false) return '该内容命中合规红线，不能沙盒发布';
      const accounts = (wsAccounts.value || []).filter((a) => !a.deleted_at && a.platform_id === v.platform_id);
      if (!accounts.length) {
        return `当前平台还没有工作空间账号，请先在下方「平台账号」添加并扫码连接${curChannel.value.name}账号`;
      }
      if (!accounts.some((a) => a.status === 'connected')) {
        return `请先在工作台平台工作空间扫码连接${curChannel.value.name}账号`;
      }
      return '';
    });

    async function openSandboxPublish() {
      if (sandboxBlock.value) {
        notify.warn(sandboxBlock.value);
        return;
      }
      sandbox.open = true;
      sandbox.variant = curVariant.value;
      sandbox.loading = true;
      sandbox.error = '';
      sandbox.job = null;
      sandbox.accountId = null;
      try {
        // 打开弹窗时重新取账号，避免刚扫码连接后页面状态仍是旧的
        const list = await phase2Api.wsAccounts();
        wsAccounts.value = list || [];
        sandbox.accounts = list || [];
        const first = sandboxAccounts.value.find((a) => a.status === 'connected');
        sandbox.accountId = first ? first.id : null;
      } catch (e) {
        sandbox.error = '工作空间账号加载失败：' + errorMessage(e);
      } finally {
        sandbox.loading = false;
      }
    }

    function goConnectAccount() {
      sandbox.open = false;
      nextTick(() => {
        const card = document.querySelector('.platform-accounts');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }

    async function submitSandboxPublish() {
      const v = sandbox.variant || curVariant.value;
      const account = (sandbox.accounts || []).find((a) => a.id === sandbox.accountId);
      if (!v) { notify.err('当前 composer 没有内容版本，先从左侧拖一条内容进来'); return; }
      if (!account) { notify.err('请选择同平台的工作空间账号'); return; }
      if (account.status !== 'connected') {
        notify.err(`账号「${account.label}」当前未连接，请先完成扫码登录`);
        return;
      }
      sandbox.busy = true;
      sandbox.error = '';
      try {
        const job = await phase2Api.publishJob({
          request_key: `variant_${v.id}_${account.id}`,
          account_id: account.id,
          variant_id: v.id,
        });
        sandbox.job = job;
        sandbox.open = false;
        notify.ok(`沙盒发布任务 #${job.id} 已创建，已定位到下方「沙盒发布任务」`);
        await loadWorkspace();
        await nextTick();
        scrollToJobs(job.id);
      } catch (e) {
        sandbox.error = errorMessage(e);
        notify.err(sandbox.error);
      } finally {
        sandbox.busy = false;
      }
    }

    async function copyComposer() {
      const ok = await copyText(buildCopy(curChannel.value, cur.value));
      notify[ok ? 'ok' : 'err'](ok ? `${curChannel.value.name}文案已复制` : '复制失败，请手动选中文案复制');
    }

    function openBackend() {
      const home = curChannel.value.home || PLATFORM_HOME[active.value];
      if (!home) {
        notify.warn('该平台没有后台地址，请在平台官网发布');
        return;
      }
      window.open(home, '_blank');
      notify.info(`已打开${curChannel.value.name}后台，粘贴文案后发布`);
    }

    async function markPublished() {
      const id = cur.value.sourceId;
      if (!id) {
        notify.warn('当前 composer 还没有内容，先从左侧拖一条内容进来');
        return;
      }
      let url = '';
      try {
        const r = await EP().ElMessageBox.prompt(
          '粘贴发布后的链接。未回填链接不会计入已发布量（硬门槛），请填完整 http(s) 链接。',
          '标记已发',
          { confirmButtonText: '确认已发', cancelButtonText: '取消', inputPlaceholder: 'https://…' },
        );
        url = (r && r.value ? r.value : '').trim();
      } catch (e) {
        return; // 用户取消
      }
      const check = validatePublishUrl(url);
      if (!check.ok) {
        notify.err(check.message);
        return;
      }
      busy[id] = true;
      try {
        await contentApi.publish(id, url);
        const target = items.value.find((x) => x.id === id);
        if (target) {
          target.published_url = url;
          target.publish_status = 'published';
        }
        notify.ok('已标记已发并回填链接，该版本计入已发布');
        await loadAll();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[id] = false;
      }
    }

    /* ---------------- 内容池卡片操作（沿用原工作台） ---------------- */
    async function confirmPublish(v) {
      busy[v.id] = true;
      try {
        const d = await contentApi.confirm(v.id);
        const result = d && d.publish_result;
        if (result && result.ok) {
          v.publish_status = 'published';
          notify.ok('已发布 🎉');
        } else {
          const err = (result && result.err) || '发布失败';
          v.publish_status = 'failed';
          v.publish_error = err;
          await copyText(composeCopyText(v));
          notify.warn(`${err}；文案已复制，请到${platformName(v.platform)}后台粘贴发布`);
        }
      } catch (e) {
        v.publish_status = 'failed';
        v.publish_error = errorMessage(e);
        notify.err(errorMessage(e));
      } finally {
        busy[v.id] = false;
        await loadAll();
      }
    }

    async function reject(v) {
      try {
        await contentApi.confirmReject(v.id);
        notify.info('已驳回');
        await loadAll();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    /** 「先用文字版」：素材不足时的兜底，不阻塞工作台 */
    function useTextOnly() {
      textOnly.value = true;
      Object.keys(drafts).forEach((k) => {
        const ch = CHANNEL_MAP[k];
        ch.fields.forEach((f) => { if (f.type === 'media') drafts[k][f.key] = ''; });
        drafts[k].textOnly = true;
      });
      notify.info('已切换为纯文字版：媒体字段留空，其余流程照常');
    }

    /** 「去素材库补充」 */
    function gotoMaterials() {
      window.location.hash = '#/materials';
    }

    onMounted(async () => {
      await loadAll();
      await loadMaterials();
      loadWorkspace();
    });
    onUnmounted(() => { if (timer) window.clearInterval(timer); });

    const pendingCount = computed(() => items.value.filter((i) => i.confirm_status === 'pending').length);

    return {
      items, loading, error, busy, funnel, platStatus, platMode,
      selPlatform, brImg, brLogged, brLoading, brError,
      pendingCount, loadAll, openBrowser, confirmPublish, reject,
      platformName, bizLineClass, bizLineName,
      // 通道与 composer
      channels: CHANNELS, active, drafts, cur, curChannel, curFields, dragOver, dragging,
      assigned, textOnly, coverage, materials, materialError, materialEmpty,
      onDragStart, onDragEnd, onDragOver, onDragOut, onDrop, onPick,
      switchChannel, copyComposer, openBackend, markPublished, useTextOnly, gotoMaterials,
      channelName, platformAccounts, openAddPlatform,
      wsJobs, wsAccounts, wsLoading, wsError, loadWorkspace, jobRun, jobConfirm, jobCancel,
      jobStatusName, jobStatusTag, jobHighlight, accountStatusName,
      sandbox, sandboxAccounts, sandboxHasConnected, sandboxCanSubmit, sandboxBlock,
      openSandboxPublish, goConnectAccount, submitSandboxPublish,
      isAdmin,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">今日内容工作台</div>
    <div class="page-sub">左侧内容池 → 拖到右侧平台 tab → 自动复制该平台格式文案并填充 composer → 微调 → 沙盒发布（人工确认）/ 复制文案 / 打开平台后台人工发布 → 回填链接标记已发。拖动只复制不发布。</div>
  </div>
  <div class="row">
    <el-button size="small" @click="loadAll" :loading="loading">刷新</el-button>
  </div>
</div>

<div v-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="loadAll" style="margin-left:8px">重试</el-button>
</div>

<div v-if="loading" class="card">
  <el-skeleton :rows="5" animated />
</div>

<template v-else-if="!error">
  <div class="wk-wrap">
    <!-- ============ 左：内容池 ============ -->
    <div class="wk-pool">
      <div class="alert-strip info">
        待确认 {{ pendingCount }} 条 · 合计 {{ items.length }} 条未发布。
        拖动卡片到右侧平台 tab 即可投放（松手自动复制文案并填充 composer）。
      </div>

      <!-- 素材覆盖统计 -->
      <div class="card wk-cover">
        <div class="row" style="justify-content:space-between">
          <b>素材库覆盖</b>
          <span class="muted">可公开 {{ coverage.public }} 条 · 需脱敏 {{ coverage.masked }} 条 · 仅内部 {{ coverage.internal }} 条</span>
        </div>
        <div v-if="materialError" class="muted mt6">素材覆盖统计读取失败：{{ materialError }}（不影响投放）</div>
        <div v-else-if="materialEmpty" class="alert-strip warn mt10">
          素材库为空：内容卡暂无可用图片/视频，媒体字段会留空。
          <div class="row mt10">
            <el-button size="small" type="primary" @click="gotoMaterials">去素材库补充</el-button>
            <el-button size="small" @click="useTextOnly">先用文字版</el-button>
          </div>
        </div>
        <div v-else class="muted mt6">
          图片/视频仍需人工上传到平台后台；工作台只做文案与结构，缺图不阻塞投放。
        </div>
        <div class="row mt10">
          <el-button size="small" text type="primary" @click="gotoMaterials">去素材库补充</el-button>
          <el-button size="small" text @click="useTextOnly">先用文字版</el-button>
          <el-tag v-if="textOnly" size="small" type="warning">纯文字版已开启</el-tag>
        </div>
      </div>

      <!-- 内容卡 -->
      <div class="card wk-card" v-for="v in items" :key="v.id"
           :class="{dragging: dragging && dragging.id === v.id}"
           draggable="true"
           @dragstart="onDragStart(v, $event)"
           @dragend="onDragEnd">
        <div class="row">
          <span class="pf" :class="'pf-' + v.platform">{{ platformName(v.platform) }}</span>
          <span class="line-tag" :class="bizLineClass(v.biz_line)">{{ bizLineName(v.biz_line) }}</span>
          <b>{{ v.content_title }}</b>
          <span class="muted" v-if="v.quality_score">质量分 {{ v.quality_score }}</span>
          <el-tag v-if="v.publish_status === 'published'" size="small" type="success">已发布</el-tag>
          <el-tag v-else-if="v.publish_status === 'failed'" size="small" type="danger">发布失败</el-tag>
          <el-tag v-if="v.confirm_status === 'pending'" size="small" type="warning">待确认</el-tag>
          <el-tag v-if="assigned[v.id]" size="small" type="info">已复制到 {{ channelName(assigned[v.id]) }}</el-tag>
        </div>
        <div class="body-pre mt10">{{ v.body }}</div>
        <div v-if="v.hashtags" class="muted mt6">{{ v.hashtags }}</div>
        <div class="muted mt6">
          素材：{{ v.image_prompt || '素材不足，可先用文字版投放' }}
        </div>
        <div v-if="!v.compliance_ok" class="alert-strip error mt10">⚠ 命中合规红线：{{ v.compliance_hits }}，请修改后再发布（红线命中不可直接放行）。</div>
        <div v-if="v.publish_error" class="alert-strip warn mt10">发布失败：{{ v.publish_error }}</div>
        <div class="row mt14">
          <el-button v-if="v.confirm_status === 'pending'" size="small" type="success"
                     :loading="busy[v.id]" @click="confirmPublish(v)">确认发布</el-button>
          <el-button v-if="v.confirm_status === 'pending'" size="small" @click="reject(v)">驳回</el-button>
          <el-dropdown size="small" @command="(p) => onPick(p, v)">
            <el-button size="small">复制到…</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="c in channels" :key="c.key" :command="c.key">{{ c.name }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span class="muted tiny">桌面端可直接拖动卡片到右侧平台 tab</span>
        </div>
      </div>

      <div v-if="!items.length" class="card">
        <div class="state-box">
          <el-icon><i class="el-icon-document" /></el-icon>
          暂无待处理内容。生成入口在「今日待办」，或等每日 08:00 定时任务生成。
          <div class="row mt10" style="justify-content:center">
            <el-button size="small" type="primary" @click="gotoMaterials">去素材库补充</el-button>
            <el-button size="small" @click="useTextOnly">先用文字版</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 右：平台通道 ============ -->
    <div class="wk-channels">
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <b>平台通道</b>
          <span class="muted">拖到 tab 松手 = 复制文案 + 填充 composer</span>
        </div>

        <div class="wk-tabs">
          <div v-for="c in channels" :key="c.key"
               class="wk-tab"
               :class="{on: active === c.key, over: dragOver === c.key}"
               @click="switchChannel(c.key)"
               @dragover.prevent="onDragOver(c.key)"
               @dragleave="onDragOut(c.key)"
               @drop.prevent="onDrop(c.key, $event)">
            {{ c.name }}
            <span v-if="drafts[c.key] && drafts[c.key].sourceId" class="wk-tab-dot"></span>
          </div>
          <button v-if="isAdmin()" type="button" class="wk-tab wk-tab-add" title="添加平台账号"
                  aria-label="添加平台账号" @click="openAddPlatform">+</button>
        </div>

        <div class="wk-dropzone"
             :class="{over: dragOver === active}"
             @dragover.prevent="onDragOver(active)"
             @dragleave="onDragOut(active)"
             @drop.prevent="onDrop(active, $event)">
          <div class="wk-composer-head">
            <b>{{ curChannel.name }} composer</b>
            <el-tag size="small" v-if="cur.sourceId">已填充内容</el-tag>
            <el-tag size="small" type="warning" v-else>空（把左侧内容拖进来）</el-tag>
            <el-tag size="small" :type="platMode[active] === 'auto' ? 'success' : 'info'">
              {{ platMode[active] === 'auto' ? '可自动发布' : '需人工发布' }}
            </el-tag>
          </div>

          <div class="wk-fields">
            <div class="wk-field" v-for="f in curFields" :key="f.key">
              <label class="wk-label">{{ f.label }}</label>
              <el-input v-if="f.type === 'text'" v-model="cur[f.key]" :placeholder="f.placeholder" />
              <el-input v-else-if="f.type === 'textarea'" type="textarea" :rows="f.rows"
                        v-model="cur[f.key]" :placeholder="f.placeholder" />
              <el-select v-else-if="f.type === 'select'" v-model="cur[f.key]" style="width:100%">
                <el-option v-for="o in f.options" :key="o" :label="o" :value="o"></el-option>
              </el-select>
              <div v-else class="wk-media">
                <div class="muted">{{ f.hint }}</div>
                <div v-if="cur[f.key]" class="wk-media-note">{{ cur[f.key] }}</div>
                <div v-else class="wk-media-none">
                  {{ cur.textOnly ? '纯文字版：暂不带图/视频' : '暂无素材：投放前请在素材库补齐，或用「先用文字版」' }}
                </div>
                <el-button size="small" text type="primary" @click="gotoMaterials">去素材库补充</el-button>
              </div>
              <div v-if="f.note" class="muted tiny mt6">{{ f.note }}</div>
            </div>
          </div>

          <div class="row mt14 wk-actions">
            <el-button type="primary" size="small" @click="copyComposer">复制文案</el-button>
            <el-button size="small" @click="openBackend">打开{{ curChannel.name }}后台</el-button>
            <el-button size="small" @click="markPublished" :disabled="!cur.sourceId">标记已发</el-button>
            <el-tooltip :content="sandboxBlock || '提交到沙盒适配器：执行只上传视频并填稿留截图，需人工确认后才真正发布'" placement="top">
              <span><el-button size="small" type="primary" plain :disabled="!!sandboxBlock" @click="openSandboxPublish">沙盒发布</el-button></span>
            </el-tooltip>
          </div>
          <div class="gap-note">沙盒发布需先选已连接账号；任务创建后在下方「沙盒发布任务」执行、核对截图，再人工确认。标记已发需回填链接：未回填链接不计入「已发布」（硬门槛，不允许绕过）。</div>
        </div>
      </div>

      <platform-accounts ref="platformAccounts" @changed="loadWorkspace" />

      <div class="card" id="ws-jobs-card" v-if="wsJobs.length || wsError">
        <div class="row" style="justify-content:space-between">
          <b>沙盒发布任务</b>
          <el-button size="small" :loading="wsLoading" @click="loadWorkspace">刷新任务</el-button>
        </div>
        <div class="muted mt6">创建任务 → 执行上传填稿并截图 → 人工核对 → 确认继续 → 发布存证</div>
        <div v-if="wsError" class="alert-strip warn mt10" role="alert">{{ wsError }}</div>
        <div v-for="j in wsJobs.slice(0, 8)" :key="j.id" class="row mt10"
             :style="jobHighlight === j.id ? 'background:#f0f9eb;border-radius:6px' : ''"
             style="justify-content:space-between;border-top:1px dashed #ebeef5;padding-top:8px">
          <div class="row">
            <el-tag size="small" :type="jobStatusTag(j.status)">{{ jobStatusName(j.status) }}</el-tag>
            <span class="muted">任务 #{{ j.id }} · 内容版本 {{ j.variant_id }}</span>
            <span v-if="j.error" class="muted tiny">（{{ j.error }}）</span>
          </div>
          <div class="row">
            <el-button v-if="j.status === 'queued'" size="small" text type="primary" @click="jobRun(j)">执行</el-button>
            <el-button v-if="j.status === 'awaiting_confirmation'" size="small" text type="success" @click="jobConfirm(j)">确认继续</el-button>
            <el-button v-if="['queued','failed','awaiting_confirmation'].indexOf(j.status) >= 0" size="small" text type="danger" @click="jobCancel(j)">取消</el-button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="row" style="justify-content:space-between"><b>数据速览</b></div>
        <div class="grid3 mt10" style="grid-template-columns:repeat(2,1fr)">
          <div style="text-align:center"><div style="font-size:22px;font-weight:700">{{ funnel.published }}</div><div class="muted">已发布</div></div>
          <div style="text-align:center"><div style="font-size:22px;font-weight:700">{{ funnel.views }}</div><div class="muted">总曝光</div></div>
          <div style="text-align:center"><div style="font-size:22px;font-weight:700">{{ funnel.leads }}</div><div class="muted">线索</div></div>
          <div style="text-align:center"><div style="font-size:22px;font-weight:700;color:#f56c6c">{{ funnel.high_intent }}</div><div class="muted">高意向</div></div>
        </div>
      </div>

      <div class="card">
        <div class="row" style="justify-content:space-between"><b>平台发布模式</b></div>
        <div class="tag-row mt10">
          <el-tag v-for="p in platStatus" :key="p.platform" size="small"
                  :type="p.mode === 'auto' ? 'success' : 'info'">
            {{ platformName(p.platform) }}：{{ p.mode === 'auto' ? '可自动发布' : '需人工发布' }}
          </el-tag>
        </div>
      </div>
    </div>
  </div>

</template>

<el-dialog v-model="sandbox.open" title="沙盒发布" width="600px" :close-on-click-modal="false">
  <div v-if="sandbox.variant" class="mb10">
    <div class="muted">内容版本</div>
    <b>#{{ sandbox.variant.id }} · {{ platformName(sandbox.variant.platform) }} · r{{ sandbox.variant.revision }}</b>
    <div class="muted mt6">标题：{{ sandbox.variant.cover_text || sandbox.variant.content_title || '（无）' }}</div>
  </div>
  <div v-if="sandbox.error" class="alert-strip error mt10">{{ sandbox.error }}</div>
  <div v-if="sandbox.loading" class="card"><el-skeleton :rows="2" animated /></div>
  <div v-else-if="!sandboxAccounts.length" class="alert-strip warn">
    当前平台还没有工作空间账号。请先在下方「平台账号」添加并扫码连接{{ curChannel.name }}账号。
    <div class="mt10"><el-button size="small" @click="goConnectAccount">去添加 / 连接账号</el-button></div>
  </div>
  <div v-else-if="!sandboxHasConnected" class="alert-strip warn">
    当前平台的账号均未连接（{{ sandboxAccounts.map((a) => a.label + '：' + accountStatusName(a.status)).join('；') }}）。
    请先完成扫码登录，再发起沙盒发布。
    <div class="mt10"><el-button size="small" @click="goConnectAccount">去平台账号扫码连接</el-button></div>
  </div>
  <template v-else>
    <div class="muted mt6">选择已连接的同平台账号（任务提交到沙盒适配器，步骤与截图全程留痕）</div>
    <el-select v-model="sandbox.accountId" style="width:100%" placeholder="选择工作空间账号">
      <el-option v-for="a in sandboxAccounts" :key="a.id"
                 :label="a.label + '（' + accountStatusName(a.status) + '）'"
                 :value="a.id" :disabled="a.status !== 'connected'"></el-option>
    </el-select>
    <div class="gap-note mt10">
      幂等键：variant_{{ sandbox.variant.id }}_{{ sandbox.accountId || '账号' }}；重复提交不会重复建任务。
      任务使用该内容版本已审核的文案，composer 里的临时修改不会同步；需改稿请先在内容管理保存新版本。
      创建后到「沙盒发布任务」点「执行」只做上传和填稿并截图，确认继续前不会真正发布。
    </div>
  </template>
  <template #footer>
    <el-button @click="sandbox.open = false">关闭</el-button>
    <el-button v-if="!sandbox.loading && sandboxHasConnected" type="primary"
               :loading="sandbox.busy" :disabled="!sandboxCanSubmit || sandbox.busy"
               @click="submitSandboxPublish">创建发布任务</el-button>
  </template>
</el-dialog>
`,
};
