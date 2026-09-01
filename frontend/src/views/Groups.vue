<template>
  <div class="page">
    <aside class="list">
      <div class="list-head">
        <div>
          <div class="kicker">GROUP ROSTER</div>
          <div class="title">群画像</div>
        </div>
        <el-button link type="primary" @click="loadGroups">刷新</el-button>
      </div>
      <el-input v-model="q" clearable placeholder="搜索群名" @clear="loadGroups" @keyup.enter="loadGroups" />
      <p v-if="!groups.length" class="empty">还没有同步到群。请到微信同步勾选「包含群聊」后再同步。</p>
      <button
        v-for="g in groups"
        :key="g.id"
        type="button"
        class="g-item"
        :class="{ on: selectedId === g.id }"
        @click="selectGroup(g.id)"
      >
        <div class="g-name">{{ g.name }}</div>
        <div class="g-meta">{{ g.member_count }} 人发言 · {{ g.msg_count }} 条</div>
      </button>
    </aside>

    <section class="main-pane">
      <div v-if="!selectedId" class="blank">
        从左侧选一个群。可以看成员画像，也可以生成并查看群日报、群周报。
      </div>
      <template v-else>
        <header class="hero">
          <div>
            <h1>{{ group.name || "群画像" }}</h1>
            <p class="sub">
              只看这个群里发过言的人。成员画像用来判断要不要加好友；群报用来看这一天或这一周群里发生了什么。
            </p>
          </div>
          <div class="actions">
            <el-select v-model="promptId" placeholder="群画像提示词" style="width: 220px">
              <el-option v-for="p in prompts" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-checkbox v-model="activeOnly" @change="loadDetail">只看较活跃（≥3条）</el-checkbox>
            <el-button type="primary" :loading="busy" @click="run">发起画像</el-button>
            <el-button :loading="busy" @click="runDigest('daily')">生成日报</el-button>
            <el-button :loading="busy" @click="runDigest('weekly')">生成周报</el-button>
            <el-button v-if="group.conversation_id" @click="goChat">看群聊天</el-button>
            <el-button link type="primary" @click="goPrompts">管理提示词</el-button>
          </div>
        </header>
        <div v-if="job" class="progress-wrap">
          <el-progress
            :percentage="displayPercent"
            :status="progressStatus"
            :indeterminate="analyzing && displayPercent < 12"
            striped
            :striped-flow="analyzing"
            :stroke-width="10"
            :show-text="false"
          />
          <p class="job">{{ progressText }}{{ job.error_message ? " · " + job.error_message : "" }}</p>
        </div>
        <section class="digest">
          <div class="digest-head no-export">
            <div>
              <div class="roster-title">群报</div>
              <div class="roster-meta">日报看当天，周报看最近一周。和下面的成员画像分开保存，互不覆盖。</div>
            </div>
            <div class="digest-actions">
              <el-radio-group v-model="digestTab" size="small" @change="loadDigest">
                <el-radio-button label="daily">日报</el-radio-button>
                <el-radio-button label="weekly">周报</el-radio-button>
              </el-radio-group>
              <el-button
                :loading="digestExporting"
                :disabled="!digestPayload || busy"
                @click="exportDigest"
              >导出图片</el-button>
            </div>
          </div>
          <p v-if="!digestHistory.length" class="digest-empty no-export">
            还没有{{ digestTab === "daily" ? "日报" : "周报" }}。点右上角生成后会出现在这里。
          </p>
          <div v-else class="digest-history no-export">
            <button
              v-for="item in digestHistory"
              :key="item.id"
              type="button"
              class="h-item"
              :class="{ active: digestResultId === item.id }"
              @click="openDigest(item)"
            >
              {{ item.title }}
            </button>
          </div>
          <div v-if="digestPayload" ref="digestRoot" class="digest-share">
            <p class="share-only digest-brand">{{ group.name }} · {{ digestKindLabel }}</p>
            <div class="digest-body">
            <div class="digest-kicker">{{ digestMeta.title || digestRange }}</div>
            <h2>{{ digestPayload.headline || digestKindLabel }}</h2>
            <p v-if="digestPayload.raw && !digestPayload.summary" class="digest-summary">{{ digestPayload.raw }}</p>
            <p v-else class="digest-summary">{{ digestPayload.summary }}</p>
            <div v-if="(digestPayload.highlights || []).length" class="digest-block">
              <div class="digest-label">要点</div>
              <div v-for="(h, i) in digestPayload.highlights" :key="'h' + i" class="digest-item">
                <b>{{ h.title || h.who || "要点" }}</b>
                <span v-if="h.who && h.title"> · {{ h.who }}</span>
                <p>{{ h.detail }}</p>
              </div>
            </div>
            <div v-if="(digestPayload.topics || []).length" class="digest-tags">
              <span v-for="(t, i) in digestPayload.topics" :key="'t' + i">{{ t.name }}{{ t.count ? ` ${t.count}` : "" }}</span>
            </div>
            <div class="digest-cols">
              <div v-if="(digestPayload.active || []).length">
                <div class="digest-label">较活跃</div>
                <p v-for="(p, i) in digestPayload.active" :key="'a' + i">{{ p.name }}{{ p.note ? ` · ${p.note}` : "" }}</p>
              </div>
              <div v-if="(digestPayload.quiet || []).length">
                <div class="digest-label">发言较少</div>
                <p v-for="(p, i) in digestPayload.quiet" :key="'q' + i">{{ p.name }}{{ p.note ? ` · ${p.note}` : "" }}</p>
              </div>
            </div>
            <div v-if="(digestPayload.risks || []).length" class="digest-block">
              <div class="digest-label">注意</div>
              <div v-for="(r, i) in digestPayload.risks" :key="'r' + i" class="digest-item">
                <b>{{ r.title || "注意" }}</b>
                <p>{{ r.detail }}</p>
              </div>
            </div>
            <div v-if="(digestPayload.actions || []).length" class="digest-block">
              <div class="digest-label">建议</div>
              <p v-for="(a, i) in digestPayload.actions" :key="'x' + i">{{ typeof a === "string" ? a : a.title || a.detail || "" }}</p>
            </div>
            </div>
            <footer class="share-footer">Judy · {{ digestKindLabel }}</footer>
          </div>
        </section>
        <div class="kpis">
          <div class="kpi"><div class="k-label">发言成员</div><div class="k-num">{{ summary.members || 0 }}</div></div>
          <div class="kpi cyan"><div class="k-label">较活跃</div><div class="k-num">{{ summary.active || 0 }}</div></div>
          <div class="kpi accent"><div class="k-label">建议加好友</div><div class="k-num">{{ summary.recommend || 0 }}</div></div>
          <div class="kpi"><div class="k-label">已是好友</div><div class="k-num">{{ summary.already_friend || 0 }}</div></div>
        </div>
        <GroupGraph
          :graph="graph"
          :selected-key="selectedMember"
          :share-title="graphShareTitle"
          @select="selectMember"
        />
        <div class="table-wrap">
        <div class="roster-head">
          <div class="roster-title">群友名册</div>
          <div class="roster-meta">{{ members.length }} 人 · 点图谱或点行可互相对照</div>
        </div>
        <el-table
          :data="members"
          max-height="420"
          class="table"
          highlight-current-row
          :row-class-name="rowClass"
          empty-text="这个群在当前范围没有发言成员"
          @row-click="(row) => selectMember(row.key)"
        >
          <el-table-column label="群好友" min-width="140">
            <template #default="{ row }">
              <div>{{ row.name }}</div>
              <div v-if="row.already_friend" class="t">通讯录已有{{ row.friend_label ? `：${row.friend_label}` : "" }}</div>
            </template>
          </el-table-column>
          <el-table-column label="发言" width="88">
            <template #default="{ row }">{{ row.msg_count }}</template>
          </el-table-column>
          <el-table-column label="活跃" width="88">
            <template #default="{ row }">{{ activityLabel(row.activity) }}</template>
          </el-table-column>
          <el-table-column label="最近" min-width="168">
            <template #default="{ row }">{{ formatTime(row.last_at) }}</template>
          </el-table-column>
          <el-table-column label="画像" min-width="240">
            <template #default="{ row }">
              <div>{{ row.profile || row.reason || row.note || "尚未分析" }}</div>
              <div v-if="row.reason" class="t">{{ row.reason }}</div>
            </template>
          </el-table-column>
          <el-table-column label="加好友" width="168" fixed="right">
            <template #default="{ row }">
              <el-select :model-value="row.status" size="small" @change="(v) => mark(row, v)">
                <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </template>
          </el-table-column>
        </el-table>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api";
