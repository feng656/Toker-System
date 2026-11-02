/**
 * 设置：角色可见范围、平台发布模式说明；管理员另可管理平台凭据、合规红线与用户。
 * 完成标志（《分工》4.2）：不会把实验能力误认为一期必需能力。
 */
import { ref, reactive, onMounted } from '../core/vue.js';
import { platformApi } from '../api/platform.js';
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

    async function load() {
      loading.value = true;
      error.value = '';
      forbidden.value = false;
      try {
        const st = await platformApi.status();
        platStatus.value = st || [];
        if (isAdmin()) {
          const [acc, rl, us] = await Promise.all([
            platformApi.list().catch(() => []),
            ruleApi.list().catch(() => []),
            authApi.listUsers().catch(() => []),
          ]);
          accounts.value = acc || [];
          rules.value = rl || [];
          users.value = us || [];
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

    onMounted(load);

    return {
      platStatus, accounts, rules, users, loading, error, forbidden,
      accForm, ruleForm, userForm, load, saveAccount, addRule, removeRule, addUser,
      platformName, PLATFORM_HOME, isAdmin, session, ROLE_VISIBLE, PAGE_ROLES,
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
</template>
`,
};
