<template>
  <el-card>
    <template #header>系统设置</template>
    <el-form label-width="140px" class="form">
      <el-form-item label="授权状态">
        <div>
          <div>{{ licenseText }}</div>
          <div class="hint">{{ licenseHint }}</div>
        </div>
      </el-form-item>
      <el-form-item label="本机系统号">
        <el-input :model-value="form.wechat_wxid || form.wechat_account" disabled placeholder="完成微信读取初始化后自动识别" />
      </el-form-item>
      <el-form-item v-if="accounts.length > 1" label="本机出现过的微信号">
        <div class="accounts">
          <p class="hint block">只读切换查看，不影响当前同步写入哪个号。默认仍是当前登录号。</p>
          <div v-for="row in accounts" :key="row.id" class="account-row">
            <div>
              <b>{{ row.display_name || row.account_key }}</b>
              <span class="hint">{{ row.account_key }}</span>
              <span v-if="row.is_current" class="hint">当前登录</span>
              <span v-else-if="viewingId === row.id" class="hint">查看中</span>
            </div>
            <el-button v-if="!row.is_current && viewingId !== row.id" link type="primary" @click="viewAccount(row.id)">查看此号</el-button>
            <el-button v-else-if="!row.is_current" link type="primary" @click="viewAccount(null)">回到当前登录号</el-button>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="我的微信昵称">
        <el-input v-model="form.self_nickname" placeholder="聊天气泡里显示的本机昵称，不填则显示「我」" />
      </el-form-item>
      <el-form-item label="数据库文件">
        <div class="path-block">
          <el-input :model-value="form.db_path" disabled />
          <el-button @click="copy(form.db_path)">复制</el-button>
        </div>
      </el-form-item>
      <el-form-item label="数据目录">
        <div class="path-block">
          <el-input
            v-model="form.data_dir_next"
            :disabled="form.data_dir_locked"
            placeholder="聊天记录、图片和诊断结果保存在这里"
          />
          <el-button :disabled="form.data_dir_locked" @click="form.data_dir_next = form.data_dir_default">恢复默认</el-button>
          <el-button @click="reveal">打开</el-button>
        </div>
        <div class="hint block">{{ dataDirHint }}</div>
      </el-form-item>
      <el-form-item label="超时阈值(秒)">
        <div>
          <el-input-number v-model="form.timeout_seconds" :min="30" :max="3600" />
          <p class="hint block">对方发来消息后，超过这个秒数还没回复，好友雷达会标超时，效率统计也会计入超时次数。默认 180 秒。</p>
        </div>
      </el-form-item>
      <el-form-item label="会话间隔(小时)">
        <div>
          <el-input-number v-model="form.session_gap_hours" :min="1" :max="72" />
          <p class="hint block">同一联系人两次消息间隔超过这个小时数，下次同步会拆成一条新会话。只影响之后的同步，已经存下来的会话不会改。默认 12 小时。</p>
        </div>
      </el-form-item>
      <el-form-item label="模型地址">
        <el-input v-model="form.model_base_url" placeholder="https://api.example.com/v1" />
      </el-form-item>
      <el-form-item label="模型名">
        <el-input v-model="form.model_name" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="form.model_api_key" type="password" show-password placeholder="已配置则不必重填" />
        <span class="hint">{{ form.model_key_configured ? "已保存，重启后仍有效；不必重填" : "未保存。请填写后点保存，不要只填地址和模型名" }}</span>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="save">保存</el-button>
        <el-button type="warning" :loading="restarting" @click="restart">重启 Judy</el-button>
        <span class="hint">改数据目录后必须重启。也可在 Finder 里双击安装目录中的「重启」或「停止」。</span>
      </el-form-item>
    </el-form>
    <el-divider />
    <h4>禁用词</h4>
    <el-table :data="lexicon">
      <el-table-column prop="term" label="词条" />
      <el-table-column label="启用" width="120">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="(v) => toggle(row, v)" />
        </template>
      </el-table-column>
    </el-table>
    <div class="add">
      <el-input v-model="newItem.term" placeholder="新增禁用词" />
      <el-button @click="add">添加</el-button>
    </div>
  </el-card>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from "vue";
import { ElLoading, ElMessage, ElMessageBox } from "element-plus";
import { api } from "../api";

