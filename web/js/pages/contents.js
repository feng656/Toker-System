/**
 * 内容管理（二期 R4）：
 *  - 多维筛选：平台、内容状态、版本状态、排期范围、质量分、合规、业务线、关键词；URL 同步
 *  - 批量审批：多选、整批预检、逐项结果；后端批量接口未就绪时走逐条兼容模式
 *  - 版本对比：同一内容/平台 revision 并排 diff、时间线、驳回理由
 *  - 待办联动：今日/明日待发数量，点击跳到筛选后的列表
 *  - 草稿箱：后端 POST/PUT /contents 未上线，本期不提供死入口（见执行报告）
 */
import { ref, reactive, computed, onMounted, onUnmounted, watch } from '../core/vue.js';
import { contentApi } from '../api/content.js';
import { videoApi } from '../api/video.js';
import { phase2Api } from '../api/phase2.js';
import { notify, errorMessage } from '../core/ui.js';
import {
  platformName, bizLineClass, bizLineName, contentStatusName, variantStatusName,
  confirmStatusName, publishStatusName, fmtDate, fmtDateTime, todayStr,
} from '../core/format.js';
import { PLATFORM_META } from '../core/status.js';
import { sideBySide, inlineDiff } from '../core/diff.js';
import { canWriteContent } from '../core/store.js';

const QUALITY_OPTIONS = [
  { value: '', label: '不限质量分' },
  { value: '70', label: '≥ 70' },
  { value: '85', label: '≥ 85' },
];

const platformFilterOptions = PLATFORM_META
  .slice()
  .sort((a, b) => a.sort - b.sort)
  .map((p) => ({ value: p.code, label: p.template ? `${p.name}（历史）` : p.name }));

function tomorrowStr() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function variantTagType(status) {
  if (status === 'blocked') return 'danger';
  if (status === 'pending') return 'warning';
  if (status === 'published') return 'success';
  return 'info';
}

function confirmTagType(s) {
  if (s === 'rejected') return 'danger';
  if (s === 'confirmed') return 'success';
  if (s === 'pending') return 'warning';
  return 'info';
}

function publishTagType(s) {
  if (s === 'failed') return 'danger';
  if (s === 'published') return 'success';
  return 'info';
}