import { exportSharePng } from "../exportImage";
import { formatTime } from "../formatTime";
import GroupGraph from "../components/GroupGraph.vue";

const filter = inject("filter");
const router = useRouter();
const q = ref("");
const groups = ref([]);
const selectedId = ref(null);
const group = ref({});
const members = ref([]);
const graph = ref({ nodes: [], edges: [] });
const selectedMember = ref("");
const summary = ref({});
const statusOptions = ref([]);
const prompts = ref([]);
const promptId = ref(null);
const activeOnly = ref(true);
const job = ref(null);
const displayPercent = ref(0);
const loading = ref(false);
const digestTab = ref("daily");
const digestHistory = ref([]);
const digestPayload = ref(null);
const digestMeta = ref({ title: "", start_date: "", end_date: "" });
const digestResultId = ref(null);
const digestRoot = ref(null);
const digestExporting = ref(false);
let timer = null;
let tickTimer = null;

const STATUS = { queued: "排队中", running: "分析中", succeeded: "已完成", failed: "失败" };
const analyzing = computed(() => ["queued", "running"].includes(job.value?.status || ""));
const busy = computed(() => loading.value || analyzing.value);
const progressStatus = computed(() => {
  if (job.value?.status === "failed") return "exception";
  if (job.value?.status === "succeeded") return "success";
  return undefined;
});
const progressText = computed(() => {
  const label = job.value?.progress_label || STATUS[job.value?.status] || "";
  return label ? `${label} ${displayPercent.value}%` : `${displayPercent.value}%`;
});
const digestRange = computed(() => {
  const start = digestMeta.value.start_date || "";
  const end = digestMeta.value.end_date || "";
  if (start && end && start !== end) return `${start} 至 ${end}`;
  return start || end || "";
});
const digestKindLabel = computed(() => (digestTab.value === "daily" ? "群日报" : "群周报"));
const graphShareTitle = computed(() => `${group.value.name || "群"} · 活跃关系图谱`);

