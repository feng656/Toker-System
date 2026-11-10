/**
 * 设置：角色可见范围、平台发布模式说明；管理员另可管理平台凭据、合规红线与用户。
 * 完成标志（《分工》4.2）：不会把实验能力误认为一期必需能力。
 */
import { ref, reactive, onMounted } from '../core/vue.js';
import { platformApi } from '../api/platform.js';
import { phase2Api } from '../api/phase2.js';
import { ruleApi } from '../api/library.js';
import { authApi } from '../api/auth.js';
import { notify, errorMessage } from '../core/ui.js';
import { platformName, PLATFORM_HOME } from '../core/format.js';
import { session, isAdmin, PAGE_ROLES } from '../core/store.js';

const ROLE_VISIBLE = {
  admin: '全部页面 + 平台凭据 / 合规红线 / 用户管理',
  operator: '工作台、今日待办、内容管理、素材库、选题池、线索看板、数据看板、设置与帮助',
  sales: '线索看板、数据看板、设置与帮助',
};

export default {
  name: 'PageSettings',
  setup() {
    const platStatus = ref([]);
    const accounts = ref([]);
    const rules = ref([]);
    const users = ref([]);
    const loading = ref(false);
    const error = ref('');
    const forbidden = ref(false);

    const accForm = reactive({
      gzh: { appid: '', appsecret: '' },
      douyin: { appid: '', appsecret: '', open_id: '' },
      xhs: { appid: '', appsecret: '' },
      shipinhao: { appid: '', appsecret: '' },
    });
    const ruleForm = reactive({ rule_type: 'forbidden', pattern: '', note: '' });
    const userForm = reactive({ username: '', password: '', name: '', role: 'operator' });

    /* ---- 二期：动态平台（R1） ---- */
    const platforms = ref([]);
    const pfTemplates = ref([]);
    const pfDlg = ref(false);
    const pfSaving = ref(false);
    const pfForm = reactive({ id: null, code: '', name: '', category: 'text', publish_mode: 'manual', default_time: '18:00-20:00', style_prompt: '', enabled: true, expected_version: null });

    /* ---- 二期：AI 供应商（R9） ---- */
    const providers = ref([]);
    const provDlg = ref(false);
    const provSaving = ref(false);
    const provTesting = reactive({});
    const provForm = reactive({ id: null, name: '', capability: 'text', endpoint: '', model: '', key_env: '', priority: 100, enabled: true, expected_version: null });

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        const st = await platformApi.status();
        platStatus.value = st || [];
        if (isAdmin()) {
          const [acc, rl, us, pfs, provs] = await Promise.all([
            platformApi.list().catch(() => []),
            ruleApi.list().catch(() => []),
            authApi.listUsers().catch(() => []),
            phase2Api.platforms().catch(() => []),
            phase2Api.providers().catch(() => []),
          ]);
          accounts.value = acc || [];
          rules.value = rl || [];
          users.value = us || [];
          platforms.value = pfs || [];
          providers.value = provs || [];
          accounts.value.forEach((a) => {
            if (accForm[a.platform]) {
              accForm[a.platform].appid = a.appid || '';
              if (a.extra && a.extra.open_id) accForm[a.platform].open_id = a.extra.open_id;
            }
          });
        }
      } catch (e) {
        error.value = errorMessage(e);
        forbidden.value = !!(e && e.forbidden);
      } finally {
        loading.value = false;
      }
    }

    async function saveAccount(pf) {
      const f = accForm[pf];
      try {
        await platformApi.save({
          platform: pf,
          appid: f.appid,
          appsecret: f.appsecret,
          extra: { open_id: f.open_id || '' },
          enabled: true,
        });
        notify.ok(`${platformName(pf)} 凭据已保存`);
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    async function addRule() {
      if (!ruleForm.pattern.trim()) { notify.err('请填写匹配词'); return; }
      try {
        await ruleApi.create({ rule_type: ruleForm.rule_type, pattern: ruleForm.pattern.trim(), note: ruleForm.note });
        notify.ok('已新增红线');
        ruleForm.pattern = '';
        ruleForm.note = '';
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    async function removeRule(r) {
      try {
        await ruleApi.remove(r.id);
        notify.ok('已删除');
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    async function addUser() {
      if (!userForm.username.trim() || !userForm.password) {
        notify.err('账号与密码为必填');
        return;
      }
      try {
        await authApi.createUser({ ...userForm, username: userForm.username.trim() });
        notify.ok('已创建用户');
        Object.assign(userForm, { username: '', password: '', name: '', role: 'operator' });
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    /* ---- 二期：动态平台管理（R1） ---- */
    async function loadTemplates() {
      try { pfTemplates.value = await phase2Api.platformTemplates() || []; } catch (e) { pfTemplates.value = []; }
    }

    function openPfAdd() {
      Object.assign(pfForm, { id: null, code: '', name: '', category: 'text', publish_mode: 'manual', default_time: '18:00-20:00', style_prompt: '', enabled: true, expected_version: null });
      loadTemplates();
      pfDlg.value = true;
    }

    function openPfEdit(p) {
      Object.assign(pfForm, { id: p.id, code: p.code, name: p.name, category: p.category, publish_mode: p.publish_mode, default_time: p.default_time, style_prompt: p.style_prompt, enabled: p.enabled, expected_version: p.version });
      pfDlg.value = true;
    }

    function pickTemplate(t) {
      pfForm.code = t.code;
      pfForm.name = t.name;
      pfForm.category = t.category;
      pfForm.style_prompt = t.style_prompt || '';
    }

    async function savePlatform() {
      if (!pfForm.code.trim() || !pfForm.name.trim()) { notify.err('平台 code 与名称必填'); return; }
      pfSaving.value = true;
      try {
        const body = {
          code: pfForm.code.trim().toLowerCase(), name: pfForm.name.trim(), icon: '', category: pfForm.category,
          publish_mode: pfForm.publish_mode, default_time: pfForm.default_time, style_prompt: pfForm.style_prompt,
          enabled: pfForm.enabled, expected_version: pfForm.expected_version,
        };
        if (pfForm.id) await phase2Api.editPlatform(pfForm.id, body);
        else await phase2Api.addPlatform(body);
        notify.ok('平台已保存');
        pfDlg.value = false;
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        pfSaving.value = false;
      }
    }

    async function togglePlatform(p) {
      try {
        await phase2Api.editPlatform(p.id, {
          code: p.code, name: p.name, icon: p.icon || '', category: p.category,
          publish_mode: p.publish_mode, default_time: p.default_time, style_prompt: p.style_prompt || '',
          enabled: !p.enabled, expected_version: p.version,
        });
        notify.ok(p.enabled ? '已停用' : '已启用');
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      }
    }

    const pfModeName = (m) => ({ manual: '人工复制', sandbox: '沙盒发布', api: 'API 直发' }[m] || m);
    const pfCatName = (c) => ({ text: '图文', video: '短视频', commerce: '电商', other: '其它' }[c] || c);

    /* ---- 二期：AI 供应商（R9） ---- */
    function openProvAdd() {
      Object.assign(provForm, { id: null, name: '', capability: 'text', endpoint: '', model: '', key_env: '', priority: 100, enabled: true, expected_version: null });
      provDlg.value = true;
    }

    async function saveProvider() {
      if (!provForm.name.trim() || !provForm.endpoint.trim() || !provForm.model.trim()) {
        notify.err('名称、接口地址与模型名必填'); return;
      }
      provSaving.value = true;
      try {
        const body = {
          name: provForm.name.trim(), capability: provForm.capability, endpoint: provForm.endpoint.trim(),
          model: provForm.model.trim(), key_env: provForm.key_env.trim(), priority: Number(provForm.priority) || 100,
          enabled: provForm.enabled, expected_version: provForm.expected_version,
        };
        await phase2Api.addProvider(body);
        notify.ok('AI 供应商已添加');
        provDlg.value = false;
        await load();
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        provSaving.value = false;
      }
    }

    async function testProvider(p) {
      provTesting[p.id] = true;
      try {
        const d = await phase2Api.testProvider(p.id);
        if (d && d.ok) notify.ok('连接成功（环境密钥校验通过）');
        else notify.warn(d && d.detail ? d.detail : '连接失败，详见 AI 日志');
      } catch (e) {
        notify.err(errorMessage(e));
      } finally {
        provTesting[p.id] = false;
      }
    }

    onMounted(load);

    return {
      platStatus, accounts, rules, users, loading, error, forbidden,
      accForm, ruleForm, userForm, load, saveAccount, addRule, removeRule, addUser,
      platformName, PLATFORM_HOME, isAdmin, session, ROLE_VISIBLE, PAGE_ROLES,
      platforms, pfTemplates, pfDlg, pfSaving, pfForm,
      openPfAdd, openPfEdit, pickTemplate, savePlatform, togglePlatform, pfModeName, pfCatName,
      providers, provDlg, provSaving, provForm, provTesting,
      openProvAdd, saveProvider, testProvider,
    };
  },
  template: `
<div class="page-head">
  <div>
    <div class="page-title">设置</div>
    <div class="page-sub">当前角色：<b>{{ session.user.name }}（{{ session.user.role }}）</b>。本页只展示与你的角色相关的内容：平台发布模式对所有人可见，凭据 / 红线 / 用户管理仅管理员可见。</div>
  </div>
  <div class="row"><el-button size="small" @click="load" :loading="loading">刷新</el-button></div>
</div>

<div v-if="forbidden" class="page-state">
  <el-result icon="warning" title="没有访问权限" sub-title="当前角色不可访问设置页。"></el-result>
</div>
<div v-else-if="error" class="alert-strip error">
  加载失败：{{ error }}
  <el-button size="small" text type="danger" @click="load" style="margin-left:8px">重试</el-button>
</div>
<div v-else-if="loading" class="card"><el-skeleton :rows="6" animated /></div>

<template v-else>
  <div class="card">
    <h4 class="card-title">角色可见范围</h4>
    <div class="kv">
      <span class="k">管理员</span><span>{{ ROLE_VISIBLE.admin }}</span>
      <span class="k">运营</span><span>{{ ROLE_VISIBLE.operator }}</span>
      <span class="k">销售</span><span>{{ ROLE_VISIBLE.sales }}</span>
    </div>
  </div>

  <div class="card">
    <h4 class="card-title">平台发布模式</h4>
    <el-table :data="platStatus" size="small" empty-text="暂无平台信息">
      <el-table-column label="平台" width="110">
        <template #default="s"><span class="pf" :class="'pf-' + s.row.platform">{{ platformName(s.row.platform) }}</span></template>
      </el-table-column>
      <el-table-column label="模式" width="140">
        <template #default="s">
          <el-tag size="small" :type="s.row.mode === 'auto' ? 'success' : 'info'">
            {{ s.row.mode === 'auto' ? '可自动发布' : '人工发布（复制文案）' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="后台地址" min-width="220">
        <template #default="s">
          <a v-if="s.row.home" :href="s.row.home" target="_blank">{{ s.row.home }}</a>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="说明" min-width="260">
        <template #default="s">
          <span class="muted">
            {{ s.row.mode === 'auto' ? '已配置官方接口凭据，运营点确认后可由系统推送。' : '未配置凭据或平台不支持，运营需复制文案到后台人工发布并回填链接。' }}
          </span>
        </template>
      </el-table-column>
    </el-table>
    <div class="gap-note">一期以半自动发布为验收口径：平台账号 / 凭据未到位不阻塞验收，操作方式为「复制文案 → 人工发布 → 回填链接」。</div>
  </div>

  <template v-if="isAdmin">
    <div class="card">
      <h4 class="card-title">平台凭据（管理员）</h4>
      <div class="grid3">
        <div v-for="pf in ['gzh', 'douyin', 'shipinhao', 'xhs']" :key="pf">
          <div class="row" style="margin-bottom:6px">
            <span class="pf" :class="'pf-' + pf">{{ platformName(pf) }}</span>
            <el-tag v-if="accounts.find(a => a.platform === pf && a.configured)" size="small" type="success">已配置</el-tag>
            <el-tag v-else size="small" type="info">未配置</el-tag>
          </div>
          <el-input v-model="accForm[pf].appid" size="small" :placeholder="pf === 'douyin' ? 'client_key' : 'AppID'" style="margin-bottom:6px"></el-input>
          <el-input v-model="accForm[pf].appsecret" size="small" type="password" show-password placeholder="AppSecret / client_secret" style="margin-bottom:6px"></el-input>
          <el-input v-if="pf === 'douyin'" v-model="accForm[pf].open_id" size="small" placeholder="授权后的 open_id" style="margin-bottom:6px"></el-input>
          <el-button size="small" type="primary" @click="saveAccount(pf)">保存{{ platformName(pf) }}凭据</el-button>
        </div>
      </div>
      <div class="gap-note">公众号需先完成企业认证并把服务器 IP 加入白名单，否则官方接口调用会失败（属于平台侧前置条件，非系统缺陷）。</div>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h4 class="card-title" style="margin:0">发布平台（二期 · 动态扩展）</h4>
        <el-button size="small" type="primary" @click="openPfAdd">+ 添加平台</el-button>
      </div>
      <div class="muted" style="margin:6px 0 10px">不再固定四个平台：可添加淘宝、小红书、快手等任意平台，参与内容生成、待办与看板统计。</div>
      <el-table :data="platforms" size="small" empty-text="暂无平台">
        <el-table-column label="平台" min-width="130">
          <template #default="s">
            <span class="pf" :class="'pf-' + s.row.code">{{ s.row.name }}</span>
            <span class="muted tiny">（{{ s.row.code }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="90">
          <template #default="s"><el-tag size="small" type="info">{{ pfCatName(s.row.category) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="发布方式" width="100">
          <template #default="s"><span>{{ pfModeName(s.row.publish_mode) }}</span></template>
        </el-table-column>
        <el-table-column prop="default_time" label="默认时段" width="110"></el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="s">
            <el-tag size="small" :type="s.row.enabled ? 'success' : 'info'">{{ s.row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="s">
            <el-button size="small" text type="primary" @click="openPfEdit(s.row)">编辑</el-button>
            <el-button size="small" text :type="s.row.enabled ? 'warning' : 'success'" @click="togglePlatform(s.row)">
              {{ s.row.enabled ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h4 class="card-title" style="margin:0">AI 供应商（二期 · 文案/评论/视频）</h4>
        <el-button size="small" type="primary" @click="openProvAdd">+ 添加 AI</el-button>
      </div>
      <div class="muted" style="margin:6px 0 10px">
        可接入任意 OpenAI 兼容服务（DeepSeek / 通义 / 豆包等）。密钥以环境变量引用（TOKER_AI_KEY_*），不落库；配置完成后可一键测试连通。
      </div>
      <el-table :data="providers" size="small" empty-text="暂无 AI 供应商，生成将使用演示替身">
        <el-table-column prop="name" label="名称" min-width="120"></el-table-column>
        <el-table-column label="能力" width="80">
          <template #default="s"><el-tag size="small" :type="s.row.capability === 'video' ? 'warning' : 'primary'">{{ s.row.capability === 'video' ? '视频' : '文本' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="model" label="模型" width="140"></el-table-column>
        <el-table-column prop="endpoint" label="接口地址" min-width="220" show-overflow-tooltip></el-table-column>
        <el-table-column prop="priority" label="优先级" width="80"></el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="s">
            <el-tag size="small" :type="s.row.enabled ? 'success' : 'info'">{{ s.row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="s">
            <el-button v-if="s.row.capability === 'text'" size="small" text type="primary" :loading="provTesting[s.row.id]" @click="testProvider(s.row)">测试</el-button>
            <span v-else class="muted tiny">任务实测</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card">
      <h4 class="card-title">合规红线（管理员）</h4>
      <div class="row mb10">
        <el-select v-model="ruleForm.rule_type" size="small" style="width:130px">
          <el-option label="禁用词 forbidden" value="forbidden"/>
          <el-option label="广告法 ad_law" value="ad_law"/>
          <el-option label="必需口径 required" value="required"/>
        </el-select>
        <el-input v-model="ruleForm.pattern" size="small" placeholder="匹配词" style="width:160px"></el-input>
        <el-input v-model="ruleForm.note" size="small" placeholder="说明（例：渠道价盘保护）" style="width:220px"></el-input>
        <el-button size="small" type="primary" @click="addRule">新增规则</el-button>
      </div>
      <el-table :data="rules" size="small" empty-text="暂无规则">
        <el-table-column prop="rule_type" label="类型" width="110"></el-table-column>
        <el-table-column prop="pattern" label="匹配词" width="160"></el-table-column>
        <el-table-column prop="note" label="说明"></el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="s"><el-button size="small" text type="danger" @click="removeRule(s.row)">删除</el-button></template>
        </el-table-column>
      </el-table>
      <div class="gap-note">forbidden / ad_law 命中即判为红线，内容会被标记为不可发布；required 表示口径要求，后端当前未据此拦截（GAP-15）。</div>
    </div>

    <div class="card">
      <h4 class="card-title">用户管理（管理员）</h4>
      <div class="row mb10">
        <el-input v-model="userForm.username" size="small" placeholder="账号" style="width:130px"></el-input>
        <el-input v-model="userForm.password" size="small" type="password" placeholder="初始密码" style="width:130px"></el-input>
        <el-input v-model="userForm.name" size="small" placeholder="姓名" style="width:120px"></el-input>
        <el-select v-model="userForm.role" size="small" style="width:110px">
          <el-option label="运营" value="operator"/>
          <el-option label="销售" value="sales"/>
          <el-option label="管理员" value="admin"/>
        </el-select>
        <el-button size="small" type="primary" @click="addUser">创建用户</el-button>
      </div>
      <el-table :data="users" size="small" empty-text="暂无用户">
        <el-table-column prop="username" label="账号" width="140"></el-table-column>
        <el-table-column prop="name" label="姓名" width="140"></el-table-column>
        <el-table-column prop="role" label="角色" width="120"></el-table-column>
      </el-table>
    </div>
  </template>

  <el-dialog v-model="pfDlg" :title="pfForm.id ? '编辑平台' : '添加平台'" width="600px">
    <el-form label-width="90px">
      <el-form-item label="快捷模板">
        <el-select v-if="!pfForm.id" placeholder="选择主流平台模板，可再修改" style="width:100%" @change="pickTemplate">
          <el-option v-for="t in pfTemplates" :key="t.code" :label="t.name + '（' + t.code + '）'" :value="t"></el-option>
        </el-select>
        <span v-else class="muted">编辑模式不提供模板切换</span>
      </el-form-item>
      <el-form-item label="平台 code">
        <el-input v-model="pfForm.code" placeholder="小写字母开头，如 taobao / xiaohongshu" :disabled="!!pfForm.id"></el-input>
      </el-form-item>
      <el-form-item label="名称"><el-input v-model="pfForm.name" placeholder="如 淘宝"></el-input></el-form-item>
      <el-form-item label="分类">
        <el-select v-model="pfForm.category" style="width:100%">
          <el-option label="图文" value="text"/>
          <el-option label="短视频" value="video"/>
          <el-option label="电商" value="commerce"/>
          <el-option label="其它" value="other"/>
        </el-select>
      </el-form-item>
      <el-form-item label="发布方式">
        <el-select v-model="pfForm.publish_mode" style="width:100%">
          <el-option label="人工复制发布" value="manual"/>
          <el-option label="沙盒模拟发布" value="sandbox"/>
          <el-option label="API 直发" value="api"/>
        </el-select>
      </el-form-item>
      <el-form-item label="默认时段"><el-input v-model="pfForm.default_time" placeholder="18:00-20:00"></el-input></el-form-item>
      <el-form-item label="风格提示词">
        <el-input v-model="pfForm.style_prompt" type="textarea" :rows="3" placeholder="该平台文案风格要求，AI 生成时使用"></el-input>
      </el-form-item>
      <el-form-item label="启用"><el-switch v-model="pfForm.enabled"></el-switch></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="pfDlg = false">取消</el-button>
      <el-button type="primary" :loading="pfSaving" @click="savePlatform">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="provDlg" title="添加 AI 供应商" width="600px">
    <el-form label-width="110px">
      <el-form-item label="名称"><el-input v-model="provForm.name" placeholder="如 DeepSeek 主用"></el-input></el-form-item>
      <el-form-item label="能力">
        <el-select v-model="provForm.capability" style="width:100%">
          <el-option label="文本（文案/评论/私信）" value="text"/>
          <el-option label="视频生成" value="video"/>
        </el-select>
      </el-form-item>
      <el-form-item label="接口地址"><el-input v-model="provForm.endpoint" placeholder="https://api.deepseek.com/v1（需在服务器白名单内）"></el-input></el-form-item>
      <el-form-item label="模型名"><el-input v-model="provForm.model" placeholder="deepseek-chat / 服务商模型 ID"></el-input></el-form-item>
      <el-form-item label="密钥环境变量">
        <el-input v-model="provForm.key_env" placeholder="TOKER_AI_KEY_TEXT 或 TOKER_AI_KEY_VIDEO"></el-input>
        <div class="muted tiny mt6">只填环境变量名；真实密钥由运维写入服务器环境变量，不落数据库。</div>
      </el-form-item>
      <el-form-item label="优先级"><el-input-number v-model="provForm.priority" :min="0" :max="1000" style="width:140px"></el-input-number></el-form-item>
      <el-form-item label="启用"><el-switch v-model="provForm.enabled"></el-switch></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="provDlg = false">取消</el-button>
      <el-button type="primary" :loading="provSaving" @click="saveProvider">保存</el-button>
    </template>
  </el-dialog>
</template>
`,
};
