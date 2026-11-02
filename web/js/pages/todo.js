/**
 * 今日待办：按日期查看待发布内容 → 复制文案 → 人工发布 → 回填发布链接 → 上传数据截图。
 * 完成标志（《分工》4.2）：运营可按日期完成待办，未回填链接不显示为已发布。
 */
import { ref, reactive, computed, onMounted } from '../core/vue.js';
import { contentApi } from '../api/content.js';
import { platformApi } from '../api/platform.js';
import { notify, errorMessage } from '../core/ui.js';
import {
  platformName, bizLineClass, bizLineName, composeCopyText, copyText,
  validatePublishUrl, todayStr, contentStatusName,
} from '../core/format.js';
import { canWriteContent } from '../core/store.js';

export default {
  name: 'PageTodo',
  setup() {
    const date = ref(todayStr());
    const items = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);
    const urlDraft = reactive({});
    const busy = reactive({});
    const genBusy = ref(false);
    const genInfo = ref('');
    const shotResult = reactive({});

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        if (date.value === todayStr()) {
          const d = await contentApi.todoToday();
          items.value = d.pending || [];
        } else {
          // 后端 /todo/today 只返回今天；其他日期用内容明细派生（GAP-04）
          const list = await contentApi.list({ scheduled: date.value });
          const out = [];
          (list || []).forEach((c) => {
            if (['draft', 'approved'].indexOf(c.status) < 0) return;
            (c.variants || []).forEach((v) => {
              if (!v.published_url) {
                out.push({ ...v, content_id: c.id, content_title: c.title, biz_line: c.biz_line, status: c.status });
              }
            });
          });
          items.value = out;
        }
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
        items.value = [];
      } finally {
        loading.value = false;
      }
    }

    async function doCopy(v) {
      const ok = await copyText(composeCopyText(v));
      notify[ok ? 'ok' : 'err'](ok ? '文案已复制，可直接粘贴到平台' : '复制失败，请手动选择文案');
    }

    async function submitUrl(v) {
      const raw = urlDraft[v.id];
      const check = validatePublishUrl(raw);
      if (!check.ok) {
        notify.err(check.message);
        return;
      }
      busy[v.id] = true;
      try {
        await contentApi.publish(v.id, raw.trim());
        notify.ok('已回填发布链接，该版本计入已发布');
        delete urlDraft[v.id];
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        busy[v.id] = false;
      }
    }

    async function uploadShot(v, kind) {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.onchange = async (e) => {
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        busy[v.id] = true;
        try {
          const d = await platformApi.uploadScreenshot(kind, v.id, f);
          shotResult[v.id] = d && d.url;
          notify.warn('截图已上传。OCR 识别尚未接入（GAP-09），请到「数据看板」手工录入数据。');
        } catch (e) {
          notify.err(errorMessage(e));
        } finally {
          busy[v.id] = false;
        }
      };
      input.click();
    }

    async function generate() {
      genBusy.value = true;
      genInfo.value = '';
      try {
        const d = await contentApi.generateDaily();
        genInfo.value = d.msg || '已触发生成';
        notify.ok(d.msg || '已触发生成');
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        genBusy.value = false;
      }
    }

    async function pollGen() {
      try {
        const s = await contentApi.generationStatus();
        if (s && s.last && !s.last.error) {
          genInfo.value = `上次生成：${s.last.count || 0} 条 · ${(s.last.titles || []).join('、') || '-'}`;
        } else if (s && s.last && s.last.error) {
          genInfo.value = `上次生成失败：${s.last.error}`;
        }
      } catch (e) { /* 忽略 */ }
    }

    const pendingCount = computed(() => items.value.length);

    onMounted(async () => {
      await load();
      await pollGen();
    });

    return {
      date, items, loading, error, forbidden, urlDraft, busy, genBusy, genInfo, shotResult,
      pendingCount, load, doCopy, submitUrl, uploadShot, generate, pollGen,
      canWriteContent, platformName, bizLineClass, bizLineName, contentStatusName, todayStr,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">今日待办（{{ pendingCount }} 条待处理）</div>
    <div class="page-sub">按日期查看当天应发布的内容。发布链路：复制文案 → 到平台人工发布 → 回到这里粘贴链接并「确认回填」。<b>未回填链接的条目不会显示为已发布，也不计入发布量。</b></div>
  </div>
  <div class="row">
    <el-date-picker v-model="date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" @change="load"></el-date-picker>
    <el-button size="small" @click="load" :loading="loading">刷新</el-button>
    <el-button v-if="canWriteContent" size="small" type="primary" @click="generate" :loading="genBusy">生成明日内容包</el-button>
  </div>
</div>

<div v-if="genInfo" class="alert-strip info">{{ genInfo }}</div>

<div v-if="forbidden" class="page-state">
  <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可查看今日待办，请联系管理员调整角色。"></el-result>
</div>

<div v-else-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
</div>

<div v-else-if="loading" class="card"><el-skeleton :rows="6" animated /></div>

<template v-else>
  <div class="card" v-for="v in items" :key="v.id">
    <div class="row">
      <span class="pf" :class="'pf-' + v.platform">{{ platformName(v.platform) }}</span>
      <span class="line-tag" :class="bizLineClass(v.biz_line)">{{ bizLineName(v.biz_line) }}</span>
      <b>{{ v.content_title }}</b>
      <el-tag size="small" type="info">{{ contentStatusName(v.status) }}</el-tag>
      <span class="muted right">建议 {{ v.best_time || '18:00-20:00' }} 发布</span>
    </div>
    <div class="body-pre mt10">{{ v.body }}</div>
    <div v-if="v.hashtags" class="muted mt6">{{ v.hashtags }}</div>
    <div v-if="!v.compliance_ok" class="alert-strip error mt10">⚠ 命中合规红线：{{ v.compliance_hits }}，请修改后再发布。</div>
    <div v-if="shotResult[v.id]" class="alert-strip ok mt10">截图已上传：{{ shotResult[v.id] }}（OCR 未接入，请手工录入指标）</div>

    <div class="row mt14">
      <el-button size="small" @click="doCopy(v)">复制文案</el-button>
      <el-input v-model="urlDraft[v.id]" size="small" style="width:320px"
                placeholder="发布后粘贴链接（http/https 开头）"></el-input>
      <el-button size="small" type="success" :loading="busy[v.id]" @click="submitUrl(v)">确认回填</el-button>
      <el-dropdown size="small" @command="(c) => uploadShot(v, c)">
        <el-button size="small">上传截图<el-icon style="margin-left:4px"><i class="el-icon-arrow-down" /></el-icon></el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="metrics">数据截图（曝光/点赞）</el-dropdown-item>
            <el-dropdown-item command="comments">评论截图</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
    <div v-if="v.published_url" class="alert-strip ok mt10">
      已发布：<a :href="v.published_url" target="_blank">{{ v.published_url }}</a>
    </div>
  </div>

  <div v-if="!items.length" class="card">
    <div class="state-box">
      <el-icon><i class="el-icon-circle-check" /></el-icon>
      {{ date === todayStr() ? '今日内容已全部发布 🎉' : '该日期没有待发布内容' }}
    </div>
  </div>
</template>
`,
};
