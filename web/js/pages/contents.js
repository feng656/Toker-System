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
      window.addEventListener('hashchange', onHashChange);
    });

    onUnmounted(() => {
      if (syncTimer) window.clearTimeout(syncTimer);
      window.removeEventListener('hashchange', onHashChange);
    });

    return {
      contents, filteredContents, visibleVariants, loading, error, forbidden, filter, includeHistory,
      openMap, draft, busy, selected, rejectMode, rejectNote,
      todo, batch, batchRejectOpen, batchRejectReason, batchRejectError,
      cmp, cmpLeft, cmpRight, cmpSame, cmpDiff,
      stats, visibleCount, activeFilterCount, allSelected, selectedCount, selectedList,
      QUALITY_OPTIONS, platformFilterOptions,
      load, loadTodo, resetFilters, jumpTodo, toggle, saveVariant, approveOne, rejectOne,
      reviewContent, openCompare, versionLabel,
      setSelected, toggleSelectAll, clearSelection,
      runBatchApprove, runBatchReject, precheckBatch, resultRow,
      canWriteContent, platformName, bizLineClass, bizLineName, contentStatusName,
      variantStatusName, confirmStatusName, publishStatusName, fmtDate, fmtDateTime,
      variantTagType, confirmTagType, publishTagType,
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
  </div>
</div>

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
`,
};
