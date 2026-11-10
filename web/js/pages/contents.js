/**
 * 内容管理：内容包 + 平台版本（选题与平台版本展示、修改、审核、驳回理由、重新生成入口）。
 * 完成标志（《分工》4.2）：用户能看懂每个版本为何通过或被拦截。
 */
import { ref, reactive, computed, onMounted } from '../core/vue.js';
import { contentApi } from '../api/content.js';
import { phase2Api } from '../api/phase2.js';
import { notify, errorMessage } from '../core/ui.js';
import {
  platformName, bizLineClass, bizLineName, contentStatusName, confirmStatusName,
  publishStatusName, fmtDate, fmtDateTime,
} from '../core/format.js';
import { canWriteContent } from '../core/store.js';

export default {
  name: 'PageContents',
  setup() {
    const contents = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);
    const filter = reactive({ status: '', biz_line: '', keyword: '' });
    const openMap = reactive({});
    const draft = reactive({});     // vid → {body, cover_text, hashtags}
    const busy = reactive({});
    const rejectMode = reactive({}); // cid → true
    const rejectNote = reactive({}); // cid → note

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
        const list = await contentApi.list();
        contents.value = list || [];
        (list || []).forEach((c) => {
          (c.variants || []).forEach((v) => {
            if (!draft[v.id]) draft[v.id] = { body: v.body || '', cover_text: v.cover_text || '', hashtags: v.hashtags || '' };
          });
        });
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
        contents.value = [];
      } finally {
        loading.value = false;
      }
    }

    const filtered = computed(() => {
      const kw = filter.keyword.trim();
      return contents.value.filter((c) => {
        if (filter.status && c.status !== filter.status) return false;
        if (filter.biz_line && c.biz_line !== filter.biz_line) return false;
        if (kw && (c.title || '').indexOf(kw) < 0 && (c.topic || '').indexOf(kw) < 0) return false;
        return true;
      });
    });

    function toggle(c) {
      openMap[c.id] = !openMap[c.id];
    }

    async function saveVariant(v) {
      busy[v.id] = true;
      try {
        const updated = await contentApi.updateVariant(v.id, {
          body: draft[v.id].body,
          cover_text: draft[v.id].cover_text,
          hashtags: draft[v.id].hashtags,
        });
        Object.assign(v, updated);
        notify.ok(updated.compliance_ok ? '已保存，合规检查通过' : `已保存，但命中红线：${updated.compliance_hits}`);
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[v.id] = false;
      }
    }

    async function review(c, action) {
      busy[c.id] = true;
      try {
        const note = rejectNote[c.id] || '';
        if (action === 'reject' && !note.trim()) {
          notify.err('驳回必须填写理由，理由会保留在内容上并用于改进生成');
          busy[c.id] = false;
          return;
        }
        await contentApi.review(c.id, action, note);
        notify.ok(action === 'approve' ? '已通过' : '已驳回并记录理由');
        rejectMode[c.id] = false;
        rejectNote[c.id] = '';
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[c.id] = false;
      }
    }

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

    onMounted(() => { load(); loadPlatforms(); });

    return {
      contents, filtered, loading, error, forbidden, filter, openMap, draft, busy,
      rejectMode, rejectNote, load, toggle, saveVariant, review,
      canWriteContent, platformName, bizLineClass, bizLineName, contentStatusName,
      confirmStatusName, publishStatusName, fmtDate, fmtDateTime,
      tab, pfList, vq, vlist, vtotal, vloading, vselected, bulkBusy,
      draftDlg, draftSaving, draftForm,
      applyVariantFilter, bulkApprove, bulkReject, openDraft, saveDraft, vStatusName,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">内容管理</div>
    <div class="page-sub">每个内容包对应一个选题，下面按平台展开版本。版本上会标明：AI 质检分、是否命中合规红线、人工确认状态、发布状态与链接——这就是「为什么通过 / 为什么被拦截」。</div>
  </div>
  <div class="row">
    <el-select v-model="filter.status" placeholder="全部状态" clearable size="small" style="width:130px">
      <el-option label="待审核" value="draft"/>
      <el-option label="已通过" value="approved"/>
      <el-option label="已驳回" value="rejected"/>
      <el-option label="已发布" value="published"/>
    </el-select>
    <el-select v-model="filter.biz_line" placeholder="全部业务线" clearable size="small" style="width:120px">
      <el-option label="甲方线" value="project"/>
      <el-option label="渠道线" value="channel"/>
    </el-select>
    <el-input v-model="filter.keyword" placeholder="搜索标题 / 选题" size="small" clearable style="width:180px"></el-input>
    <el-button size="small" @click="load" :loading="loading">刷新</el-button>
    <el-button v-if="canWriteContent" size="small" type="primary" @click="openDraft">+ 新建草稿</el-button>
  </div>
</div>

<el-tabs v-model="tab">
  <el-tab-pane label="内容包（按选题）" name="pack">
    <div v-if="forbidden" class="page-state">
      <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可查看内容管理，请联系管理员。"></el-result>
    </div>
    <div v-else-if="error" class="alert-strip error">
      加载失败：{{ error }}
      <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
    </div>
    <div v-else-if="loading" class="card"><el-skeleton :rows="8" animated /></div>

    <template v-else>
  <div v-if="!filtered.length" class="card">
    <div class="state-box"><el-icon><i class="el-icon-document" /></el-icon>没有符合条件的内容</div>
  </div>

  <div class="card" v-for="c in filtered" :key="c.id">
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
      <b>驳回理由：</b>{{ c.review_note }}
    </div>

    <div v-for="v in c.variants" :key="v.id" class="mt14" style="border-top:1px dashed #ebeef5;padding-top:10px">
      <div class="row">
        <span class="pf" :class="'pf-' + v.platform">{{ platformName(v.platform) }}</span>
        <el-button size="small" text type="primary" @click="toggle(c)">{{ openMap[c.id] ? '收起' : '展开 / 编辑' }}</el-button>
        <el-tag size="small" :type="v.quality_score >= 85 ? 'success' : (v.quality_score >= 70 ? 'warning' : 'danger')">
          质量分 {{ v.quality_score || '-' }}
        </el-tag>
        <el-tag size="small" :type="v.compliance_ok ? 'success' : 'danger'">
          {{ v.compliance_ok ? '合规通过' : '命中红线' }}
        </el-tag>
        <el-tag size="small" :type="v.confirm_status === 'confirmed' ? 'success' : 'info'">
          {{ confirmStatusName(v.confirm_status) }}
        </el-tag>
        <el-tag size="small" :type="v.publish_status === 'published' ? 'success' : (v.publish_status === 'failed' ? 'danger' : 'info')">
          {{ publishStatusName(v.publish_status) }}
        </el-tag>
        <el-tag v-if="v.published_url" size="small" type="success">已回填链接</el-tag>
      </div>

      <div v-if="!v.compliance_ok" class="alert-strip error mt10">被拦截原因：命中禁用/广告法词 —— {{ v.compliance_hits || '未标注具体词' }}。按《分工》硬门槛，红线命中不能直接放行。</div>
      <div v-if="v.quality_note" class="muted mt6">质检评语：{{ v.quality_note }}</div>
      <div v-if="v.published_url" class="muted mt6">发布链接：<a :href="v.published_url" target="_blank">{{ v.published_url }}</a> · {{ fmtDateTime(v.published_at) }}</div>
      <div v-if="v.publish_error" class="alert-strip warn mt10">发布失败：{{ v.publish_error }}</div>

      <div v-if="openMap[c.id]" class="mt10">
        <el-input v-model="draft[v.id].cover_text" placeholder="封面文案" size="small" style="margin-bottom:6px"></el-input>
        <el-input v-model="draft[v.id].body" type="textarea" :rows="5" placeholder="正文"></el-input>
        <el-input v-model="draft[v.id].hashtags" placeholder="话题标签" size="small" style="margin-top:6px"></el-input>
        <div class="row mt10">
          <el-button v-if="canWriteContent" size="small" type="primary" :loading="busy[v.id]" @click="saveVariant(v)">保存并重新合规检查</el-button>
          <el-tooltip placement="top" content="后端暂未提供「按驳回理由重新生成变体」接口，见《接口缺口清单》GAP-03">
            <span><el-button size="small" disabled>重新生成此版本</el-button></span>
          </el-tooltip>
        </div>
      </div>
    </div>

    <div v-if="canWriteContent" class="row mt14">
      <el-button size="small" type="success" :loading="busy[c.id]" @click="review(c, 'approve')">通过</el-button>
      <el-button size="small" type="danger" @click="rejectMode[c.id] = !rejectMode[c.id]">驳回</el-button>
      <template v-if="rejectMode[c.id]">
        <el-input v-model="rejectNote[c.id]" size="small" placeholder="驳回理由（必填）" style="width:300px"></el-input>
        <el-button size="small" type="danger" :loading="busy[c.id]" @click="review(c, 'reject')">确认驳回</el-button>
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