function activityLabel(v) {
  return { high: "高", mid: "中", low: "低" }[v] || "—";
}

function rangeParams() {
  return {
    start_date: filter.value.start_date,
    end_date: filter.value.end_date,
  };
}

async function loadPrompts() {
  const rows = (await api.prompts()).filter((p) => p.enabled && p.kind === "group");
  prompts.value = rows;
  if (!promptId.value) {
    const def = rows.find((p) => p.is_default) || rows[0];
    promptId.value = def ? def.id : null;
  }
}

async function loadGroups() {
  const data = await api.groups({ ...rangeParams(), q: q.value });
  groups.value = data.items || [];
  if (selectedId.value && !groups.value.some((g) => g.id === selectedId.value)) {
    selectedId.value = groups.value[0]?.id || null;
  } else if (!selectedId.value && groups.value.length) {
    selectedId.value = groups.value[0].id;
  }
  if (selectedId.value) {
    await loadDetail();
    await loadDigest();
  }
}

async function loadDetail() {
  if (!selectedId.value) return;
  const data = await api.group(selectedId.value, {
    ...rangeParams(),
    min_msgs: activeOnly.value ? 3 : 1,
  });
  group.value = data.group || {};
  members.value = data.members || [];
  graph.value = data.graph || { nodes: [], edges: [] };
  summary.value = data.summary || {};
  statusOptions.value = data.status_options || [];
  if (selectedMember.value && !members.value.some((m) => m.key === selectedMember.value) && selectedMember.value !== "_self") {
    selectedMember.value = "";
  }
}