const form = reactive({
  timeout_seconds: 180,
  session_gap_hours: 12,
  model_base_url: "",
  model_name: "",
  model_api_key: "",
  model_key_configured: false,
  self_nickname: "",
  wechat_account: "",
  wechat_wxid: "",
  db_path: "",
  data_dir: "",
  data_dir_default: "",
  data_dir_next: "",
  data_dir_source: "default",
  data_dir_locked: false,
  data_dir_restart_required: false,
});
const lexicon = ref([]);
const restarting = ref(false);
const newItem = reactive({ kind: "forbidden", term: "" });
const license = ref({ ok: true, mode: "development", customer: "", version: "", message: "" });
const accounts = inject("accounts", ref([]));
const setViewingAccount = inject("setViewingAccount", () => {});
const viewingAccount = inject("viewingAccount", ref(null));
const viewingId = computed(() => viewingAccount.value?.id || null);

function viewAccount(id) {
  setViewingAccount(id);
}
const licenseText = computed(() => {
  if (license.value.mode === "development") return "开发模式";
  if (license.value.ok) return `已授权${license.value.customer ? ` · ${license.value.customer}` : ""}`;
  return license.value.message || "未授权";
});
const licenseHint = computed(() => {
  const ver = license.value.version ? `版本 ${license.value.version}` : "";
  if (license.value.mode === "development") return "源码运行不校验微信绑定。交付包会绑定约定 wxid。";
  return [ver, "本机包绑定微信系统号后，复制给其他人无法使用"].filter(Boolean).join(" · ");
});
const dataDirHint = computed(() => {
  if (form.data_dir_locked) return "当前由环境变量 JUDY_DATA_DIR 指定，页面不能改。";
  const bits = ["会话、图片、诊断结果都在这个目录。改完保存后需重启 Judy 才生效，不会自动搬迁已有数据。"];
  if (form.data_dir_restart_required) bits.unshift(`正在使用：${form.data_dir}。重启后将改用新目录。`);
  return bits.join(" ");
});

async function load() {
  Object.assign(form, await api.settings());
  const rows = await api.lexicon();
  lexicon.value = rows.filter((r) => r.kind === "forbidden");
  try {
    license.value = await api.license();
  } catch {
    license.value = { ok: false, mode: "invalid", customer: "", version: "", message: "无法读取授权" };
  }
}

async function copy(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制路径");
  } catch {
    ElMessage.error("复制失败");
  }
}

async function reveal() {
  try {
    await api.revealData();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function waitUntilUp(timeoutMs = 45000) {
  const start = Date.now();
  await new Promise((r) => setTimeout(r, 1200));
  while (Date.now() - start < timeoutMs) {
    try {
      await api.ping();
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, 400));
    }
  }
  return false;
}

async function restart() {
  try {
    await ElMessageBox.confirm(
      "Judy 将关闭并重新打开。改数据目录后必须走这一步。",
      "重启 Judy",
      { type: "warning", confirmButtonText: "重启", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  restarting.value = true;
  const loading = ElLoading.service({
    lock: true,
    text: "正在重启 Judy…",
    background: "rgba(255, 255, 255, 0.82)",
  });
  try {
    await api.restart();
  } catch {
    /* 进程退出时请求可能被掐断 */
  }
  const ok = await waitUntilUp();
  loading.close();
  restarting.value = false;
  if (ok) {
    location.reload();
    return;
  }
  ElMessage.error("重启超时。请从托盘退出 Judy 后重新打开。");
}

async function save() {
  const body = {
    timeout_seconds: form.timeout_seconds,
    session_gap_hours: form.session_gap_hours,
    model_base_url: form.model_base_url,
    model_name: form.model_name,
    self_nickname: form.self_nickname,
  };
  if (!form.data_dir_locked) body.data_dir = form.data_dir_next;
  if (form.model_api_key) body.model_api_key = form.model_api_key;
  try {
    await api.saveSettings(body);
    ElMessage.success("已保存");
    await load();
    if (form.data_dir_restart_required) ElMessage.warning("数据目录将在重启后生效");
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function toggle(row, enabled) {
  await api.patchLexicon(row.id, { enabled });
  row.enabled = enabled;
}

async function add() {
  if (!newItem.term.trim()) return;
  await api.addLexicon({ kind: "forbidden", term: newItem.term.trim(), enabled: true });
  newItem.term = "";
  load();
}

onMounted(load);
</script>

<style scoped>
.form { max-width: 760px; }
.hint { margin-left: 8px; color: #909399; }
.hint.block { margin: 8px 0 0; line-height: 1.6; }
.path-block { display: flex; gap: 8px; width: 100%; }
.path-block :deep(.el-input) { flex: 1; }
.add { display: flex; gap: 8px; margin-top: 12px; max-width: 420px; }
.accounts { width: 100%; }
.account-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.account-row b { margin-right: 8px; }
</style>
