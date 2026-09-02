<template>
  <div class="page">
    <el-card class="status-card">
      <div class="status-row">
        <div class="stat">
          <div class="k">读取状态</div>
          <div class="v" :class="status.reader_ready ? 'good' : 'bad'">
            {{ status.reader_ready ? "已就绪" : "未就绪" }}
          </div>
        </div>
        <div class="stat" v-if="status.wechat_wxid || status.wechat_account">
          <div class="k">本机系统号</div>
          <div class="v">{{ status.wechat_wxid || status.wechat_account }}</div>
        </div>
        <div class="stat">
          <div class="k">最近同步</div>
          <div class="v">{{ lastSyncText }}</div>
        </div>
        <div class="stat">
          <div class="k">下次定时</div>
          <div class="v">{{ nextSyncText }}</div>
        </div>
      </div>
      <p v-if="status.hint" class="hint status-hint">{{ status.hint }}</p>
    </el-card>

    <el-card class="rule-card">
      <div class="rule-kicker">全局规则</div>
      <p class="hint">对手动同步和定时自动同步都生效。按微信备注、昵称或群名匹配，改完自动保存到本机。</p>

      <div class="rule-section">
        <div class="rule-head">
          <div class="rule-title">只同步这些人</div>
          <div class="rule-count">{{ includeItems.length ? `已指定 ${includeItems.length} 人` : "未设置，按最近会话" }}</div>
        </div>
        <p class="hint">填了就只同步这些人，人数上限不生效。群名写在这里也会同步该群，不必再勾选包含群聊。</p>
        <div class="rule-editor">
          <el-tag
            v-for="name in includeItems"
            :key="'in-' + name"
            closable
            effect="plain"
            type="success"
            @close="removeInclude(name)"
          >{{ name }}</el-tag>
          <el-input
            v-model="includeDraft"
            class="rule-add"
            placeholder="输入备注、昵称或群名，回车添加"
            @keydown.enter.prevent="onIncludeEnter"
          >
            <template #append>
              <el-button @click="addInclude">添加</el-button>
            </template>
          </el-input>
        </div>
      </div>

      <div class="rule-section">
        <div class="rule-head">
          <div class="rule-title">排除名单</div>
          <div class="rule-count">{{ excludeItems.length ? `已排除 ${excludeItems.length} 人` : "未设置" }}</div>
        </div>
        <p class="hint">两边都写了同一个人时，以排除名单为准。</p>
        <div class="rule-editor">
          <el-tag
            v-for="name in excludeItems"
            :key="'ex-' + name"
            closable
            effect="plain"
            @close="removeExclude(name)"
          >{{ name }}</el-tag>
          <el-input
            v-model="excludeDraft"
            class="rule-add"
            placeholder="输入备注或昵称，回车添加"
            @keydown.enter.prevent="onExcludeEnter"
          >
            <template #append>
              <el-button @click="addExclude">添加</el-button>
            </template>
          </el-input>
        </div>
      </div>
    </el-card>

    <el-card class="live-card">
      <template #header>
        <div class="card-head">
          <span>同步进度</span>
          <span class="head-meta" v-if="job">{{ statusLabel }} ｜ {{ jobKindLabel }} ｜ 会话 {{ job.ok_contacts || 0 }}/{{ job.total_contacts || 0 }} ｜ {{ jobMetricLabel }} {{ job.written || 0 }}</span>
          <span class="head-meta" v-else>开始同步后进度和日志会显示在这里</span>
        </div>
      </template>
      <el-progress
        :percentage="percent"
        :status="job?.status === 'failed' ? 'exception' : job?.status === 'succeeded' ? 'success' : undefined"
        :indeterminate="busy && percent < 12"
        striped
        :striped-flow="busy"
      />
      <el-alert
        v-if="job?.error_message"
        :title="job.error_message"
        type="error"
        :closable="false"
        style="margin-top: 12px"
      />
      <pre ref="logBox" class="log">{{ job?.log || "暂无日志。点「开始同步」或从右侧记录里查看历史日志。" }}</pre>
    </el-card>

    <div class="body">
      <div class="settings-col">
        <el-card>
          <template #header>本次同步</template>
          <el-form label-width="108px" class="form">
            <el-form-item label="同步最近">
              <div class="inline">
                <el-input-number v-model="days" :min="1" :max="90" @change="saveTiming" />
                <span>天</span>
              </div>
            </el-form-item>
            <el-form-item label="会话范围">
              <el-checkbox v-model="includeGroups" @change="saveTiming">包含群聊</el-checkbox>
            </el-form-item>
            <el-form-item label="人数上限">
              <div class="inline">
                <el-switch v-model="limitEnabled" :disabled="includeItems.length > 0" @change="saveTiming" />
                <el-input-number
                  v-model="limitPeople"
                  :min="1"
                  :max="300"
                  :disabled="!limitEnabled || includeItems.length > 0"
                  @change="saveTiming"
                />
                <span>人</span>
              </div>
              <p v-if="includeItems.length" class="hint field-hint">已指定只同步这些人，人数上限不生效</p>
            </el-form-item>
            <el-form-item label="每人条数">
              <div class="limit-pair">
                <div class="inline">
                  <span>个人</span>
                  <el-input-number
                    v-model="limitPerContact"
                    :min="50"
                    :max="5000"
                    :step="100"
                    @change="saveTiming"
                  />
                  <span>条</span>
                </div>
                <div class="inline">
                  <span>群聊</span>
                  <el-input-number
                    v-model="limitPerGroup"
                    :min="50"
                    :max="5000"
                    :step="100"
                    @change="saveTiming"
                  />
                  <span>条</span>
                </div>
              </div>
              <p class="hint field-hint">群更活跃，单独调高即可。调大后下次同步会按最近天数补更早的记录。</p>
            </el-form-item>
            <el-form-item>
              <div class="sync-actions">
                <el-button type="primary" :loading="loading" :disabled="busy" @click="start">开始同步</el-button>
                <el-button :loading="backfillLoading" :disabled="busy" @click="startMediaBackfill">补拉媒体</el-button>
              </div>
              <p v-if="status.missing_media_count" class="hint field-hint">
                当前有 {{ status.missing_media_count }} 条缺原文件。请先在微信里点开原图或下载附件，再点「补拉媒体」。
              </p>
            </el-form-item>
          </el-form>
          <p class="hint">默认只同步个人聊天。已同步过的人只拉上次成功之后的新消息；把天数或个人/群聊条数调大时会补更早的记录。</p>
        </el-card>

        <el-card>
          <template #header>同步时机</template>
          <el-form label-width="108px" class="form">
            <el-form-item label="自动同步">
              <el-switch v-model="autoEnabled" @change="saveTiming" />
            </el-form-item>
            <el-form-item label="定时间隔">
              <el-select v-model="autoMinutes" :disabled="!autoEnabled" style="width: 160px" teleported @change="saveTiming">
                <el-option :value="5" label="每 5 分钟" />
                <el-option :value="15" label="每 15 分钟" />
                <el-option :value="30" label="每 30 分钟" />
                <el-option :value="60" label="每 60 分钟" />
              </el-select>
            </el-form-item>
            <el-form-item label="库有更新时">
              <el-checkbox v-model="watchEnabled" :disabled="!autoEnabled" @change="saveTiming">
                安静约 1 分钟后提前同步
              </el-checkbox>
            </el-form-item>
          </el-form>
          <p class="hint">
            不能按库文件体积实时解密。定时间隔最稳；勾选「库有更新」只在会话库改动并安静后再跑同一套同步。
          </p>
        </el-card>

        <div class="danger-zone">
          <el-button type="danger" plain :loading="resetting" @click="resetData">清空数据</el-button>
          <span class="hint">只清已同步的聊天，不影响设置和词表</span>
        </div>
      </div>

      <el-card class="history-card">
        <template #header>
          <div class="card-head">
            <span>同步记录</span>
            <el-button link type="primary" @click="loadHistory">刷新</el-button>
          </div>
        </template>
        <el-table :data="history" max-height="560" empty-text="还没有同步记录">
          <el-table-column label="时间" min-width="168">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="类型" width="88">
            <template #default="{ row }">{{ jobKindText(row.kind) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="88">
            <template #default="{ row }">
              <el-tag :type="jobTag(row.status)" size="small">{{ jobLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="会话" width="88">
            <template #default="{ row }">{{ row.ok_contacts || 0 }}/{{ row.total_contacts || 0 }}</template>
          </el-table-column>
          <el-table-column label="写入" width="72">
            <template #default="{ row }">{{ row.kind === "media_backfill" ? row.written || 0 : row.written }}</template>
          </el-table-column>
          <el-table-column label="操作" width="88" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openHistory(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <el-drawer v-model="historyOpen" :title="historyTitle" size="520px" destroy-on-close>
      <p class="meta" v-if="historyJob">
        {{ jobLabel(historyJob.status) }} ｜ {{ jobKindText(historyJob.kind) }} ｜ 会话 {{ historyJob.ok_contacts || 0 }}/{{ historyJob.total_contacts || 0 }} ｜
        {{ historyJob.kind === "media_backfill" ? "补到" : "写入" }} {{ historyJob.written || 0 }} ｜ 跳过 {{ historyJob.skipped || 0 }}
      </p>
      <el-alert
        v-if="historyJob?.error_message"
        :title="historyJob.error_message"
        type="error"
        :closable="false"
        style="margin-bottom: 12px"
      />
      <pre class="log drawer-log">{{ historyJob?.log || "没有日志" }}</pre>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "../api";
import { formatTime } from "../formatTime";

const JOB_KEY = "lingxi-sync-job";
const STATUS_MAP = { queued: "排队中", running: "进行中", succeeded: "已完成", failed: "失败" };
const status = ref({});
const days = ref(14);
const includeGroups = ref(false);
const excludeNames = ref("");
const excludeDraft = ref("");
const includeNames = ref("");
const includeDraft = ref("");
const limitEnabled = ref(true);
const limitPeople = ref(20);
const limitPerContact = ref(1000);
const limitPerGroup = ref(1000);
const autoEnabled = ref(false);
const autoMinutes = ref(15);
const watchEnabled = ref(false);
const loading = ref(false);
const backfillLoading = ref(false);
const resetting = ref(false);
const saving = ref(false);
const job = ref(null);
const history = ref([]);
const historyOpen = ref(false);
const historyJob = ref(null);
const logBox = ref(null);
const excludeDirty = ref(false);
let timer = null;
let namesTimer = null;
let saveQueued = false;

const busy = computed(() => ["queued", "running"].includes(job.value?.status));

const percent = computed(() => {
  if (!job.value) return 0;
  if (job.value.status === "succeeded") return 100;
  if (!job.value.total_contacts) return job.value.status === "queued" ? 5 : 15;
  return Math.min(99, Math.round((job.value.ok_contacts / job.value.total_contacts) * 100));
});

const statusLabel = computed(() => jobLabel(job.value?.status));

const jobKindLabel = computed(() => jobKindText(job.value?.kind));

const jobMetricLabel = computed(() => (job.value?.kind === "media_backfill" ? "补到" : "写入"));

const lastSyncText = computed(() => {
  const last = status.value.last_sync;
  if (!last) return "尚未同步";
  const label = jobLabel(last.status);
  const when = formatTime(last.at);
  return when === "—" ? label || "—" : `${when} · ${label}`;
});

const nextSyncText = computed(() => {
  const auto = status.value.auto_sync || {};
  if (!auto.enabled) return "未开启";
  if (auto.need_first_sync) return "请先手动同步";
  const when = formatTime(auto.next_at);
  return when === "—" ? "等待间隔" : when;
});

const historyTitle = computed(() => {
  if (!historyJob.value) return "同步记录";
  return `${formatTime(historyJob.value.created_at)} · ${jobLabel(historyJob.value.status)}`;
});

const excludeItems = computed(() => splitNames(excludeNames.value));
const includeItems = computed(() => splitNames(includeNames.value));

function splitNames(text) {
  const names = [];
  for (const line of (text || "").split("\n")) {
    const name = line.trim();
    if (name && !names.includes(name)) names.push(name);
  }
  return names;
}

function jobKindText(value) {
  if (value === "media_backfill") return "补媒体";
  return "同步";
}

function jobLabel(value) {
  return STATUS_MAP[value] || value || "—";
}

function jobTag(value) {
  if (value === "succeeded") return "success";
  if (value === "failed") return "danger";
  if (value === "running") return "warning";
  return "info";
}

async function refreshStatus() {
  status.value = await api.readerStatus();
}

async function loadFilters() {
  const s = await api.settings();
  includeGroups.value = Boolean(s.sync_include_groups);
  limitEnabled.value = s.sync_limit_people_enabled !== false;
  limitPeople.value = s.sync_limit_people || 20;
  limitPerContact.value = s.sync_limit_per_contact || 1000;
  limitPerGroup.value = s.sync_limit_per_group || s.sync_limit_per_contact || 1000;
  days.value = s.sync_days || 14;
  autoEnabled.value = Boolean(s.sync_auto_enabled);
  autoMinutes.value = s.sync_auto_minutes || 15;
  watchEnabled.value = Boolean(s.sync_watch_enabled);
  if (!excludeDirty.value) {
    excludeNames.value = s.sync_exclude_names || "";
    includeNames.value = s.sync_include_names || "";
  }
}

async function loadHistory() {
  try {
    const data = await api.syncJobs();
    history.value = data.items || [];
  } catch {
    history.value = [];
  }
}

function scopeBody() {
  return {
    sync_days: days.value,
    sync_include_groups: includeGroups.value,
    sync_exclude_names: excludeNames.value,
    sync_include_names: includeNames.value,
    sync_limit_people_enabled: limitEnabled.value,
    sync_limit_people: limitPeople.value,
    sync_limit_per_contact: limitPerContact.value,
    sync_limit_per_group: limitPerGroup.value,
    sync_auto_enabled: autoEnabled.value,
    sync_auto_minutes: autoMinutes.value,
    sync_watch_enabled: watchEnabled.value,
  };
}

async function saveTiming() {
  if (saving.value) {
    saveQueued = true;
    return;
  }
  saving.value = true;
  try {
    do {
      saveQueued = false;
      await api.saveSettings(scopeBody());
      if (!status.value.auto_sync) status.value.auto_sync = {};
      status.value.auto_sync.enabled = autoEnabled.value;
      status.value.auto_sync.minutes = autoMinutes.value;
      status.value.auto_sync.watch_enabled = watchEnabled.value;
    } while (saveQueued);
  } catch (e) {
    ElMessage.error(e.message);
  } finally {
    saving.value = false;
  }
}

function onNamesInput() {
  excludeDirty.value = true;
  clearTimeout(namesTimer);
  namesTimer = setTimeout(() => {
    saveTiming();
  }, 400);
}

function setExcludeItems(names) {
  excludeNames.value = names.join("\n");
  onNamesInput();
}

function addExclude() {
  const name = excludeDraft.value.trim();
  if (!name) return;
  if (!excludeItems.value.includes(name)) {
    setExcludeItems([...excludeItems.value, name]);
  }
  excludeDraft.value = "";
}

function onExcludeEnter(e) {
  if (e.isComposing || e.keyCode === 229) return;
  addExclude();
}

function removeExclude(name) {
  setExcludeItems(excludeItems.value.filter((item) => item !== name));
}

function setIncludeItems(names) {
  includeNames.value = names.join("\n");
  onNamesInput();
}

function addInclude() {
  const name = includeDraft.value.trim();
  if (!name) return;
  if (!includeItems.value.includes(name)) {
    setIncludeItems([...includeItems.value, name]);
  }
  includeDraft.value = "";
}

function onIncludeEnter(e) {
  if (e.isComposing || e.keyCode === 229) return;
  addInclude();
}

function removeInclude(name) {
  setIncludeItems(includeItems.value.filter((item) => item !== name));
}

async function startMediaBackfill() {
  backfillLoading.value = true;
  try {
    const created = await api.startMediaBackfill({
      include_names: includeNames.value,
      exclude_names: excludeNames.value,
    });
    job.value = created;
    sessionStorage.setItem(JOB_KEY, created.id);
    poll();
    loadHistory();
  } catch (e) {
    ElMessage.error(e.message);
  } finally {
    backfillLoading.value = false;
  }
}

async function start() {
  loading.value = true;
  try {
    await api.saveSettings(scopeBody());
    const created = await api.startSync({
      days: days.value,
      limit_per_contact: limitPerContact.value,
      limit_per_group: limitPerGroup.value,
      include_groups: includeGroups.value,
      exclude_names: excludeNames.value,
      include_names: includeNames.value,
      limit_people_enabled: limitEnabled.value,
      limit_people: limitPeople.value,
    });
    job.value = created;
    sessionStorage.setItem(JOB_KEY, created.id);
    poll();
    loadHistory();
  } catch (e) {
    ElMessage.error(e.message);
  } finally {
    loading.value = false;
  }
}

async function tick() {
  if (!job.value?.id) return;
  try {
    job.value = await api.syncJob(job.value.id);
    if (historyOpen.value && historyJob.value?.id === job.value.id) {
      historyJob.value = job.value;
    }
    await nextTick();
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight;
    if (["succeeded", "failed"].includes(job.value.status)) {
      stop();
      await refreshStatus();
      await loadHistory();
    }
  } catch {
    /* 继续轮询 */
  }
}

async function openHistory(row) {
  if (job.value?.id === row.id && job.value.log) {
    historyJob.value = job.value;
    historyOpen.value = true;
    return;
  }
  try {
    historyJob.value = await api.syncJob(row.id);
    historyOpen.value = true;
  } catch (e) {
    ElMessage.error(e.message);
  }
}

async function resetData() {
  try {
    await ElMessageBox.confirm(
      "将清空已同步的会话、消息、统计和分析结果。设置和词表会保留。此操作不可恢复。",
      "清空当前数据",
      { type: "warning", confirmButtonText: "清空", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  resetting.value = true;
  try {
    stop();
    await api.resetData();
    job.value = null;
    history.value = [];
    historyOpen.value = false;
    sessionStorage.removeItem(JOB_KEY);
    await refreshStatus();
    ElMessage.success("已清空");
  } catch (e) {
    ElMessage.error(e.message);
  } finally {
    resetting.value = false;
  }
}

function poll() {
  stop();
  tick();
  timer = setInterval(tick, 1000);
}

function stop() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

function attachJob(id) {
  if (!id) return;
  job.value = { id, status: "running", log: "正在恢复任务…" };
  sessionStorage.setItem(JOB_KEY, id);
  poll();
}

onMounted(async () => {
  const ready = Promise.all([loadFilters(), loadHistory(), refreshStatus()]);
  await ready;
  const active = ["queued", "running"].includes(status.value.sync_job_status);
  if (active && status.value.sync_job_id) {
    attachJob(status.value.sync_job_id);
    return;
  }
  const saved = sessionStorage.getItem(JOB_KEY);
  if (saved) {
    attachJob(saved);
    return;
  }
  const latest = history.value[0];
  if (latest) {
    try {
      job.value = await api.syncJob(latest.id);
    } catch {
      job.value = latest;
    }
  }
});
onUnmounted(() => {
  stop();
  clearTimeout(namesTimer);
  if (excludeDirty.value) saveTiming();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 8px;
}
.status-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}
.stat {
  padding: 4px 8px 4px 0;
  border-right: 1px solid var(--line);
}
.stat:last-child { border-right: none; }
.k { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.v { font-weight: 600; line-height: 1.4; word-break: break-all; }
.v.good { color: var(--good); }
.v.bad { color: var(--bad); }
.status-hint { margin: 12px 0 0; }
.rule-card :deep(.el-card__body) { padding-bottom: 16px; }
.rule-section {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.rule-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
.rule-kicker {
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--warn);
  font-weight: 600;
  margin-bottom: 2px;
}
.rule-title { font-weight: 700; }
.rule-count { color: var(--muted); font-size: 13px; white-space: nowrap; }
.rule-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  max-height: 112px;
  overflow: auto;
}
.rule-add { width: 280px; max-width: 100%; }
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.head-meta { color: var(--muted); font-size: 13px; font-weight: 400; }
.body {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.1fr);
  gap: 16px;
  align-items: start;
}
.settings-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: visible;
}
.settings-col :deep(.el-card),
.settings-col :deep(.el-card__body),
.settings-col :deep(.el-card__header),
.history-card {
  overflow: visible;
}
.form { max-width: 420px; }
.inline { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sync-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.limit-pair { display: flex; flex-direction: column; gap: 8px; }
.hint { color: var(--muted); font-size: 13px; margin: 0; line-height: 1.6; }
.field-hint { margin-top: 6px; }
.meta { margin: 0 0 12px; color: var(--muted); }
.danger-zone { display: flex; align-items: center; gap: 12px; padding: 4px 2px 8px; }
.log {
  max-height: 160px;
  overflow: auto;
  background: #12171e;
  color: #dcdfe6;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  margin: 12px 0 0;
}
.drawer-log { max-height: none; height: calc(100vh - 220px); margin: 0; }
@media (max-width: 1100px) {
  .status-row, .body { grid-template-columns: 1fr; }
  .stat { border-right: none; border-bottom: 1px solid var(--line); padding-bottom: 12px; }
  .stat:last-child { border-bottom: none; }
}
</style>