async function loadDigest() {
  if (!selectedId.value) return;
  const data = await api.analysisResults({
    kind: "group",
    contact_id: selectedId.value,
    report_type: digestTab.value,
  });
  digestHistory.value = data.history || [];
  digestPayload.value = data.payload || null;
  digestMeta.value = {
    title: data.title || "",
    start_date: data.start_date || "",
    end_date: data.end_date || "",
  };
  digestResultId.value = data.result_id || null;
}

async function openDigest(item) {
  const data = await api.analysisResult(item.id);
  digestPayload.value = data.payload || null;
  digestMeta.value = {
    title: data.title || item.title || "",
    start_date: data.start_date || "",
    end_date: data.end_date || "",
  };
  digestResultId.value = data.result_id || item.id;
  if (data.report_type === "daily" || data.report_type === "weekly") {
    digestTab.value = data.report_type;
  }
  digestHistory.value = data.history || digestHistory.value;
}

function selectGroup(id) {
  selectedId.value = id;
  selectedMember.value = "";
  job.value = null;
  displayPercent.value = 0;
  digestPayload.value = null;
  digestHistory.value = [];
  digestResultId.value = null;
  loadDetail();
  loadDigest();
}

function selectMember(key) {
  selectedMember.value = selectedMember.value === key ? "" : key;
}

function rowClass({ row }) {
  return row.key === selectedMember.value ? "is-picked" : "";
}

async function mark(row, status) {
  try {
    const saved = await api.patchGroupMember(selectedId.value, {
      member_key: row.key,
      member_name: row.name,
      status,
      note: row.note || "",
    });
    row.status = saved.status;
    row.status_label = saved.status_label;
    row.source = saved.source;
    await loadDetail();
  } catch (e) {
    ElMessage.error(e.message);
  }
}

async function run() {
  if (!selectedId.value || analyzing.value) return;
  displayPercent.value = 5;
  loading.value = true;
  try {
    const created = await api.startAnalysis({
      kind: "group",
      report_type: "portrait",
      contact_id: selectedId.value,
      start_date: filter.value.start_date,
      end_date: filter.value.end_date,
      prompt_id: promptId.value || undefined,
    });
    applyJob(created);
    startTick();
    poll();
  } catch (e) {
    ElMessage.error(e.message);
    job.value = null;
  } finally {
    loading.value = false;
  }
}

async function runDigest(reportType) {
  if (!selectedId.value || analyzing.value) return;
  digestTab.value = reportType;
  displayPercent.value = 5;
  loading.value = true;
  try {
    const created = await api.startAnalysis({
      kind: "group",
      report_type: reportType,
      contact_id: selectedId.value,
      start_date: filter.value.start_date,
      end_date: filter.value.end_date,
    });
    applyJob(created);
    startTick();
    poll();
  } catch (e) {
    ElMessage.error(e.message);
    job.value = null;
  } finally {
    loading.value = false;
  }
}

function applyJob(next) {
  job.value = next;
  const raw = Number(next?.progress) || 0;
  if (next?.status === "succeeded") {
    displayPercent.value = 100;
    return;
  }
  displayPercent.value = Math.max(displayPercent.value, raw);
}

function startTick() {
  stopTick();
  tickTimer = setInterval(() => {
    if (!analyzing.value) return;
    const cap = job.value?.status === "queued" ? 10 : 86;
    if (displayPercent.value < cap) displayPercent.value = Math.min(cap, displayPercent.value + 1);
  }, 450);
}

function stopTick() {
  if (tickTimer) {
    clearInterval(tickTimer);
    tickTimer = null;
  }
}

function poll() {
  stop();
  timer = setInterval(async () => {
    if (!job.value?.id) return;
    applyJob(await api.analysisJob(job.value.id));
    if (["succeeded", "failed"].includes(job.value.status)) {
      stop();
      stopTick();
      if (job.value.status === "succeeded") {
        loadDetail();
        loadDigest();
      }
    }
  }, 1500);
}

function stop() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

function goChat() {
  if (!group.value.conversation_id) return;
  router.push({ path: "/conversations", query: { id: String(group.value.conversation_id) } });
}

function goPrompts() {
  router.push("/prompts");
}

