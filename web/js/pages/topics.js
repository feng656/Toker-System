/**
 * 选题池：主题分类、业务线、表现分、状态（可用 / 已使用 / 已归档）。
 * 完成标志（《分工》4.2）：运营可独立维护素材和选题。
 */
import { ref, reactive, computed, onMounted } from '../core/vue.js';
import { topicApi } from '../api/library.js';
import { notify, errorMessage } from '../core/ui.js';
import { bizLineClass, bizLineName, topicStatusName, TOPIC_THEMES } from '../core/format.js';
import { canWriteContent } from '../core/store.js';

export default {
  name: 'PageTopics',
  setup() {
    const topics = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);
    const filter = reactive({ biz_line: '', theme: '', status: '', keyword: '' });

    const dlg = ref(false);
    const saving = ref(false);
    const form = reactive({ biz_line: 'project', theme: '', title: '', angle: '' });

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        // 后端按 status 精确过滤，这里并行取三种状态后合并，便于运营查看历史选题
        const [active, used, archived] = await Promise.all([
          topicApi.list({ status: 'active' }),
          topicApi.list({ status: 'used' }),
          topicApi.list({ status: 'archived' }),
        ]);
        topics.value = [...(active || []), ...(used || []), ...(archived || [])];
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
        topics.value = [];
      } finally {
        loading.value = false;
      }
    }

    const filtered = computed(() => {
      const kw = filter.keyword.trim();
      return topics.value.filter((t) => {
        if (filter.biz_line && t.biz_line !== filter.biz_line) return false;
        if (filter.theme && t.theme !== filter.theme) return false;
        if (filter.status && t.status !== filter.status) return false;
        if (kw && (t.title || '').indexOf(kw) < 0 && (t.angle || '').indexOf(kw) < 0) return false;
        return true;
      });
    });

    async function save() {
      if (!form.theme.trim() || !form.title.trim()) {
        notify.err('主题与选题标题为必填');
        return;
      }
      saving.value = true;
      try {
        await topicApi.create({ biz_line: form.biz_line, theme: form.theme.trim(), title: form.title.trim(), angle: form.angle });
        notify.ok('已新增选题');
        dlg.value = false;
        Object.assign(form, { biz_line: 'project', theme: '', title: '', angle: '' });
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        saving.value = false;
      }
    }

    async function setStatus(t, status) {
      try {
        await topicApi.setStatus(t.id, status);
        notify.ok(`已标记为「${topicStatusName(status)}」`);
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    onMounted(load);

    return {
      topics, filtered, loading, error, forbidden, filter, dlg, saving, form,
      load, save, setStatus, canWriteContent, bizLineClass, bizLineName, topicStatusName, TOPIC_THEMES,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">选题池</div>
    <div class="page-sub">选题是内容的源头。主题分类决定内容方向；表现分由历史表现回填（当前后端不自动更新，GAP-11）；状态「已使用」表示已被生成过，避免重复。</div>
  </div>
  <div class="row">
    <el-button v-if="canWriteContent" size="small" type="primary" @click="dlg = true">+ 新增选题</el-button>
    <el-button size="small" @click="load" :loading="loading">刷新</el-button>
  </div>
</div>

<div class="toolbar">
  <el-select v-model="filter.biz_line" placeholder="全部业务线" clearable size="small" style="width:120px">
    <el-option label="甲方线" value="project"/>
    <el-option label="渠道线" value="channel"/>
  </el-select>
  <el-select v-model="filter.theme" placeholder="全部主题" clearable size="small" style="width:140px">
    <el-option v-for="t in TOPIC_THEMES" :key="t" :label="t" :value="t"></el-option>
  </el-select>
  <el-select v-model="filter.status" placeholder="全部状态" clearable size="small" style="width:120px">
    <el-option label="可用" value="active"/>
    <el-option label="已使用" value="used"/>
    <el-option label="已归档" value="archived"/>
  </el-select>
  <el-input v-model="filter.keyword" placeholder="搜索选题 / 角度" size="small" clearable style="width:200px"></el-input>
  <span class="muted">共 {{ filtered.length }} / {{ topics.length }} 条</span>
</div>

<div v-if="forbidden" class="page-state">
  <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可查看选题池，请联系管理员。"></el-result>
</div>
<div v-else-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
</div>
<div v-else-if="loading" class="card"><el-skeleton :rows="5" animated /></div>

<template v-else>
  <div v-if="!filtered.length" class="card">
    <div class="state-box"><el-icon><i class="el-icon-lightbulb" /></el-icon>没有符合条件的选题</div>
  </div>

  <div class="card" v-for="t in filtered" :key="t.id">
    <div class="row">
      <el-tag size="small">{{ t.theme }}</el-tag>
      <span class="line-tag" :class="bizLineClass(t.biz_line)">{{ bizLineName(t.biz_line) }}</span>
      <b>{{ t.title }}</b>
      <el-tag size="small" :type="t.status === 'active' ? 'success' : 'info'">{{ topicStatusName(t.status) }}</el-tag>
      <span class="muted right">表现分 <b>{{ Number(t.score || 0).toFixed(1) }}</b></span>
    </div>
    <div class="muted mt6" style="line-height:1.8">{{ t.angle }}</div>
    <div class="row mt10" v-if="canWriteContent">
      <el-button v-if="t.status !== 'used'" size="small" @click="setStatus(t, 'used')">标记已使用</el-button>
      <el-button v-if="t.status !== 'active'" size="small" @click="setStatus(t, 'active')">恢复可用</el-button>
      <el-button v-if="t.status !== 'archived'" size="small" @click="setStatus(t, 'archived')">归档</el-button>
      <el-tooltip placement="top" content="后端暂无「编辑选题 / 删除选题」接口，见《接口缺口清单》GAP-12">
        <span><el-button size="small" disabled>编辑选题</el-button></span>
      </el-tooltip>
    </div>
  </div>
</template>

<el-dialog v-model="dlg" title="新增选题" width="540px">
  <el-form label-width="86px">
    <el-form-item label="业务线">
      <el-select v-model="form.biz_line">
        <el-option label="甲方线" value="project"/>
        <el-option label="渠道线" value="channel"/>
      </el-select>
    </el-form-item>
    <el-form-item label="主题">
      <el-select v-model="form.theme" filterable allow-create default-first-option>
        <el-option v-for="t in TOPIC_THEMES" :key="t" :label="t" :value="t"></el-option>
      </el-select>
    </el-form-item>
    <el-form-item label="选题"><el-input v-model="form.title" placeholder="选题标题（必填）" maxlength="200" show-word-limit></el-input></el-form-item>
    <el-form-item label="角度"><el-input v-model="form.angle" type="textarea" :rows="3" placeholder="这条内容从什么角度切，避免和历史选题重复"></el-input></el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="dlg = false">取消</el-button>
    <el-button type="primary" :loading="saving" @click="save">保存</el-button>
  </template>
</el-dialog>
`,
};