export default {
  name: 'PageContents',
  setup() {
    const contents = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);
    const includeHistory = ref(false);

    const filter = reactive({
      platform: '',
      status: '',
      variant_status: '',
      biz_line: '',
      keyword: '',
      scheduled_from: '',
      scheduled_to: '',
      quality_min: '',
      compliance: '',
      confirm_status: '',
      todoOnly: false,
    });

    const openMap = reactive({});
    const draft = reactive({});
    const busy = reactive({});
    const selected = reactive({});

    const rejectMode = reactive({});
    const rejectNote = reactive({});

    const todo = reactive({
      today: { date: todayStr(), count: 0 },
      tomorrow: { date: tomorrowStr(), count: 0 },
      error: '',
    });

    const batch = reactive({
      open: false, running: false, error: '', summary: '', mode: '', title: '批量审批结果', results: [],
    });
    const batchRejectOpen = ref(false);
    const batchRejectReason = ref('');
    const batchRejectError = ref('');

    const cmp = reactive({
      open: false, loading: false, error: '', contentTitle: '', platform: '',
      variants: [], leftId: null, rightId: null,
    });

    /* ---------------- 视频生成（平台 /video/*） ---------------- */
    const video = reactive({
      open: false, configured: null, status: null, submitting: false, error: '',
      variantId: null, title: '', platform: '', taskId: null, task: null,
      polling: false, blobUrl: '', modelNote: '',
    });
    let videoTimer = null;
    let videoPollToken = 0;

    function stopVideoPoll() {
      videoPollToken += 1;
      video.polling = false;
      if (videoTimer) { window.clearTimeout(videoTimer); videoTimer = null; }
    }

    function resetVideoUrl() {
      if (video.blobUrl) { URL.revokeObjectURL(video.blobUrl); video.blobUrl = ''; }
    }

    async function openVideo(v) {
      stopVideoPoll();
      resetVideoUrl();
      Object.assign(video, {
        open: true, error: '', submitting: false, variantId: v.id, title: v.cover_text || '未命名内容',
        platform: v.platform, taskId: null, task: null, modelNote: '',
      });
      if (video.status === null) {
        try { video.status = await videoApi.status(); } catch (e) { video.status = { configured: false }; }
      }
      video.configured = !!(video.status && video.status.configured);
      if (video.configured) {
        const s = video.status;
        video.modelNote = `${s.model} · ${s.resolution} · ${s.aspect_ratio} · ${s.duration_sec} 秒`;
      }
    }

    async function startVideo() {
      if (!video.configured) return;
      video.submitting = true;
      video.error = '';
      try {
        const r = await videoApi.generate({ variant_id: video.variantId });
        video.taskId = r.task_id;
        video.task = { status: r.status };
        watchVideo(r.task_id);
      } catch (e) {
        video.error = errorMessage(e);
      } finally {
        video.submitting = false;
      }
    }

    async function watchVideo(taskId) {
      const token = ++videoPollToken;
      video.polling = true;
      try {
        for (;;) {
          if (token !== videoPollToken) return;
          const task = await videoApi.task(taskId);
          if (token !== videoPollToken) return;
          video.task = task;
          if (task.status === 'succeeded') {
            await loadVideoBlob(taskId, token);
            return;
          }
          if (task.status === 'failed') {
            video.error = task.error || '视频生成失败，可稍后重试';
            return;
          }
          await new Promise((resolve) => { videoTimer = window.setTimeout(resolve, 5000); });
        }
      } catch (e) {
        if (token === videoPollToken) video.error = errorMessage(e);
      } finally {
        if (token === videoPollToken) video.polling = false;
      }
    }

    async function loadVideoBlob(taskId, token) {
      try {
        const res = await videoApi.file(taskId);
        const blob = await res.blob();
        if (token !== videoPollToken) return;
        resetVideoUrl();
        video.blobUrl = URL.createObjectURL(blob);
      } catch (e) {
        if (token === videoPollToken) video.error = '成片已生成，但预览加载失败：' + errorMessage(e);
      }
    }

    function closeVideo() {
      stopVideoPoll();
      resetVideoUrl();
      video.open = false;
    }

    /* ---------------- 沙盒发布（R2 闭环） ---------------- */
    const publish = reactive({
      open: false, loadingAccounts: false, accounts: [], busy: false, error: '',
      variant: null, accountId: null, job: null,
    });

    function publishEligible(v) {
      return !!(v && v.is_current && v.status === 'pending' && v.confirm_status === 'confirmed'
        && v.compliance_ok && !v.published_url);
    }

    const publishAccounts = computed(() => {
      if (!publish.variant) return [];
      return (publish.accounts || [])
        .filter((a) => !a.deleted_at && a.platform_id === publish.variant.platform_id)
        .sort((a, b) => (a.status === 'connected' ? 0 : 1) - (b.status === 'connected' ? 0 : 1));
    });

    const publishHasConnected = computed(() => publishAccounts.value.some((a) => a.status === 'connected'));

    const publishCanSubmit = computed(() => {
      const a = (publish.accounts || []).find((x) => x.id === publish.accountId);
      return !!(a && a.status === 'connected');
    });

    async function loadWsAccounts() {
      publish.loadingAccounts = true;
      publish.error = '';
      try {
        publish.accounts = (await phase2Api.wsAccounts()) || [];
      } catch (e) {
        publish.accounts = [];
        publish.error = '工作空间账号加载失败：' + errorMessage(e);
      } finally {
        publish.loadingAccounts = false;
      }
    }

    async function openPublish(v) {
      publish.variant = v;
      publish.job = null;
      publish.accountId = null;
      publish.open = true;
      await loadWsAccounts();
      const first = publishAccounts.value.find((a) => a.status === 'connected');
      publish.accountId = first ? first.id : null;
    }

    function goWorkbench() {
      publish.open = false;
      window.location.hash = '#/work';
    }

    async function submitPublish() {
      const v = publish.variant;
      const account = (publish.accounts || []).find((a) => a.id === publish.accountId);
      if (!v) return;
      if (!account) { notify.err('请选择同平台的工作空间账号'); return; }
      if (account.status !== 'connected') {
        notify.err(`账号「${account.label}」当前状态为「${account.status}」，请先在工作台完成扫码登录`);
        return;
      }
      publish.busy = true;
      publish.error = '';
      try {
        const job = await phase2Api.publishJob({
          request_key: `variant_${v.id}_${account.id}`,
          account_id: account.id,
          variant_id: v.id,
        });
        publish.job = job;
        notify.ok(`发布任务 #${job.id} 已创建，请到工作台查看任务进度`);
        await load();
      } catch (e) {
        publish.error = errorMessage(e);
        notify.err(publish.error);
      } finally {
        publish.busy = false;
      }
    }

    /* ---------------- 数据加载 ---------------- */

    function ensureDraft(v) {
      if (!draft[v.id]) {
        draft[v.id] = {
          body: v.body || '',
          cover_text: v.cover_text || '',
          hashtags: v.hashtags || '',
        };
      }
    }

    function buildQuery() {
      // 一期 /contents 只认 status / scheduled / limit；其余维度在前端本地筛，
      // 避免「刷新后 URL 带 status，用户再清空状态却仍只看到服务端过滤结果」。
      // 数据量大时由后端按 M-R4-02 补齐平台/排期范围/质量分/合规等参数。
      return { limit: 500 };
    }

    /* ---- 二期 R4：版本筛选 / 批量审核 / 草稿箱 ---- */
    const tab = ref('pack');
    const pfList = ref([]);
    const vq = reactive({ platform_id: '', status: '', confirm_status: '', scheduled_from: '', scheduled_to: '', min_score: 0, max_score: 100, compliance_ok: '' });
    const vlist = ref([]);
    const vtotal = ref(0);
    const vloading = ref(false);
    const vselected = ref([]);
    const bulkBusy = ref(false);
    const draftDlg = ref(false);
    const draftSaving = ref(false);
    const draftForm = reactive({ title: '', platform_id: null, body: '', biz_line: 'project', scheduled_date: '' });

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        const list = await contentApi.list(buildQuery());
        contents.value = list || [];
        (list || []).forEach((c) => {
          (c.variants || []).forEach((v) => ensureDraft(v));
        });
        clearSelection();
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
        contents.value = [];
      } finally {
        loading.value = false;
      }
    }

    async function loadTodo() {
      todo.error = '';
      const results = await Promise.allSettled([
        contentApi.todoToday(todo.today.date),
        contentApi.todoToday(todo.tomorrow.date),
      ]);
      const pick = (r) => {
        if (r.status !== 'fulfilled') return null;
        return (r.value && r.value.pending ? r.value.pending.length : 0);
      };
      const a = pick(results[0]);
      const b = pick(results[1]);
      if (a === null && b === null) {
        todo.error = '待办数量加载失败，刷新重试';
        return;
      }
      todo.today.count = a || 0;
      todo.tomorrow.count = b || 0;
    }

    /* ---------------- 本地筛选 ---------------- */

    function matchContent(c) {
      if (filter.status && c.status !== filter.status) return false;
      if (filter.biz_line && c.biz_line !== filter.biz_line) return false;
      const kw = filter.keyword.trim();
      if (kw) {
        const hay = `${c.title || ''} ${c.topic || ''}`;
        if (hay.indexOf(kw) < 0) return false;
      }
      const d = c.scheduled_date || '';
      if (filter.scheduled_from && d && d < filter.scheduled_from) return false;
      if (filter.scheduled_to && d && d > filter.scheduled_to) return false;
      if ((filter.scheduled_from || filter.scheduled_to) && !d) return false;
      return true;
    }

    function matchVariant(v) {
      if (!includeHistory.value && !v.is_current) return false;
      if (filter.platform && v.platform !== filter.platform) return false;
      if (filter.variant_status && v.status !== filter.variant_status) return false;
      if (filter.confirm_status && v.confirm_status !== filter.confirm_status) return false;
      if (filter.quality_min && Number(v.quality_score || 0) < Number(filter.quality_min)) return false;
      if (filter.compliance === 'ok' && v.compliance_ok !== true) return false;
      if (filter.compliance === 'fail' && v.compliance_ok !== false) return false;
      if (filter.todoOnly) {
        if (v.status !== 'pending' || v.confirm_status !== 'confirmed' || v.published_url) return false;
      }
      return true;
    }

    const filteredContents = computed(() => contents.value
      .filter(matchContent)
      .map((c) => ({ ...c, visibleVariants: (c.variants || []).filter(matchVariant) }))
      .filter((c) => c.visibleVariants.length > 0));

    const visibleCount = computed(() => filteredContents.value
      .reduce((n, c) => n + c.visibleVariants.length, 0));

    const stats = computed(() => {
      let pending = 0;
      let blocked = 0;
      let qualitySum = 0;
      let qualityN = 0;
      contents.value.forEach((c) => {
        (c.variants || []).forEach((v) => {
          if (!v.is_current) return;
          if (v.status === 'pending' && v.confirm_status === 'pending') pending += 1;
          if (v.status === 'blocked') blocked += 1;
          if (v.quality_score) { qualitySum += Number(v.quality_score); qualityN += 1; }
        });
      });
      return {
        pending,
        blocked,
        avgQuality: qualityN ? Math.round(qualitySum / qualityN) : 0,
      };
    });

    const activeFilterCount = computed(() => {
      let n = 0;
      ['platform', 'status', 'variant_status', 'biz_line', 'keyword',
        'scheduled_from', 'scheduled_to', 'quality_min', 'compliance', 'confirm_status']
        .forEach((k) => { if (filter[k]) n += 1; });
      if (filter.todoOnly) n += 1;
      if (includeHistory.value) n += 1;
      return n;
    });

    function resetFilters() {
      Object.assign(filter, {
        platform: '', status: '', variant_status: '', biz_line: '', keyword: '',
        scheduled_from: '', scheduled_to: '', quality_min: '', compliance: '',
        confirm_status: '', todoOnly: false,
      });
      includeHistory.value = false;
    }

    function jumpTodo(which) {
      const d = which === 'today' ? todo.today.date : todo.tomorrow.date;
      // /todo/today 的语义是「排期 <= 查询日」，包含逾期；跳转条件必须与计数一致。
      Object.assign(filter, {
        platform: '', status: '', variant_status: '', biz_line: '', keyword: '',
        scheduled_from: '', scheduled_to: d, quality_min: '', compliance: '',
        confirm_status: '', todoOnly: true,
      });
      const el = document.getElementById('contents-list');
      if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /* ---------------- URL 同步 ---------------- */

    const FILTER_KEYS = [
      'platform', 'status', 'variant_status', 'biz_line', 'keyword',
      'scheduled_from', 'scheduled_to', 'quality_min', 'compliance', 'confirm_status',
    ];

    function readFiltersFromHash() {
      const raw = (window.location.hash || '').replace(/^#\/?/, '');
      const q = raw.indexOf('?');
      const params = new URLSearchParams(q >= 0 ? raw.slice(q + 1) : '');
      FILTER_KEYS.forEach((k) => { filter[k] = params.get(k) || ''; });
      filter.todoOnly = params.get('todo') === '1';
      includeHistory.value = params.get('history') === '1';
    }

    let syncTimer = null;
    function syncFiltersToHash() {
      if (syncTimer) window.clearTimeout(syncTimer);
      syncTimer = window.setTimeout(() => {
        const raw = (window.location.hash || '').replace(/^#\/?/, '');
        const q = raw.indexOf('?');
        const params = new URLSearchParams(q >= 0 ? raw.slice(q + 1) : '');
        FILTER_KEYS.forEach((k) => {
          if (filter[k]) params.set(k, filter[k]);
          else params.delete(k);
        });
        if (filter.todoOnly) params.set('todo', '1'); else params.delete('todo');
        if (includeHistory.value) params.set('history', '1'); else params.delete('history');
        const qs = params.toString();
        const base = (q >= 0 ? raw.slice(0, q) : raw) || 'contents';
        try {
          history.replaceState(null, '', `#/${base}${qs ? `?${qs}` : ''}`);
        } catch (e) { /* 忽略 */ }
      }, 250);
    }

    watch(filter, syncFiltersToHash, { deep: true });
    watch(includeHistory, syncFiltersToHash);

    /* ---------------- 选择与批量预检 ---------------- */

    const allVariants = computed(() => {
      const out = [];
      contents.value.forEach((c) => {
        (c.variants || []).forEach((v) => out.push({ content: c, variant: v }));
      });
      return out;
    });

    const visibleVariants = computed(() => {
      const out = [];
      filteredContents.value.forEach((c) => {
        c.visibleVariants.forEach((v) => out.push({ content: c, variant: v }));
      });
      return out;
    });

    const selectedList = computed(() => allVariants.value.filter(({ variant }) => selected[variant.id]));
    const selectedCount = computed(() => selectedList.value.length);
    const allSelected = computed(() => visibleVariants.value.length > 0
      && visibleVariants.value.every(({ variant }) => selected[variant.id]));

    function setSelected(id, value) {
      if (value) selected[id] = true;
      else delete selected[id];
    }

    function toggleSelectAll(value) {
      visibleVariants.value.forEach(({ variant }) => setSelected(variant.id, value));
    }

    function clearSelection() {
      Object.keys(selected).forEach((k) => { delete selected[k]; });
    }

    function precheckBatch(list) {
      const problems = [];
      list.forEach(({ content, variant }) => {
        const reasons = [];
        if (!variant.is_current) reasons.push('不是当前版本');
        if (variant.status === 'blocked') reasons.push('状态为 blocked（已拦截）');
        else if (variant.status !== 'pending') reasons.push(`状态为「${variantStatusName(variant.status)}」，不是待确认`);
        if (variant.confirm_status !== 'pending') reasons.push(`人工确认状态为「${confirmStatusName(variant.confirm_status)}」`);
        if (variant.compliance_ok === false) reasons.push(`命中合规红线：${variant.compliance_hits || '未标注具体词'}`);
        if (reasons.length) {
          problems.push({ content, variant, reasons });
        }
      });
      return problems;
    }

    function resultRow(item, ok, message) {
      return {
        variant_id: item.variant.id,
        content_title: item.content.title,
        revision: item.variant.revision,
        ok,
        message,
      };
    }

    function openBatchResults(title, summary, rows, mode) {
      batch.open = true;
      batch.error = '';
      batch.title = title || '批量审批结果';
      batch.summary = summary;
      batch.mode = mode || '';
      batch.results = rows;
    }

    async function runBatchApprove() {
      const list = selectedList.value;
      if (!list.length) { notify.warn('请先选择要审批的版本'); return; }
      const problems = precheckBatch(list);
      if (problems.length) {
        openBatchResults(
          '批量通过',
          `${problems.length} 个版本未通过预检，整批未提交`,
          problems.map((p) => resultRow(p, false, p.reasons.join('；'))),
          'precheck',
        );
        return;
      }

      batch.running = true;
      batch.open = true;
      batch.error = '';
      batch.title = '批量通过';
      batch.results = [];
      batch.summary = '正在提交…';
      const ids = list.map(({ variant }) => variant.id);
      const versions = {};
      list.forEach(({ variant }) => { versions[String(variant.id)] = variant.version; });

      try {
        const res = await contentApi.batchApprove({ variant_ids: ids, expected_versions: versions });
        const rows = (res.results || []).map((r) => {
          const item = list.find(({ variant }) => variant.id === r.variant_id) || list[0];
          return {
            variant_id: r.variant_id,
            content_title: item ? item.content.title : '',
            revision: item ? item.variant.revision : '',
            ok: !!r.ok,
            message: r.message || (r.ok ? '已通过' : (r.code || '失败')),
          };
        });
        const okCount = rows.filter((r) => r.ok).length;
        openBatchResults('批量通过', `已通过 ${okCount} / ${rows.length} 个版本`, rows, 'batch');
        notify.ok(`批量通过完成：${okCount} 个版本`);
        await refreshAfterBatch();
      } catch (e) {
        if (e && (e.status === 404 || e.status === 405)) {
          await fallbackBatchApprove(list);
        } else {
          batch.error = errorMessage(e);
          batch.summary = '批量通过失败';
        }
      } finally {
        batch.running = false;
      }
    }

    async function fallbackBatchApprove(list) {
      batch.mode = 'fallback';
      batch.summary = '后端批量接口未就绪，正在逐条调用旧接口…';
      const rows = [];
      for (const item of list) {
        try {
          const updated = await contentApi.approveVariant(item.variant.id, item.variant.version);
          rows.push(resultRow(item, true, `已通过 r${updated.revision || item.variant.revision}`));
        } catch (e) {
          rows.push(resultRow(item, false, errorMessage(e)));
        }
      }
      const okCount = rows.filter((r) => r.ok).length;
      openBatchResults(
        '批量通过（逐条兼容）',
        `${okCount} 成功 / ${rows.length - okCount} 失败；逐条模式可能部分写入，请核对列表`,
        rows,
        'fallback',
      );
      await refreshAfterBatch();
    }

    async function runBatchReject() {
      const list = selectedList.value;
      if (!list.length) { notify.warn('请先选择要驳回的版本'); return; }
      if (!batchRejectReason.value.trim()) {
        batchRejectError.value = '驳回必须填写理由，理由会保留在版本上并用于改进生成';
        return;
      }
      const problems = precheckBatch(list);
      if (problems.length) {
        batchRejectOpen.value = false;
        openBatchResults(
          '批量驳回',
          `${problems.length} 个版本未通过预检，整批未提交`,
          problems.map((p) => resultRow(p, false, p.reasons.join('；'))),
          'precheck',
        );
        return;
      }

      batchRejectError.value = '';
      batch.running = true;
      batch.open = true;
      batch.error = '';
      batch.title = '批量驳回';
      batch.results = [];
      batch.summary = '正在提交驳回…';
      const ids = list.map(({ variant }) => variant.id);
      const versions = {};
      list.forEach(({ variant }) => { versions[String(variant.id)] = variant.version; });

      try {
        const res = await contentApi.batchReject({
          variant_ids: ids,
          reason: batchRejectReason.value.trim(),
          expected_versions: versions,
        });
        const rows = (res.results || []).map((r) => {
          const item = list.find(({ variant }) => variant.id === r.variant_id) || list[0];
          return {
            variant_id: r.variant_id,
            content_title: item ? item.content.title : '',
            revision: item ? item.variant.revision : '',
            ok: !!r.ok,
            message: r.message || (r.ok ? '已驳回，等待生成新版本' : (r.code || '失败')),
          };
        });
        openBatchResults('批量驳回', `已驳回 ${rows.filter((r) => r.ok).length} / ${rows.length} 个版本`, rows, 'batch');
        batchRejectOpen.value = false;
        batchRejectReason.value = '';
        await refreshAfterBatch();
      } catch (e) {
        if (e && (e.status === 404 || e.status === 405)) {
          await fallbackBatchReject(list);
          batchRejectOpen.value = false;
          batchRejectReason.value = '';
        } else {
          batch.error = errorMessage(e);
          batch.summary = '批量驳回失败';
        }
      } finally {
        batch.running = false;
      }
    }

    async function fallbackBatchReject(list) {
      const reason = batchRejectReason.value.trim();
      batch.mode = 'fallback';
      batch.summary = '后端批量接口未就绪，正在逐条调用旧接口…';
      const rows = [];
      for (const item of list) {
        try {
          await contentApi.rejectVariant(item.variant.id, reason, item.variant.version);
          rows.push(resultRow(item, true, '已驳回，等待生成新版本'));
        } catch (e) {
          rows.push(resultRow(item, false, errorMessage(e)));
        }
      }
      const okCount = rows.filter((r) => r.ok).length;
      openBatchResults(
        '批量驳回（逐条兼容）',
        `${okCount} 成功 / ${rows.length - okCount} 失败；逐条模式可能部分写入，请核对列表`,
        rows,
        'fallback',
      );
      await refreshAfterBatch();
    }

    async function refreshAfterBatch() {
      clearSelection();
      await load();
      await loadTodo();
    }

    /* ---------------- 单版本操作 ---------------- */

    function toggle(c) {
      openMap[c.id] = !openMap[c.id];
    }

    async function saveVariant(v) {
      const d = draft[v.id];
      if (!d) return;
      busy[v.id] = true;
      try {
        const updated = await contentApi.updateVariant(v.id, {
          body: d.body,
          cover_text: d.cover_text,
          hashtags: d.hashtags,
        }, v.version);
        Object.assign(v, updated);
        draft[v.id] = {
          body: updated.body || '',
          cover_text: updated.cover_text || '',
          hashtags: updated.hashtags || '',
        };
        notify.ok(updated.compliance_ok
          ? '已保存，合规检查通过'
          : `已保存，但命中红线：${updated.compliance_hits || '未标注具体词'}`);
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[v.id] = false;
      }
    }

    async function approveOne(v) {
      busy[v.id] = true;
      try {
        const updated = await contentApi.approveVariant(v.id, v.version);
        Object.assign(v, updated);
        notify.ok('已通过');
        await loadTodo();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[v.id] = false;
      }
    }

    async function rejectOne(v) {
      const note = rejectNote[v.id] || '';
      if (!note.trim()) {
        notify.err('驳回必须填写理由，理由会保留在版本上并用于改进生成');
        return;
      }
      busy[v.id] = true;
      try {
        await contentApi.rejectVariant(v.id, note.trim(), v.version);
        notify.ok('已驳回并记录理由，等待生成新版本');
        rejectMode[v.id] = false;
        rejectNote[v.id] = '';
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[v.id] = false;
      }
    }

    async function reviewContent(c, action) {
      const note = rejectNote[`c${c.id}`] || '';
      if (action === 'reject' && !note.trim()) {
        notify.err('驳回必须填写理由');
        return;
      }
      busy[`c${c.id}`] = true;
      try {
        await contentApi.review(c.id, action, note);
        notify.ok(action === 'approve' ? '整包已通过（兼容入口）' : '整包已驳回（兼容入口）');
        rejectMode[`c${c.id}`] = false;
        rejectNote[`c${c.id}`] = '';
        await load();
        await loadTodo();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[`c${c.id}`] = false;
      }
    }

    /* ---------------- 版本对比 ---------------- */

    const cmpLeft = computed(() => cmp.variants.find((v) => v.id === cmp.leftId) || null);
    const cmpRight = computed(() => cmp.variants.find((v) => v.id === cmp.rightId) || null);
    const cmpSame = computed(() => !!(cmpLeft.value && cmpRight.value && cmpLeft.value.id === cmpRight.value.id));

    const cmpDiff = computed(() => {
      if (!cmpLeft.value || !cmpRight.value) return null;
      return {
        title: inlineDiff(cmpLeft.value.cover_text, cmpRight.value.cover_text),
        body: sideBySide(cmpLeft.value.body, cmpRight.value.body),
        hashtags: inlineDiff(cmpLeft.value.hashtags, cmpRight.value.hashtags),
      };
    });

    function versionLabel(v) {
      return `r${v.revision} · ${fmtDateTime(v.created_at)}${v.is_current ? ' · 当前' : ''}`;
    }

    async function openCompare(c, v) {
      Object.assign(cmp, {
        open: true, loading: true, error: '', contentTitle: c.title, platform: v.platform,
        variants: [], leftId: null, rightId: null,
      });
      try {
        const list = await contentApi.history(v.id);
        const sorted = (list || []).slice().sort((a, b) => a.revision - b.revision);
        cmp.variants = sorted;
        const current = sorted.find((x) => x.is_current) || sorted[sorted.length - 1];
        const idx = sorted.indexOf(current);
        const prev = idx > 0 ? sorted[idx - 1] : null;
        cmp.rightId = current ? current.id : null;
        cmp.leftId = prev ? prev.id : (sorted[0] ? sorted[0].id : null);
      } catch (e) {
        cmp.error = errorMessage(e);
      } finally {
        cmp.loading = false;
      }
    }

    /* ---------------- 生命周期 ---------------- */

    function onHashChange() {
      if (!(window.location.hash || '').startsWith('#/contents')) return;
      readFiltersFromHash();
    }

    onMounted(() => {
      readFiltersFromHash();
      load();
      loadTodo();
      loadPlatforms();
      loadWsAccounts();
      window.addEventListener('hashchange', onHashChange);
    });

    onUnmounted(() => {
      if (syncTimer) window.clearTimeout(syncTimer);
      stopVideoPoll();
      resetVideoUrl();
      window.removeEventListener('hashchange', onHashChange);
    });

    /* ---- 二期 R4 逻辑 ---- */
    async function loadPlatforms() {
      try { pfList.value = await phase2Api.platforms() || []; } catch (e) { pfList.value = []; }
    }

    async function loadVariants() {
      vloading.value = true;
      try {
        const q = { ...vq };
        if (q.compliance_ok === '') delete q.compliance_ok;
        const d = await phase2Api.variants(q);
        vlist.value = (d && d.items) || [];
        vtotal.value = (d && d.total) || 0;
      } catch (e) {
        notify.err(errorMessage(e));
        vlist.value = [];
        vtotal.value = 0;
      } finally {
        vloading.value = false;
      }
    }

    function applyVariantFilter() { loadVariants(); }

    async function bulkApprove() {
      const rows = vselected.value.map((id) => vlist.value.find((x) => x.id === id)).filter(Boolean);
      if (!rows.length) { notify.err('请先勾选要审核的版本'); return; }
      bulkBusy.value = true;
      try {
        const d = await phase2Api.bulkReview({
          variant_ids: rows.map((x) => x.id),
          action: 'approve',
          expected_versions: Object.fromEntries(rows.map((x) => [String(x.id), x.version])),
        });
        notify.ok(`批量通过 ${d.processed} 条`);
        vselected.value = [];
        await loadVariants();
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        bulkBusy.value = false;
      }
    }

    async function bulkReject() {
      const rows = vselected.value.map((id) => vlist.value.find((x) => x.id === id)).filter(Boolean);
      if (!rows.length) { notify.err('请先勾选要驳回的版本'); return; }
      let reason = '';
      try {
        const r = await window.ElementPlus.ElMessageBox.prompt(
          `将驳回 ${rows.length} 条版本。驳回必须填写理由（会保留在内容上并用于改进生成）。`,
          '批量驳回',
          { confirmButtonText: '确认驳回', cancelButtonText: '取消', inputPlaceholder: '驳回理由（必填）' },
        );
        reason = (r && r.value ? r.value : '').trim();
      } catch (e) {
        return; // 取消
      }
      if (!reason) { notify.err('驳回理由必填'); return; }
      bulkBusy.value = true;
      try {
        const d = await phase2Api.bulkReview({
          variant_ids: rows.map((x) => x.id),
          action: 'reject',
          reason,
          expected_versions: Object.fromEntries(rows.map((x) => [String(x.id), x.version])),
        });
        notify.ok(`已驳回 ${d.processed} 条，生成新版本后可重新审核`);
        vselected.value = [];
        await loadVariants();
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        bulkBusy.value = false;
      }
    }

    function openDraft() {
      Object.assign(draftForm, { title: '', platform_id: pfList.value.length ? pfList.value[0].id : null, body: '', biz_line: 'project', scheduled_date: '' });
      draftDlg.value = true;
    }

    async function saveDraft() {
      if (!draftForm.title.trim() || !draftForm.body.trim() || !draftForm.platform_id) {
        notify.err('标题、正文与平台必填'); return;
      }
      draftSaving.value = true;
      try {
        await phase2Api.createDraft({
          title: draftForm.title.trim(),
          platform_id: draftForm.platform_id,
          body: draftForm.body,
          biz_line: draftForm.biz_line,
          scheduled_date: draftForm.scheduled_date || null,
        });
        notify.ok('草稿已保存（状态：草稿，可在内容包视图继续编辑）');
        draftDlg.value = false;
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        draftSaving.value = false;
      }
    }

    const vStatusName = (s) => ({ draft: '草稿', pending: '待审核', approved: '已通过', rejected: '已驳回', blocked: '被拦截', published: '已发布' }[s] || s);

    return {
      contents, filteredContents, visibleVariants, loading, error, forbidden, filter, includeHistory,
      openMap, draft, busy, selected, rejectMode, rejectNote,
      todo, batch, batchRejectOpen, batchRejectReason, batchRejectError,
      cmp, cmpLeft, cmpRight, cmpSame, cmpDiff,
      video, openVideo, startVideo, closeVideo,
      stats, visibleCount, activeFilterCount, allSelected, selectedCount, selectedList,
      QUALITY_OPTIONS, platformFilterOptions,
      load, loadTodo, resetFilters, jumpTodo, toggle, saveVariant, approveOne, rejectOne,
      reviewContent, openCompare, versionLabel,
      setSelected, toggleSelectAll, clearSelection,
      runBatchApprove, runBatchReject, precheckBatch, resultRow,
      canWriteContent, platformName, bizLineClass, bizLineName, contentStatusName,
      variantStatusName, confirmStatusName, publishStatusName, fmtDate, fmtDateTime,
      variantTagType, confirmTagType, publishTagType,
      tab, pfList, vq, vlist, vtotal, vloading, vselected, bulkBusy,
      draftDlg, draftSaving, draftForm,
      publish, publishEligible, publishAccounts, publishHasConnected, publishCanSubmit,
      openPublish, submitPublish, goWorkbench,
      applyVariantFilter, bulkApprove, bulkReject, openDraft, saveDraft, vStatusName,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">内容管理</div>
    <div class="page-sub">筛选 → 勾选版本 → 批量审批；版本对比在本机计算 diff。blocked / 未质检版本不会被批量放行。</div>
  </div>
  <div class="row">
    <el-button size="small" @click="load" :loading="loading">刷新</el-button>
    <el-button v-if="canWriteContent" size="small" type="primary" @click="openDraft">+ 新建草稿</el-button>
  </div>
</div>

<el-tabs v-model="tab">
  <el-tab-pane label="内容包（按选题）" name="pack">
<div class="todo-cards">
  <div class="todo-card" :class="{ on: filter.todoOnly && !filter.scheduled_from && filter.scheduled_to === todo.today.date }" @click="jumpTodo('today')">
    <div class="n">{{ todo.today.count }}</div>
    <div class="l">今日待办</div>
    <div class="d">含逾期 · {{ todo.today.date }}</div>
  </div>
  <div class="todo-card" :class="{ on: filter.todoOnly && !filter.scheduled_from && filter.scheduled_to === todo.tomorrow.date }" @click="jumpTodo('tomorrow')">
    <div class="n">{{ todo.tomorrow.count }}</div>
    <div class="l">明日累计待办</div>
    <div class="d">含逾期 · {{ todo.tomorrow.date }}</div>
  </div>
  <div class="todo-card static">
    <div class="n">{{ stats.pending }}</div>
    <div class="l">待人工确认</div>
    <div class="d">当前加载</div>
  </div>
  <div class="todo-card static">
    <div class="n">{{ stats.blocked }}</div>
    <div class="l">已拦截</div>
    <div class="d">当前加载</div>
  </div>
  <div class="todo-card static">
    <div class="n">{{ stats.avgQuality || '-' }}</div>
    <div class="l">平均质量分</div>
    <div class="d">当前加载</div>
  </div>
</div>
<div v-if="todo.error" class="alert-strip warn">{{ todo.error }}</div>

<div class="card filter-card">
  <div class="toolbar">
    <el-select v-model="filter.platform" placeholder="全部平台" clearable size="small" style="width:135px">
      <el-option v-for="o in platformFilterOptions" :key="o.value" :label="o.label" :value="o.value" />
    </el-select>
    <el-select v-model="filter.status" placeholder="内容状态" clearable size="small" style="width:120px">
      <el-option label="待审核" value="draft" />
      <el-option label="已通过" value="approved" />
      <el-option label="已驳回" value="rejected" />
      <el-option label="已发布" value="published" />
      <el-option label="已归档" value="archived" />
    </el-select>
    <el-select v-model="filter.variant_status" placeholder="版本状态" clearable size="small" style="width:125px">
      <el-option label="草稿 / 待质检" value="draft" />
      <el-option label="已拦截" value="blocked" />
      <el-option label="待人工确认" value="pending" />
      <el-option label="已发布" value="published" />
    </el-select>
    <el-select v-model="filter.biz_line" placeholder="业务线" clearable size="small" style="width:110px">
      <el-option label="甲方线" value="project" />
      <el-option label="渠道线" value="channel" />
    </el-select>
    <el-date-picker v-model="filter.scheduled_from" type="date" value-format="YYYY-MM-DD" placeholder="排期起" size="small" style="width:125px" />
    <span class="muted">至</span>
    <el-date-picker v-model="filter.scheduled_to" type="date" value-format="YYYY-MM-DD" placeholder="排期止" size="small" style="width:125px" />
    <el-select v-model="filter.quality_min" placeholder="质量分" size="small" style="width:110px">
      <el-option v-for="o in QUALITY_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
    </el-select>
    <el-select v-model="filter.compliance" placeholder="合规状态" clearable size="small" style="width:115px">
      <el-option label="合规通过" value="ok" />
      <el-option label="命中红线" value="fail" />
    </el-select>
    <el-select v-model="filter.confirm_status" placeholder="确认状态" clearable size="small" style="width:115px">
      <el-option label="未提交" value="none" />
      <el-option label="待人工确认" value="pending" />
      <el-option label="已确认" value="confirmed" />
      <el-option label="已驳回" value="rejected" />
    </el-select>
    <el-input v-model="filter.keyword" placeholder="搜索标题 / 选题" size="small" clearable style="width:170px"></el-input>
    <el-checkbox v-model="includeHistory" size="small">显示历史版本</el-checkbox>
    <el-button size="small" text @click="resetFilters" :disabled="activeFilterCount === 0">清空筛选</el-button>
  </div>
  <div class="row">
    <span class="muted">当前显示 {{ visibleCount }} 个版本；{{ activeFilterCount }} 个筛选条件</span>
    <el-tag v-if="filter.todoOnly" size="small" type="warning" closable @close="filter.todoOnly = false">仅看待办版本（已确认、待发布）</el-tag>
  </div>
</div>

<div v-if="forbidden" class="page-state">
  <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可查看内容管理，请联系管理员。"></el-result>
</div>
<div v-else-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
</div>
<div v-else-if="loading" class="card"><el-skeleton :rows="8" animated /></div>

<template v-else>
  <div class="batch-bar" v-if="selectedCount">
    <span class="batch-count">已选 {{ selectedCount }} 个版本</span>
    <el-button size="small" type="success" :loading="batch.running" @click="runBatchApprove">批量通过</el-button>
    <el-button size="small" type="danger" :loading="batch.running" @click="batchRejectOpen = true">批量驳回</el-button>
    <el-button size="small" text @click="clearSelection">清空选择</el-button>
    <span class="muted">整批预检不通过时不会写入任何一条</span>
  </div>

  <div class="card" v-if="visibleVariants.length">
    <el-checkbox :model-value="allSelected" @change="toggleSelectAll">全选当前列表（{{ visibleVariants.length }}）</el-checkbox>
  </div>

  <div id="contents-list" v-if="!filteredContents.length" class="card">
    <div class="state-box"><el-icon><i class="el-icon-document" /></el-icon>没有符合条件的内容，试试清空筛选。</div>
  </div>

  <div class="card" v-for="c in filteredContents" :key="c.id">
    <div class="row">
      <b>{{ c.title }}</b>
      <span class="line-tag" :class="bizLineClass(c.biz_line)">{{ bizLineName(c.biz_line) }}</span>
      <el-tag size="small" :type="c.status === 'rejected' ? 'danger' : (c.status === 'published' ? 'success' : 'info')">
        {{ contentStatusName(c.status) }}
      </el-tag>
      <el-tag v-if="c.source" size="small" type="info">{{ c.source === 'ai' ? 'AI 生成' : '人工创建' }}</el-tag>
      <span class="muted right">排期 {{ fmtDate(c.scheduled_date) }} · 来源选题：{{ c.topic || '-' }}</span>
    </div>

    <div v-if="c.status === 'rejected' && c.review_note" class="alert-strip error mt10">
      <b>内容级驳回理由：</b>{{ c.review_note }}
    </div>

    <div v-for="v in c.visibleVariants" :key="v.id" class="variant-row">
      <div class="row">
        <el-checkbox :model-value="!!selected[v.id]" @change="(val) => setSelected(v.id, val)" />
        <span class="pf" :class="'pf-' + v.platform">{{ platformName(v.platform) }}</span>
        <span class="muted">r{{ v.revision }}</span>
        <el-tag v-if="v.is_current" size="small" type="success">当前</el-tag>
        <el-tag v-else size="small" type="info">历史</el-tag>
        <el-button size="small" text type="primary" @click="toggle(c)">{{ openMap[c.id] ? '收起' : '展开 / 编辑' }}</el-button>
        <el-button size="small" text @click="openCompare(c, v)">版本对比</el-button>
        <el-button v-if="canWriteContent && publishEligible(v)" size="small" type="primary" plain @click="openPublish(v)">沙盒发布</el-button>
        <el-tag size="small" :type="variantTagType(v.status)">{{ variantStatusName(v.status) }}</el-tag>
        <el-tag size="small" :type="v.quality_score >= 85 ? 'success' : (v.quality_score >= 70 ? 'warning' : 'danger')">
          质量分 {{ v.quality_score || '-' }}
        </el-tag>
        <el-tag size="small" :type="v.compliance_ok ? 'success' : 'danger'">
          {{ v.compliance_ok ? '合规通过' : '命中红线' }}
        </el-tag>
        <el-tag size="small" :type="confirmTagType(v.confirm_status)">
          {{ confirmStatusName(v.confirm_status) }}
        </el-tag>
        <el-tag size="small" :type="publishTagType(v.publish_status)">
          {{ publishStatusName(v.publish_status) }}
        </el-tag>
        <el-tag v-if="v.published_url" size="small" type="success">已回填链接</el-tag>
      </div>

      <div v-if="v.status === 'blocked' || !v.compliance_ok" class="alert-strip error mt10">
        <b>被拦截原因：</b>{{ v.compliance_hits || '未标注具体词' }}。红线命中不能直接放行；请修改文案后重新质检。
      </div>
      <div v-if="v.rejection_reason" class="alert-strip warn mt10"><b>驳回理由：</b>{{ v.rejection_reason }}</div>
      <div v-if="v.quality_note" class="muted mt6">质检评语：{{ v.quality_note }}</div>
      <div v-if="v.published_url" class="muted mt6">发布链接：<a :href="v.published_url" target="_blank">{{ v.published_url }}</a> · {{ fmtDateTime(v.published_at) }}</div>
      <div v-if="v.publish_error" class="alert-strip warn mt10">发布失败：{{ v.publish_error }}</div>

      <div v-if="openMap[c.id]" class="mt10">
        <el-input v-model="draft[v.id].cover_text" placeholder="封面文案 / 标题" size="small" style="margin-bottom:6px"></el-input>
        <el-input v-model="draft[v.id].body" type="textarea" :rows="5" placeholder="正文"></el-input>
        <el-input v-model="draft[v.id].hashtags" placeholder="话题标签" size="small" style="margin-top:6px"></el-input>
        <div class="row mt10">
          <el-button v-if="canWriteContent" size="small" type="primary" :loading="busy[v.id]" @click="saveVariant(v)">保存并重新合规检查</el-button>
          <el-button v-if="canWriteContent" size="small" @click="openVideo(v)">生成视频</el-button>
          <el-button v-if="canWriteContent && v.confirm_status === 'pending' && v.status === 'pending' && v.compliance_ok"
                     size="small" type="success" :loading="busy[v.id]" @click="approveOne(v)">通过此版本</el-button>
          <el-button v-if="canWriteContent && v.confirm_status === 'pending' && v.status === 'pending' && v.compliance_ok"
                     size="small" type="danger" @click="rejectMode[v.id] = !rejectMode[v.id]">驳回此版本</el-button>
          <template v-if="rejectMode[v.id]">
            <el-input v-model="rejectNote[v.id]" size="small" placeholder="驳回理由（必填）" style="width:280px"></el-input>
            <el-button size="small" type="danger" :loading="busy[v.id]" @click="rejectOne(v)">确认驳回</el-button>
          </template>
          <el-tooltip placement="top" content="后端未提供切换当前版本接口（M-P0-05）；当前只读对比">
            <span><el-button size="small" disabled>设为当前版本</el-button></span>
          </el-tooltip>
        </div>
      </div>
    </div>

    <div v-if="canWriteContent" class="row mt14 compat-review">
      <span class="muted">整包快捷审核（兼容入口，建议逐版本处理）：</span>
      <el-button size="small" type="success" :loading="busy['c' + c.id]" @click="reviewContent(c, 'approve')">整包通过</el-button>
      <el-button size="small" type="danger" @click="rejectMode['c' + c.id] = !rejectMode['c' + c.id]">整包驳回</el-button>
      <template v-if="rejectMode['c' + c.id]">
        <el-input v-model="rejectNote['c' + c.id]" size="small" placeholder="整包驳回理由（必填）" style="width:280px"></el-input>
        <el-button size="small" type="danger" :loading="busy['c' + c.id]" @click="reviewContent(c, 'reject')">确认整包驳回</el-button>
      </template>
    </div>
  </div>
    </template>
  </el-tab-pane>

  <el-tab-pane label="版本筛选与批量审核（二期）" name="variants">
    <div class="toolbar">
      <el-select v-model="vq.platform_id" placeholder="全部平台" clearable size="small" style="width:140px">
        <el-option v-for="p in pfList" :key="p.id" :label="p.name" :value="p.id"></el-option>
      </el-select>
      <el-select v-model="vq.status" placeholder="全部状态" clearable size="small" style="width:120px">
        <el-option label="草稿" value="draft"/>
        <el-option label="待审核" value="pending"/>
        <el-option label="已通过" value="approved"/>
        <el-option label="已驳回" value="rejected"/>
        <el-option label="已发布" value="published"/>
      </el-select>
      <el-select v-model="vq.confirm_status" placeholder="全部确认状态" clearable size="small" style="width:140px">
        <el-option label="待确认" value="pending"/>
        <el-option label="已确认" value="confirmed"/>
        <el-option label="已驳回" value="rejected"/>
        <el-option label="无" value="none"/>
      </el-select>
      <el-date-picker v-model="vq.scheduled_from" type="date" placeholder="排期起" size="small" value-format="YYYY-MM-DD" style="width:140px"></el-date-picker>
      <el-date-picker v-model="vq.scheduled_to" type="date" placeholder="排期止" size="small" value-format="YYYY-MM-DD" style="width:140px"></el-date-picker>
      <el-select v-model="vq.compliance_ok" placeholder="全部合规状态" clearable size="small" style="width:140px">
        <el-option label="合规通过" value="true"/>
        <el-option label="命中红线" value="false"/>
      </el-select>
      <el-button size="small" type="primary" @click="applyVariantFilter" :loading="vloading">查询</el-button>
    </div>
    <div class="toolbar">
      <el-button size="small" type="success" :loading="bulkBusy" @click="bulkApprove">批量通过</el-button>
      <el-button size="small" type="danger" :loading="bulkBusy" @click="bulkReject">批量驳回（带理由）</el-button>
      <span class="muted">已选 {{ vselected.length }} 条 · 共 {{ vtotal }} 条 · 批量操作带版本锁，避免覆盖他人审核</span>
    </div>
    <div class="card">
      <el-table :data="vlist" size="small" v-loading="vloading" empty-text="没有符合条件的版本" @selection-change="vselected = $event.map(x => x.id)">
        <el-table-column type="selection" width="42"></el-table-column>
        <el-table-column prop="content_title" label="内容标题" min-width="200" show-overflow-tooltip></el-table-column>
        <el-table-column label="平台" width="100">
          <template #default="s"><span class="pf" :class="'pf-' + s.row.platform">{{ platformName(s.row.platform) }}</span></template>
        </el-table-column>
        <el-table-column prop="scheduled_date" label="排期" width="100"></el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="s"><el-tag size="small">{{ vStatusName(s.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="确认" width="90">
          <template #default="s"><span class="muted">{{ confirmStatusName(s.row.confirm_status) }}</span></template>
        </el-table-column>
        <el-table-column prop="quality_score" label="质量分" width="80"></el-table-column>
        <el-table-column label="合规" width="90">
          <template #default="s">
            <el-tag size="small" :type="s.row.compliance_ok ? 'success' : 'danger'">{{ s.row.compliance_ok ? '通过' : '红线' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="70"></el-table-column>
      </el-table>
      <el-pagination class="mt10" layout="total, prev, pager, next" :total="vtotal" :page-size="50" :current-page="1" @current-change="vq.offset = ($event - 1) * 50; applyVariantFilter()"></el-pagination>
    </div>
  </el-tab-pane>
</el-tabs>

<!-- 视频生成 -->
<el-dialog v-model="video.open" title="生成视频" width="620px" @closed="closeVideo">
  <div class="muted mb10">{{ video.title }} · {{ platformName(video.platform) }}</div>
  <div v-if="video.error" class="alert-strip error">{{ video.error }}</div>

  <template v-if="video.configured === false">
    <el-alert type="warning" :closable="false" show-icon
              title="平台视频服务未配置"
              description="部署时需在 .env 配置 PIOS_API_URL 与 PIOS_TOKEN。未配置时系统不会生成占位视频冒充真实成片。"></el-alert>
  </template>

  <template v-else>
    <div v-if="video.modelNote" class="gap-note">模型：{{ video.modelNote }}；系统会按当前文案自动拼提示词，不虚构业绩数字、客户名称或价格。</div>

    <div v-if="video.task" class="mt10">
      <div class="row">
        <el-tag size="small" :type="video.task.status === 'succeeded' ? 'success' : (video.task.status === 'failed' ? 'danger' : 'warning')">
          {{ video.task.status === 'pending' ? '排队中' : (video.task.status === 'running' ? '生成中' : (video.task.status === 'succeeded' ? '已完成' : (video.task.status === 'failed' ? '失败' : video.task.status))) }}
        </el-tag>
        <span class="muted">任务 #{{ video.taskId }}</span>
        <span v-if="video.task.result && video.task.result.credits_charged" class="muted">
          消耗 {{ video.task.result.credits_charged }} 积分
        </span>
      </div>
      <div v-if="video.polling" class="gap-note">视频生成通常需要数十秒到数分钟，可关闭窗口稍后在任务中查看。</div>
      <video v-if="video.blobUrl" :src="video.blobUrl" controls playsinline
             style="width:100%;max-height:420px;margin-top:10px;border-radius:8px;background:#000"></video>
    </div>
  </template>

  <template #footer>
    <el-button @click="closeVideo">关闭</el-button>
    <el-button v-if="video.configured && !video.task" type="primary" :loading="video.submitting" @click="startVideo">开始生成</el-button>
  </template>
</el-dialog>

<!-- 批量审批结果 -->
<el-dialog v-model="batch.open" :title="batch.title" width="760px" :close-on-click-modal="!batch.running">
  <div v-if="batch.error" class="alert-strip error">{{ batch.error }}</div>
  <div v-else class="alert-strip" :class="batch.results.some(r => !r.ok) ? 'warn' : 'ok'">{{ batch.summary }}</div>
  <div v-if="batch.mode === 'fallback'" class="gap-note">当前为逐条兼容模式：后端批量接口未就绪，已逐条调用旧接口；可能部分写入，请核对列表。</div>
  <el-table :data="batch.results" size="small" max-height="420" style="width:100%">
    <el-table-column prop="variant_id" label="版本 ID" width="90"></el-table-column>
    <el-table-column prop="content_title" label="内容" min-width="180" show-overflow-tooltip></el-table-column>
    <el-table-column prop="revision" label="版本" width="70"></el-table-column>
    <el-table-column label="结果" width="90">
      <template #default="{ row }">
        <el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? '成功' : '未通过' }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="message" label="说明" min-width="260" show-overflow-tooltip></el-table-column>
  </el-table>
  <template #footer>
    <el-button @click="batch.open = false">关闭</el-button>
  </template>
</el-dialog>

<!-- 批量驳回理由 -->
<el-dialog v-model="batchRejectOpen" title="批量驳回" width="560px">
  <el-alert type="warning" :closable="false" show-icon
            title="驳回理由会保留在每个版本上，并用于生成新版本；理由必填。"></el-alert>
  <el-input v-model="batchRejectReason" type="textarea" :rows="4" maxlength="2000" show-word-limit
            placeholder="例如：封面文案与业务线不符，请按驳回理由重生成" style="margin-top:12px"></el-input>
  <div v-if="batchRejectError" class="alert-strip error mt10">{{ batchRejectError }}</div>
  <template #footer>
    <el-button @click="batchRejectOpen = false">取消</el-button>
    <el-button type="danger" :loading="batch.running" @click="runBatchReject">确认批量驳回</el-button>
  </template>
</el-dialog>

<!-- 版本对比 -->
<el-dialog v-model="cmp.open" :title="'版本对比 · ' + cmp.contentTitle" width="94%" top="4vh">
  <div v-if="cmp.loading" class="card"><el-skeleton :rows="8" animated /></div>
  <div v-else-if="cmp.error" class="alert-strip error">
    版本历史加载失败：{{ cmp.error }}
  </div>
  <template v-else>
    <div class="cmp-toolbar">
      <span class="muted">平台：{{ platformName(cmp.platform) }}</span>
      <el-select v-model="cmp.leftId" size="small" style="width:280px" placeholder="版本 A">
        <el-option v-for="v in cmp.variants" :key="v.id" :label="versionLabel(v)" :value="v.id" />
      </el-select>
      <span class="muted">对比</span>
      <el-select v-model="cmp.rightId" size="small" style="width:280px" placeholder="版本 B">
        <el-option v-for="v in cmp.variants" :key="v.id" :label="versionLabel(v)" :value="v.id" />
      </el-select>
      <el-tag v-if="cmpSame" size="small" type="info">两侧为同一版本</el-tag>
      <span v-if="cmpDiff" class="muted">正文：+{{ cmpDiff.body.stats.added }} / -{{ cmpDiff.body.stats.removed }}</span>
    </div>

    <div class="cmp-timeline">
      <div v-for="v in cmp.variants" :key="v.id" class="cmp-rev"
           :class="{ current: v.is_current, left: cmp.leftId === v.id, right: cmp.rightId === v.id }">
        <span class="rev-no">r{{ v.revision }}</span>
        <span class="rev-time">{{ fmtDateTime(v.created_at) }}</span>
        <el-tag size="small" :type="variantTagType(v.status)">{{ variantStatusName(v.status) }}</el-tag>
        <span v-if="v.is_current" class="rev-current">当前</span>
      </div>
    </div>

    <div v-if="cmpLeft && cmpRight && cmpDiff" class="cmp-grid">
      <div class="cmp-side">
        <div class="cmp-head">版本 A · r{{ cmpLeft.revision }} · {{ fmtDateTime(cmpLeft.created_at) }}</div>
        <div class="cmp-block">
          <div class="cmp-label">封面文案 / 标题</div>
          <div class="diff-inline"><span v-for="(seg, i) in cmpDiff.title.left" :key="'lt' + i" :class="'diff-seg diff-' + seg.type">{{ seg.text }}</span></div>
        </div>
        <div class="cmp-block">
          <div class="cmp-label">正文</div>
          <div class="diff-lines"><div v-for="(line, i) in cmpDiff.body.left" :key="'lb' + i" :class="'diff-line diff-' + line.type">{{ line.text || ' ' }}</div></div>
        </div>
        <div class="cmp-block">
          <div class="cmp-label">话题</div>
          <div class="diff-inline"><span v-for="(seg, i) in cmpDiff.hashtags.left" :key="'lh' + i" :class="'diff-seg diff-' + seg.type">{{ seg.text }}</span></div>
        </div>
        <div v-if="cmpLeft.rejection_reason" class="alert-strip error mt10"><b>驳回理由：</b>{{ cmpLeft.rejection_reason }}</div>
      </div>
      <div class="cmp-side">
        <div class="cmp-head">版本 B · r{{ cmpRight.revision }} · {{ fmtDateTime(cmpRight.created_at) }}</div>
        <div class="cmp-block">
          <div class="cmp-label">封面文案 / 标题</div>
          <div class="diff-inline"><span v-for="(seg, i) in cmpDiff.title.right" :key="'rt' + i" :class="'diff-seg diff-' + seg.type">{{ seg.text }}</span></div>
        </div>
        <div class="cmp-block">
          <div class="cmp-label">正文</div>
          <div class="diff-lines"><div v-for="(line, i) in cmpDiff.body.right" :key="'rb' + i" :class="'diff-line diff-' + line.type">{{ line.text || ' ' }}</div></div>
        </div>
        <div class="cmp-block">
          <div class="cmp-label">话题</div>
          <div class="diff-inline"><span v-for="(seg, i) in cmpDiff.hashtags.right" :key="'rh' + i" :class="'diff-seg diff-' + seg.type">{{ seg.text }}</span></div>
        </div>
        <div v-if="cmpRight.rejection_reason" class="alert-strip error mt10"><b>驳回理由：</b>{{ cmpRight.rejection_reason }}</div>
      </div>
    </div>
    <div v-else class="state-box">只有一个版本，暂无可对比的历史版本。</div>
    <div class="gap-note">diff 在本机计算，不上传正文到第三方；「设为当前版本」需后端提供切换接口（M-P0-05），当前只读。</div>
  </template>
</el-dialog>

<el-dialog v-model="publish.open" title="沙盒发布" width="600px" append-to-body>
  <div v-if="publish.variant" class="mb10">
    <div class="muted">内容版本</div>
    <b>#{{ publish.variant.id }} · {{ platformName(publish.variant.platform) }} · r{{ publish.variant.revision }}</b>
    <div class="muted mt6">标题：{{ publish.variant.cover_text || '（无）' }}</div>
  </div>
  <div v-if="publish.error" class="alert-strip error mt10">{{ publish.error }}</div>
  <div v-if="publish.loadingAccounts" class="card"><el-skeleton :rows="2" animated /></div>
  <div v-else-if="!publishAccounts.length" class="alert-strip warn">
    当前平台还没有工作空间账号。请先到「工作台 → 平台通道」添加并扫码登录同平台账号。
  </div>
  <div v-else-if="!publishHasConnected" class="alert-strip warn">
    当前平台的账号均未连接（{{
      publishAccounts.map((a) => a.label + '：' + (a.status === 'expired' ? '登录已过期' : a.status === 'awaiting_scan' ? '待扫码' : '未连接')).join('；')
    }}）。请先到「工作台 → 平台通道」完成扫码登录，再发起沙盒发布。
    <div class="mt10"><el-button size="small" @click="goWorkbench">去工作台登录</el-button></div>
  </div>
  <template v-else>
    <div class="muted mb6">选择已连接的同平台账号（任务提交到沙盒适配器，步骤与截图全程留痕）</div>
    <el-select v-model="publish.accountId" style="width:100%" placeholder="选择工作空间账号">
      <el-option v-for="a in publishAccounts" :key="a.id"
                 :label="a.label + '（' + (a.status === 'connected' ? '已连接' : a.status) + '）'"
                 :value="a.id" :disabled="a.status !== 'connected'"></el-option>
    </el-select>
    <div class="gap-note mt10">
      幂等键：variant_{{ publish.variant.id }}_{{ publish.accountId || '账号' }}；重复提交不会重复建任务。
    </div>
  </template>
  <div v-if="publish.job" class="alert-strip ok mt10">
    任务 #{{ publish.job.id }} 已创建，当前状态：{{ publish.job.status }}。请到工作台查看任务进度。
  </div>
  <template #footer>
    <el-button @click="publish.open = false">关闭</el-button>
    <el-button v-if="publish.job" type="primary" @click="goWorkbench">去工作台查看</el-button>
    <el-button v-else type="primary" :loading="publish.busy" :disabled="!publishCanSubmit || publish.loadingAccounts" @click="submitPublish">创建发布任务</el-button>
  </template>
</el-dialog>

<el-dialog v-model="draftDlg" title="新建草稿（二期）" width="640px">
  <el-form label-width="90px">
    <el-form-item label="标题"><el-input v-model="draftForm.title" maxlength="200" show-word-limit></el-input></el-form-item>
    <el-form-item label="平台">
      <el-select v-model="draftForm.platform_id" style="width:100%">
        <el-option v-for="p in pfList" :key="p.id" :label="p.name + '（' + p.code + '）'" :value="p.id"></el-option>
      </el-select>
    </el-form-item>
    <el-form-item label="业务线">
      <el-select v-model="draftForm.biz_line" style="width:100%">
        <el-option label="甲方线" value="project"/>
        <el-option label="渠道线" value="channel"/>
      </el-select>
    </el-form-item>
    <el-form-item label="排期"><el-date-picker v-model="draftForm.scheduled_date" type="date" value-format="YYYY-MM-DD" placeholder="留空表示未定" style="width:100%"></el-date-picker></el-form-item>
    <el-form-item label="正文"><el-input v-model="draftForm.body" type="textarea" :rows="8" placeholder="草稿正文，保存后自动跑合规检查"></el-input></el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="draftDlg = false">取消</el-button>
    <el-button type="primary" :loading="draftSaving" @click="saveDraft">保存草稿</el-button>
  </template>
</el-dialog>
`,
};
