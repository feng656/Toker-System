import { ref, reactive, computed, onMounted, onUnmounted } from '../core/vue.js';
import { phase2Api } from '../api/phase2.js';
import { isAdmin } from '../core/store.js';
import { notify, errorMessage } from '../core/ui.js';
import { createQrPoller } from '../core/qr-poller.js';

const newKey = () => window.crypto.randomUUID ? window.crypto.randomUUID() :
  Array.from(window.crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
const statusName = (s) => ({ connected: '已登录', awaiting_scan: '待扫码', expired: '已过期', disconnected: '未登录' }[s] || s);
const categoryName = (s) => ({ video: '视频', text: '图文 / 社区', commerce: '电商', other: '其他' }[s] || '其他');
const qrStatusName = (s) => ({ configured: '可获取平台二维码', unconfigured: '扫码服务待配置', unsupported: '暂未支持扫码', disabled: '已停用' }[s] || s);

export default {
  name: 'PlatformAccounts',
  setup() {
    const accounts = ref([]);
    const platforms = ref([]);
    const loading = ref(false);
    const loadError = ref('');
    const addVisible = ref(false);
    const saving = ref(false);
    const formError = ref('');
    const customMode = ref(false);
    const customBusy = ref(false);
    const search = ref('');
    const form = reactive({ platform_id: null, login_hint: '', label: '', request_key: '' });
    const custom = reactive({ name: '', code: '', category: 'other', login_url: '', request_key: '' });
    const selected = computed(() => platforms.value.find(p => p.id === form.platform_id));
    const filtered = computed(() => platforms.value.filter(p => `${p.name} ${p.code}`.toLowerCase().includes(search.value.toLowerCase().trim())));
    const qrVisible = ref(false);
    const qrBusy = ref(false);
    const qrAccount = ref(null);
    const qrUrl = ref('');
    const qrState = ref('');
    const qrError = ref('');
    const now = ref(Date.now());
    let disposed = false;
    let requestEpoch = 0;
    let clock = null;
    const platformOf = (id) => platforms.value.find(p => p.id === id);
    const qrPlatform = computed(() => platformOf(qrAccount.value?.platform_id));
    const expiryMs = (value) => value ? Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z') : 0;
    const remaining = computed(() => Math.max(0, Math.ceil((expiryMs(qrAccount.value?.qr_expires_at) - now.value) / 1000)));
    const canRetry = computed(() => qrState.value !== 'connected' && !qrBusy.value);

    async function load() {
      loading.value = true;
      loadError.value = '';
      try {
        const [list, catalog] = await Promise.all([phase2Api.wsAccounts(), phase2Api.loginPlatforms()]);
        if (disposed) return;
        accounts.value = list;
        platforms.value = catalog;
      } catch (error) { if (!disposed) loadError.value = errorMessage(error); }
      finally { if (!disposed) loading.value = false; }
    }
    function openAdd() {
      formError.value = '';
      customMode.value = false;
      search.value = '';
      Object.assign(form, { platform_id: null, login_hint: '', label: '', request_key: newKey() });
      Object.assign(custom, { name: '', code: '', category: 'other', login_url: '', request_key: newKey() });
      addVisible.value = true;
      load();
    }
    async function saveCustom() {
      if (customBusy.value) return;
      if (!custom.name.trim()) { formError.value = '请填写平台名称'; return; }
      if (custom.code && !/^[a-z][a-z0-9_-]{0,39}$/.test(custom.code)) { formError.value = '平台标识须为小写字母开头，可包含数字、_和-'; return; }
      customBusy.value = true;
      formError.value = '';
      try {
        const body = { ...custom, name: custom.name.trim(), login_url: custom.login_url.trim() };
        if (!body.code) delete body.code;
        const platform = await phase2Api.addLoginPlatform(body);
        const catalog = await phase2Api.loginPlatforms();
        if (disposed) return;
        platforms.value = catalog;
        form.platform_id = platform.id;
        customMode.value = false;
        search.value = '';
        notify.ok('平台已保存，下次添加账号时仍可选择');
      } catch (error) { formError.value = errorMessage(error); }
      finally { customBusy.value = false; }
    }
    async function saveAccount() {
      if (saving.value) return;
      if (!selected.value || !selected.value.enabled) { formError.value = '请选择一个已启用的平台'; return; }
      if (!form.login_hint.trim()) { formError.value = '请填写平台账号、手机号或账号名称（不需要密码）'; return; }
      saving.value = true;
      formError.value = '';
      try {
        const account = await phase2Api.addWsAccount({ ...form, login_hint: form.login_hint.trim(), label: form.label.trim() || form.login_hint.trim().slice(0, 100) });
        if (disposed) return;
        addVisible.value = false;
        await load();
        if (!disposed) await startQr(account);
      } catch (error) { formError.value = errorMessage(error); }
      finally { saving.value = false; }
    }
    function clearClock() {
      if (clock !== null) window.clearInterval(clock);
      clock = null;
    }
    function closeQr() {
      requestEpoch += 1;
      poller.stop();
      clearClock();
      qrUrl.value = '';
      qrBusy.value = false;
    }
    async function applyState(data) {
      qrAccount.value = data;
      qrState.value = data.status;
      qrUrl.value = data.qr_available ? (data.qr_url || '') : '';
      now.value = Date.now();
      if (data.status === 'connected') {
        poller.stop();
        clearClock();
        qrError.value = '';
        notify.ok('已登录：' + (data.nickname || data.label));
        await load();
      } else if (data.status === 'expired') {
        poller.stop();
        clearClock();
        qrError.value = '二维码已过期，请重新获取后扫码。';
      }
    }
    const poller = createQrPoller({
      refresh: (id) => phase2Api.wsRefresh(id),
      session: (id) => phase2Api.wsSession(id),
      onState: applyState,
      onError: (error) => { qrError.value = '登录状态查询已暂停：' + errorMessage(error); },
      onLimit: () => { qrError.value = '已暂停自动查询，请点击“继续查询”或重新获取二维码。'; },
    });
    function startClock() {
      clearClock();
      clock = window.setInterval(() => {
        now.value = Date.now();
        if (qrState.value === 'awaiting_scan' && !remaining.value) {
          qrState.value = 'expired';
          qrUrl.value = '';
          qrError.value = '二维码已过期，请重新获取。';
          poller.stop();
          clearClock();
        }
      }, 1000);
    }
    async function startQr(account) {
      if (disposed) return;
      closeQr();
      const epoch = requestEpoch;
      qrAccount.value = account;
      qrState.value = 'loading';
      qrError.value = '';
      qrVisible.value = true;
      qrBusy.value = true;
      try {
        await phase2Api.wsLogin(account.id, { login_mode: 'qr', username: account.login_hint || '' });
        if (epoch !== requestEpoch || disposed || !qrVisible.value) return;
        const data = await phase2Api.wsSession(account.id);
        if (epoch !== requestEpoch || disposed || !qrVisible.value) return;
        await applyState(data);
        if (data.status === 'awaiting_scan' && epoch === requestEpoch && qrVisible.value) {
          if (!data.qr_available || !data.qr_url) throw new Error('平台未返回有效二维码，请联系管理员检查扫码服务');
          startClock();
          poller.start(account.id);
        }
      } catch (error) {
        if (epoch !== requestEpoch || disposed) return;
        qrState.value = 'error';
        qrError.value = '账号已保存，但暂时无法获取登录二维码：' + errorMessage(error);
      } finally { if (epoch === requestEpoch && !disposed) qrBusy.value = false; }
    }
    function resumePoll() {
      if (!qrAccount.value || qrState.value !== 'awaiting_scan') return;
      qrError.value = '';
      startClock();
      poller.start(qrAccount.value.id);
    }
    async function refreshAccount(account) {
      try {
        const state = await phase2Api.wsRefresh(account.id);
        notify.info('账号状态：' + statusName(state.status));
        await load();
      } catch (error) { notify.err(errorMessage(error)); }
    }
    async function logout(account) {
      try {
        await window.ElementPlus.ElMessageBox.confirm('确认退出这个平台账号？', '退出平台账号', { type: 'warning' });
        await phase2Api.wsLogout(account.id);
        await load();
      } catch (error) { if (error !== 'cancel' && error !== 'close') notify.err(errorMessage(error)); }
    }
    onMounted(load);
    onUnmounted(() => { disposed = true; closeQr(); });
    return { accounts, platforms, loading, loadError, load, isAdmin, openAdd, addVisible, saving, formError,
      form, selected, filtered, search, customMode, customBusy, custom, saveCustom, saveAccount, platformOf,
      qrVisible, qrBusy, qrAccount, qrUrl, qrState, qrError, remaining, qrPlatform, canRetry,
      startQr, closeQr, resumePoll, refreshAccount, logout, statusName, categoryName, qrStatusName };
  },
  template: `
<section class="card platform-accounts" aria-label="平台账号登录">
  <div class="pa-heading"><div><b>平台账号</b><div class="muted mt6">选择平台 → 填写账号 → 获取平台登录二维码</div></div>
    <div class="row"><el-button v-if="isAdmin()" type="primary" size="small" @click="openAdd">+ 添加账号</el-button><el-button size="small" :loading="loading" @click="load">刷新</el-button></div>
  </div>
  <div v-if="loadError" class="alert-strip error mt10" role="alert">{{ loadError }} <el-button text @click="load">重试</el-button></div>
  <div v-if="!accounts.length && !loading && !loadError" class="state-box">尚未添加账号。支持主流视频、社区、电商平台，也可以保存自定义平台。</div>
  <div v-for="account in accounts" :key="account.id" class="pa-account">
    <div><span class="pa-platform-name">{{ platformOf(account.platform_id)?.name || '平台' }}</span><b>{{ account.label }}</b>
      <div class="muted mt6">{{ account.login_hint || '未填写账号标识' }}<span v-if="account.nickname"> · 已授权：{{ account.nickname }}</span></div></div>
    <div class="row"><el-tag size="small" :type="account.status === 'connected' ? 'success' : 'info'">{{ statusName(account.status) }}</el-tag>
      <el-tag v-if="account.expires_soon" type="warning" size="small">即将过期</el-tag>
      <el-button v-if="account.status !== 'connected'" size="small" text type="primary" @click="startQr(account)">扫码登录</el-button>
      <el-button v-else size="small" text @click="refreshAccount(account)">检查会话</el-button>
      <el-button v-if="account.status === 'connected'" size="small" text type="danger" @click="logout(account)">退出</el-button>
    </div>
  </div>
  <div class="gap-note">平台账号由实际扫码的人授权。填写账号仅用于识别和登录提示；二维码必须由目标平台签发，保存平台不代表已接入扫码服务。</div>
</section>

<el-dialog v-model="addVisible" title="添加平台账号" width="min(720px, 94vw)" :close-on-click-modal="false"
  :show-close="!saving && !customBusy" :close-on-press-escape="!saving && !customBusy" class="pa-dialog">
  <template v-if="!customMode">
    <div class="pa-step">1 · 选择平台</div>
    <el-input v-model="search" placeholder="搜索平台名称，如抖音、淘宝" clearable aria-label="搜索平台" />
    <div class="pa-platform-grid" role="group" aria-label="可选平台">
      <button v-for="p in filtered" :key="p.id" type="button" class="pa-platform-option" :class="{selected: form.platform_id === p.id}"
        :aria-pressed="form.platform_id === p.id" :disabled="!p.enabled" @click="form.platform_id = p.id; formError = ''">
        <strong>{{ p.name }}</strong><small>{{ p.enabled ? categoryName(p.category) : '已停用' }}{{ !p.builtin ? ' · 自定义' : '' }}</small>
      </button>
    </div>
    <div v-if="!filtered.length" class="muted">没有匹配的平台，可以在下方手动添加。</div>
    <div v-if="filtered.some(p => !p.enabled)" class="muted">灰色平台保留原停用状态，可在“设置 → 平台管理”中启用后选择。</div>
    <el-button text type="primary" @click="customMode = true; formError = ''">找不到平台？手动添加并保存</el-button>
    <div class="pa-step">2 · 填写账号</div>
    <el-form label-position="top" @submit.prevent="saveAccount">
      <el-form-item label="平台账号 / 手机号 / 账号名称（必填）"><el-input v-model="form.login_hint" maxlength="200" placeholder="填写账号标识，无需输入密码" autocomplete="off" aria-label="平台账号" /></el-form-item>
      <el-form-item label="备注名称（选填）"><el-input v-model="form.label" maxlength="100" placeholder="如：品牌主号、华东门店" aria-label="账号备注" /></el-form-item>
    </el-form>
    <div v-if="selected" class="gap-note"><b>{{ qrStatusName(selected.qr_status) }}</b> · {{ selected.qr_message }}
      <div v-if="!selected.generation_enabled" class="mt6">添加账号不会自动扩大每日内容生成范围。</div>
    </div>
  </template>
  <template v-else>
    <el-button text @click="customMode = false; formError = ''">← 返回选择平台</el-button>
    <div class="pa-step">添加自定义平台</div>
    <el-form label-position="top" @submit.prevent="saveCustom">
      <el-form-item label="平台名称（必填）"><el-input v-model="custom.name" maxlength="100" placeholder="如：企业内容社区" aria-label="自定义平台名称" /></el-form-item>
      <el-form-item label="分类"><el-select v-model="custom.category" class="pa-full"><el-option label="图文 / 社区" value="text"/><el-option label="视频" value="video"/><el-option label="电商" value="commerce"/><el-option label="其他" value="other"/></el-select></el-form-item>
      <el-form-item label="官方登录入口（选填）"><el-input v-model="custom.login_url" maxlength="700" placeholder="https://平台官方域名/" aria-label="平台登录入口" /></el-form-item>
      <el-form-item label="平台标识（选填，已有适配器时填写约定标识）"><el-input v-model="custom.code" maxlength="40" placeholder="不填则由系统自动创建" aria-label="平台标识" /></el-form-item>
    </el-form>
    <div class="gap-note">保存后全体运营人员可重复选择；默认不参与内容生成。自定义网址仅用作人工打开入口，不会自动接管网页或生成登录凭证。</div>
  </template>
  <div v-if="formError" role="alert" class="alert-strip error mt10">{{ formError }}</div>
  <template #footer><el-button :disabled="saving || customBusy" @click="addVisible = false">取消</el-button>
    <el-button v-if="customMode" type="primary" :loading="customBusy" @click="saveCustom">保存平台并选用</el-button>
    <el-button v-else type="primary" :loading="saving" :disabled="loading" @click="saveAccount">保存账号并获取二维码</el-button>
  </template>
</el-dialog>

<el-dialog v-model="qrVisible" title="平台扫码登录" width="min(440px, 94vw)" :close-on-click-modal="false" @close="closeQr" class="pa-dialog">
  <div class="pa-qr-content">
    <b>{{ qrPlatform?.name || '平台' }} · {{ qrAccount?.label }}</b>
    <div v-if="qrBusy" class="state-box"><el-skeleton :rows="3" animated /><p>正在向平台请求登录二维码…</p></div>
    <template v-else-if="qrState === 'connected'"><el-result icon="success" title="登录成功" :sub-title="'已授权账号：' + (qrAccount.nickname || qrAccount.label)" /></template>
    <template v-else-if="qrUrl && qrState === 'awaiting_scan'">
      <img :src="qrUrl" :alt="(qrPlatform?.name || '平台') + '登录二维码'" class="pa-qr-image" @error="qrError = '二维码图片加载失败，请检查存储服务后重试'" />
      <p>请使用 {{ qrPlatform?.name }} 手机端扫码，并在手机上确认登录。</p>
      <div class="muted">剩余 {{ remaining }} 秒 · 扫码人决定实际授权账号</div>
    </template>
    <div v-else class="state-box">{{ qrState === 'expired' ? '二维码已过期' : '暂未取得登录二维码' }}</div>
    <div v-if="qrError" class="alert-strip warn mt10" role="alert">{{ qrError }}</div>
    <div v-if="qrPlatform?.login_url" class="mt10"><a :href="qrPlatform.login_url" target="_blank" rel="noopener noreferrer">打开平台官方入口</a><div class="muted mt6">仅打开网页，不会自动保存本系统的登录会话。</div></div>
  </div>
  <template #footer><el-button @click="qrVisible = false">关闭</el-button>
    <el-button v-if="qrError && qrState === 'awaiting_scan'" @click="resumePoll">继续查询</el-button>
    <el-button v-if="canRetry" type="primary" @click="startQr(qrAccount)">{{ qrState === 'expired' ? '重新获取二维码' : '重试获取二维码' }}</el-button>
  </template>
</el-dialog>
`,
};
