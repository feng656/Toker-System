/**
 * 素材库：公司素材的分类、业务线、公开级别维护 + 附件 + 筛选 + 批量导入入口。
 * 完成标志（《分工》4.2）：运营可独立维护素材和选题。
 */
import { ref, reactive, computed, onMounted } from '../core/vue.js';
import { materialApi } from '../api/library.js';
import { notify, errorMessage } from '../core/ui.js';
import {
  publicityName, bizLineClass, bizLineName, MATERIAL_CATEGORIES,
} from '../core/format.js';
import { canWriteContent, isAdmin } from '../core/store.js';

export default {
  name: 'PageMaterials',
  setup() {
    const materials = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);
    const filter = reactive({ category: '', biz_line: '', publicity: '', keyword: '', onlyEnabled: false });

    const dlg = ref(false);
    const editing = ref(null);
    const saving = ref(false);
    const form = reactive({ id: null, category: '案例', biz_line: 'both', title: '', content: '', publicity: 'public', tags: '', enabled: true });
    const importDlg = ref(false);

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        materials.value = await materialApi.list() || [];
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
        materials.value = [];
      } finally {
        loading.value = false;
      }
    }

    const filtered = computed(() => {
      const kw = filter.keyword.trim();
      return materials.value.filter((m) => {
        if (filter.category && m.category !== filter.category) return false;
        if (filter.biz_line && m.biz_line !== filter.biz_line) return false;
        if (filter.publicity && m.publicity !== filter.publicity) return false;
        if (filter.onlyEnabled && !m.enabled) return false;
        if (kw && (m.title || '').indexOf(kw) < 0 && (m.content || '').indexOf(kw) < 0 && (m.tags || '').indexOf(kw) < 0) return false;
        return true;
      });
    });

    function openCreate() {
      editing.value = null;
      Object.assign(form, { id: null, category: '案例', biz_line: 'both', title: '', content: '', publicity: 'public', tags: '', enabled: true });
      dlg.value = true;
    }

    function openEdit(m) {
      editing.value = m;
      Object.assign(form, {
        id: m.id, category: m.category, biz_line: m.biz_line, title: m.title,
        content: m.content, publicity: m.publicity, tags: m.tags, enabled: !!m.enabled,
      });
      dlg.value = true;
    }

    async function save() {
      if (!form.title.trim()) { notify.err('素材标题不能为空'); return; }
      saving.value = true;
      try {
        const body = {
          category: form.category, biz_line: form.biz_line, title: form.title.trim(),
          content: form.content, publicity: form.publicity, tags: form.tags,
          enabled: form.enabled, file_url: (editing.value && editing.value.file_url) || '',
        };
        if (form.id) await materialApi.update(form.id, body);
        else await materialApi.create(body);
        notify.ok('已保存');
        dlg.value = false;
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        saving.value = false;
      }
    }

    async function toggleEnabled(m) {
      try {
        await materialApi.update(m.id, {
          category: m.category, biz_line: m.biz_line, title: m.title,
          content: m.content, publicity: m.publicity, tags: m.tags,
          enabled: !m.enabled, file_url: m.file_url || '',
        });
        notify.ok(m.enabled ? '已停用' : '已启用');
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    async function remove(m) {
      try {
        await materialApi.remove(m.id);
        notify.ok('已删除');
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    async function uploadFile(m, file) {
      try {
        const d = await materialApi.uploadFile(m.id, file);
        m.file_url = d.file_url || m.file_url;
        notify.ok('附件已上传');
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    function pickFile(m) {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*,video/*,.pdf,.doc,.docx,.ppt,.pptx,.zip';
      input.onchange = (e) => {
        const f = e.target.files && e.target.files[0];
        if (f) uploadFile(m, f);
      };
      input.click();
    }

    function fileName(url) {
      try { return decodeURIComponent(String(url).split('/').pop().replace(/^[0-9a-f]{32}_/, '')); }
      catch (e) { return url; }
    }

    function isImage(url) { return /\.(png|jpe?g|webp|gif|bmp)(\?|$)/i.test(url || ''); }
    function isVideo(url) { return /\.(mp4|mov|webm|avi|mkv)(\?|$)/i.test(url || ''); }

    onMounted(load);

    return {
      materials, filtered, loading, error, forbidden, filter, dlg, editing, saving, form, importDlg,
      load, openCreate, openEdit, save, toggleEnabled, remove, pickFile, fileName, isImage, isVideo,
      canWriteContent, isAdmin, publicityName, bizLineClass, bizLineName, MATERIAL_CATEGORIES,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">素材库</div>
    <div class="page-sub">素材是内容生成的唯一事实来源。请标注<b>业务线</b>（甲方线 / 渠道线 / 通用）与<b>公开级别</b>（可公开 / 需脱敏 / 仅内部）——「仅内部」素材不会进入 AI 生成上下文，「需脱敏」素材需人工改写后再用。</div>
  </div>
  <div class="row">
    <el-button size="small" @click="importDlg = true">批量导入</el-button>
    <el-button v-if="canWriteContent" size="small" type="primary" @click="openCreate">+ 新增素材</el-button>
    <el-button size="small" @click="load" :loading="loading">刷新</el-button>
  </div>
</div>

<div class="toolbar">
  <el-select v-model="filter.category" placeholder="全部分类" clearable size="small" style="width:140px">
    <el-option v-for="c in MATERIAL_CATEGORIES" :key="c" :label="c" :value="c"></el-option>
  </el-select>
  <el-select v-model="filter.biz_line" placeholder="全部业务线" clearable size="small" style="width:120px">
    <el-option label="甲方线" value="project"/>
    <el-option label="渠道线" value="channel"/>
    <el-option label="通用" value="both"/>
  </el-select>
  <el-select v-model="filter.publicity" placeholder="全部公开级别" clearable size="small" style="width:130px">
    <el-option label="可公开" value="public"/>
    <el-option label="需脱敏" value="masked"/>
    <el-option label="仅内部" value="internal"/>
  </el-select>
  <el-input v-model="filter.keyword" placeholder="搜索标题 / 内容 / 标签" size="small" clearable style="width:200px"></el-input>
  <el-checkbox v-model="filter.onlyEnabled" size="small">只看启用</el-checkbox>
  <span class="muted">共 {{ filtered.length }} / {{ materials.length }} 条</span>
</div>

<div v-if="forbidden" class="page-state">
  <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可查看素材库，请联系管理员。"></el-result>
</div>
<div v-else-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
</div>
<div v-else-if="loading" class="card"><el-skeleton :rows="6" animated /></div>

<template v-else>
  <div v-if="!filtered.length" class="card">
    <div class="state-box"><el-icon><i class="el-icon-folder-opened" /></el-icon>没有符合条件的素材</div>
  </div>

  <div class="card" v-for="m in filtered" :key="m.id">
    <div class="row">
      <b>{{ m.title }}</b>
      <el-tag size="small">{{ m.category }}</el-tag>
      <el-tag size="small" :type="m.publicity === 'public' ? 'success' : (m.publicity === 'masked' ? 'warning' : 'danger')">
        {{ publicityName(m.publicity) }}
      </el-tag>
      <span class="line-tag" :class="bizLineClass(m.biz_line)">{{ bizLineName(m.biz_line) }}</span>
      <el-tag v-if="!m.enabled" size="small" type="info">已停用</el-tag>
      <span v-if="m.tags" class="muted">标签：{{ m.tags }}</span>
    </div>
    <div class="body-pre mt10" style="max-height:110px">{{ m.content }}</div>

    <div v-if="m.file_url" class="mt10">
      <img v-if="isImage(m.file_url)" :src="m.file_url" style="max-width:100%;max-height:200px;border-radius:6px;display:block"/>
      <video v-else-if="isVideo(m.file_url)" :src="m.file_url" controls style="max-width:100%;max-height:240px;border-radius:6px;display:block"></video>
      <a v-else :href="m.file_url" target="_blank">📄 {{ fileName(m.file_url) }}</a>
    </div>

    <div class="row mt10" v-if="canWriteContent">
      <el-button size="small" @click="pickFile(m)">{{ m.file_url ? '替换附件' : '上传附件' }}</el-button>
      <el-button size="small" @click="openEdit(m)">编辑</el-button>
      <el-button size="small" @click="toggleEnabled(m)">{{ m.enabled ? '停用' : '启用' }}</el-button>
      <el-button v-if="isAdmin" size="small" type="danger" @click="remove(m)">删除</el-button>
    </div>
  </div>
</template>

<el-dialog v-model="dlg" :title="form.id ? '编辑素材' : '新增素材'" width="620px">
  <el-form label-width="86px">
    <el-form-item label="分类">
      <el-select v-model="form.category">
        <el-option v-for="c in MATERIAL_CATEGORIES" :key="c" :label="c" :value="c"></el-option>
      </el-select>
    </el-form-item>
    <el-form-item label="业务线">
      <el-select v-model="form.biz_line">
        <el-option label="甲方线" value="project"/>
        <el-option label="渠道线" value="channel"/>
        <el-option label="通用" value="both"/>
      </el-select>
    </el-form-item>
    <el-form-item label="标题"><el-input v-model="form.title" placeholder="素材标题（必填）" maxlength="200" show-word-limit></el-input></el-form-item>
    <el-form-item label="内容">
      <el-input v-model="form.content" type="textarea" :rows="6" placeholder="文字说明；工地实拍可填设备 / 项目背景 / 亮点"></el-input>
    </el-form-item>
    <el-form-item label="标签"><el-input v-model="form.tags" placeholder="标签，逗号分隔"></el-input></el-form-item>
    <el-form-item label="公开级别">
      <el-select v-model="form.publicity">
        <el-option label="可公开" value="public"/>
        <el-option label="需脱敏" value="masked"/>
        <el-option label="仅内部" value="internal"/>
      </el-select>
    </el-form-item>
    <el-form-item label="启用"><el-switch v-model="form.enabled"></el-switch></el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="dlg = false">取消</el-button>
    <el-button type="primary" :loading="saving" @click="save">保存</el-button>
  </template>
</el-dialog>

<el-dialog v-model="importDlg" title="批量导入素材" width="560px">
  <div class="alert-strip warn">
    后端目前<b>没有</b>批量导入接口（《接口缺口清单》GAP-02）。页面内只提供逐条录入 + 单条附件上传；
    一次性导入请由后端同学用 <code>scripts/import_pptx.py</code> 执行（脚本在项目根目录）。
  </div>
  <div class="kv mt10">
    <span class="k">建议流程</span><span>① 按 PPT 一页一素材整理 → ② 逐条新增（分类 / 业务线 / 公开级别必填）→ ③ 一次性补充附件</span>
    <span class="k">必填项</span><span>标题、分类、业务线、公开级别</span>
    <span class="k">导入后检查</span><span>「仅内部」素材不会进入 AI 生成上下文；「需脱敏」素材需人工改写</span>
  </div>
  <template #footer><el-button type="primary" @click="importDlg = false">知道了</el-button></template>
</el-dialog>
`,
};
