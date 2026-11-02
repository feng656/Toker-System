/**
 * 工作台：内容审核确认 + 平台通道 + 数据速览。
 * 运营日常主入口：左侧看待确认内容，右侧扫码登录平台后台，复制文案 → 人工发布 → 回填链接。
 */
import { ref, reactive, computed, onMounted, onUnmounted } from '../core/vue.js';
import { contentApi } from '../api/content.js';
import { platformApi } from '../api/platform.js';
import { dashboardApi } from '../api/business.js';
import { createAsyncState, notify, errorMessage } from '../core/ui.js';
import {
  platformName, composeCopyText, copyText, PLATFORM_HOME, bizLineClass, bizLineName,
} from '../core/format.js';

export default {
  name: 'PageWork',
  setup() {
    const items = ref([]);
    const loading = ref(false);
    const error = ref('');
    const busy = reactive({});

    const funnel = reactive({ published: 0, views: 0, interactions: 0, leads: 0, high_intent: 0 });
    const platStatus = ref([]);
    const platMode = reactive({});

    const selPlatform = ref('gzh');
    const brImg = ref('');
    const brLogged = ref(false);
    const brLoading = ref(false);
    const brError = ref('');

    let timer = null;

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

    async function copyAndOpen(v) {
      const ok = await copyText(composeCopyText(v));
      const home = PLATFORM_HOME[v.platform];
      if (home) {
        window.open(home, '_blank');
        notify.ok(ok ? `文案已复制，${platformName(v.platform)}后台已打开` : `已打开${platformName(v.platform)}后台，请手动复制文案`);
      } else {
        notify.ok(ok ? '文案已复制' : '复制失败，请手动选择文案');
      }
    }

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

    onMounted(async () => {
      await loadAll();
      openBrowser();
      timer = window.setInterval(() => {
        if (!brLogged.value && brImg.value) refreshShot();
      }, 4000);
    });
    onUnmounted(() => { if (timer) window.clearInterval(timer); });

    const pendingCount = computed(() => items.value.filter((i) => i.confirm_status === 'pending').length);

    return {
      items, loading, error, busy, funnel, platStatus, platMode,
      selPlatform, brImg, brLogged, brLoading, brError,
      pendingCount, loadAll, openBrowser, copyAndOpen, confirmPublish, reject,
      platformName, bizLineClass, bizLineName,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">今日内容工作台</div>
    <div class="page-sub">AI 已生成内容并完成质检（合规硬检 + 质量打分）。你只需确认内容合不合适，复制文案到平台人工发布，再回到「今日待办」回填发布链接。</div>
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
  <div class="wk-wrap" style="display:flex;gap:18px;align-items:flex-start">
    <div style="flex:1;min-width:0">
      <div class="alert-strip info">待确认 {{ pendingCount }} 条 · 合计 {{ items.length }} 条未发布。发布量口径：只有回填了有效发布链接的版本才计入「已发布」。</div>

      <div class="card" v-for="v in items" :key="v.id">
        <div class="row">
          <span class="pf" :class="'pf-' + v.platform">{{ platformName(v.platform) }}</span>
          <span class="line-tag" :class="bizLineClass(v.biz_line)">{{ bizLineName(v.biz_line) }}</span>
          <b>{{ v.content_title }}</b>
          <span class="muted" v-if="v.quality_score">质量分 {{ v.quality_score }}</span>
          <el-tag v-if="v.publish_status === 'published'" size="small" type="success">已发布</el-tag>
          <el-tag v-else-if="v.publish_status === 'failed'" size="small" type="danger">发布失败</el-tag>
          <el-tag v-if="v.confirm_status === 'pending'" size="small" type="warning">待确认</el-tag>
        </div>
        <div class="body-pre mt10">{{ v.body }}</div>
        <div v-if="v.hashtags" class="muted mt6">{{ v.hashtags }}</div>
        <div v-if="!v.compliance_ok" class="alert-strip error mt10">⚠ 命中合规红线：{{ v.compliance_hits }}，请修改后再发布（红线命中不可直接放行）。</div>
        <div v-if="v.publish_error" class="alert-strip warn mt10">发布失败：{{ v.publish_error }}</div>
        <div class="row mt14">
          <el-button v-if="v.confirm_status === 'pending'" size="small" type="success"
                     :loading="busy[v.id]" @click="confirmPublish(v)">确认发布</el-button>
          <el-button v-if="v.confirm_status === 'pending'" size="small" @click="reject(v)">驳回</el-button>
          <el-button size="small" @click="copyAndOpen(v)">复制文案并打开{{ platformName(v.platform) }}后台</el-button>
        </div>
      </div>

      <div v-if="!items.length" class="card">
        <div class="state-box">
          <el-icon><i class="el-icon-document" /></el-icon>
          暂无待处理内容。生成入口在「今日待办」，或等每日 08:00 定时任务生成。
        </div>
      </div>
    </div>

    <div style="width:460px;flex-shrink:0">
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <b>平台登录</b>
          <span class="muted">扫码一次，长期有效</span>
        </div>
        <el-radio-group v-model="selPlatform" style="width:100%;display:flex;gap:6px;margin:12px 0" @change="openBrowser">
          <el-radio-button value="gzh" style="flex:1">公众号</el-radio-button>
          <el-radio-button value="douyin" style="flex:1">抖音</el-radio-button>
          <el-radio-button value="shipinhao" style="flex:1">视频号</el-radio-button>
          <el-radio-button value="xhs" style="flex:1">小红书</el-radio-button>
        </el-radio-group>
        <div style="position:relative;min-height:300px;background:#fafbfc;border:1px solid #ebeef5;border-radius:8px;display:flex;align-items:center;justify-content:center;overflow:hidden">
          <img v-if="brImg" :src="'data:image/png;base64,' + brImg" style="width:100%;display:block" />
          <div v-if="brLoading" style="color:#909399;font-size:13px">加载中…</div>
          <div v-if="brError" style="color:#f56c6c;font-size:13px;padding:16px;text-align:center">{{ brError }}</div>
          <div v-if="!brImg && !brLoading && !brError" style="color:#c0c4cc;font-size:13px">点击上方平台标签打开后台窗口</div>
          <div v-if="brLogged" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.7)">
            <span style="background:#67c23a;color:#fff;padding:8px 20px;border-radius:20px;font-size:14px;font-weight:600">✓ 已登录，可直接发布</span>
          </div>
        </div>
        <div class="row mt10" style="justify-content:space-between">
          <el-tag v-if="!brLogged" size="small" type="warning">未登录，请用微信扫码</el-tag>
          <el-tag v-else size="small" type="success">已登录</el-tag>
          <el-button size="small" text type="primary" @click="openBrowser">刷新画面</el-button>
        </div>
        <div class="gap-note">公众号等平台要求扫码 + 二次确认，自动发布能否走通取决于平台凭据是否已配置（见「设置」）。一期以人工发布为准。</div>
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
`,
};