async function exportDigest() {
  if (!digestRoot.value || !digestPayload.value || digestExporting.value) return;
  digestExporting.value = true;
  try {
    const title = `${group.value.name || "群"} · ${digestKindLabel.value}`;
    const result = await exportSharePng(digestRoot.value, {
      filename: title,
      title,
      backgroundColor: "#1a2028",
    });
    if (result === "shared") ElMessage.success("已打开分享");
    else if (result === "downloaded") ElMessage.success("已导出图片，可直接转发分享");
  } catch {
    ElMessage.error("导出失败，请稍后重试");
  } finally {
    digestExporting.value = false;
  }
}

onMounted(async () => {
  await loadPrompts();
  await loadGroups();
});
watch(filter, loadGroups, { deep: true });
onUnmounted(() => {
  stop();
  stopTick();
});
</script>

<style scoped>
.page {
  height: 100%;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}
.list {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px;
  overflow: auto;
  min-height: 0;
}
.list-head { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 12px; }
.kicker { font-size: 11px; letter-spacing: 0.18em; color: var(--warn); font-weight: 600; }
.title { font-weight: 800; }
.empty { color: var(--muted); font-size: 13px; line-height: 1.6; margin: 16px 0 0; }
.g-item {
  appearance: none;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 10px 10px;
  margin-top: 6px;
  color: var(--ink);
  cursor: pointer;
}
.g-item:hover { background: var(--panel2); }
.g-item.on { border-color: var(--accent); background: var(--accent-dim); }
.g-name { font-weight: 600; }
.g-meta { color: var(--muted); font-size: 12px; margin-top: 2px; }
.main-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
}
.table-wrap {
  flex: 0 0 auto;
  min-height: 280px;
}
.table { width: 100%; }
.table :deep(.is-picked) { background: var(--accent-dim) !important; }
.roster-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}
.roster-title { font-weight: 800; }
.roster-meta { color: var(--muted); font-size: 12px; }
.blank {
  color: var(--muted);
  padding: 40px 8px;
}
.hero { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
h1 { margin: 0; font-size: 28px; font-weight: 800; letter-spacing: -0.02em; }
.sub { margin: 8px 0 0; color: var(--muted); max-width: 640px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.kpi { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px 16px; }
.k-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.k-num { font-size: 24px; font-weight: 800; }
.kpi.accent .k-num { color: var(--accent); }
.kpi.cyan .k-num { color: var(--cyan); }
.t { color: var(--muted); font-size: 12px; margin-top: 2px; }
.progress-wrap { max-width: 520px; }
.job { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.digest {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px;
}
.digest-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.digest-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.digest-share.exporting {
  padding: 8px 4px 0;
  overflow: visible;
  height: auto;
  max-height: none;
}
.share-only { display: none; }
.digest-share.exporting .share-only { display: block; }
.digest-brand { margin: 0 0 10px; color: var(--muted); font-size: 12px; letter-spacing: 0.08em; }
.share-footer { display: none; }
.digest-share.exporting .share-footer {
  display: block;
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 0.12em;
}
.digest-empty { color: var(--muted); font-size: 13px; margin: 0; }
.digest-history {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 120px;
  overflow: auto;
  margin-bottom: 12px;
}
.h-item {
  appearance: none;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--ink);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.h-item:hover { background: var(--panel2); }
.h-item.active { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
.digest-body h2 { margin: 4px 0 8px; font-size: 20px; }
.digest-kicker { color: var(--muted); font-size: 12px; }
.digest-summary { margin: 0 0 12px; line-height: 1.7; }
.digest-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; font-weight: 600; }
.digest-block { margin-top: 12px; }
.digest-item { margin-bottom: 8px; }
.digest-item p { margin: 2px 0 0; color: var(--muted); font-size: 13px; line-height: 1.6; }
.digest-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.digest-tags span {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
}
.digest-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 12px;
}
.digest-cols p { margin: 0 0 4px; font-size: 13px; }
@media (max-width: 980px) {
  .page { grid-template-columns: 1fr; height: auto; }
  .kpis { grid-template-columns: 1fr 1fr; }
  .digest-cols { grid-template-columns: 1fr; }
  .table { min-height: 280px; }
}
</style>
