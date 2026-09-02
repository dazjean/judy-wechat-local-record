<template>
  <div class="page">
    <div class="kpis">
      <div
        v-for="card in cards"
        :key="card.key"
        class="kpi"
        :class="{ on: focus === card.key, accent: card.accent }"
        @click="setFocus(card.key)"
      >
        <div class="k-label">{{ card.label }}</div>
        <div class="k-num">{{ card.value }}</div>
      </div>
    </div>
    <el-alert
      v-if="syncHint"
      :title="syncHint"
      type="info"
      show-icon
      :closable="false"
      style="margin-top: 16px"
    />
    <el-alert
      v-else-if="hint"
      :title="hint"
      type="info"
      show-icon
      :closable="false"
      style="margin-top: 16px"
    />
    <el-card class="radar" style="margin-top: 16px">
      <template #header>
        <div class="head">
          <span>好友雷达</span>
          <span class="t">点一行打开会话。优先排风险、待回复、已发未回和未兑承诺。</span>
        </div>
      </template>
      <el-table :data="rows" height="100%" empty-text="当前范围没有好友会话" @row-click="openRow">
        <el-table-column label="好友" min-width="140">
          <template #default="{ row }">
            <div>{{ row.contact }}</div>
            <div v-if="row.contact_sub" class="sub">{{ row.contact_sub }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="主诉求" min-width="200">
          <template #default="{ row }">
            <div v-if="row.intent && row.intent !== '—'" class="intent">{{ row.intent }}</div>
            <div class="snip">{{ row.snippet }}</div>
          </template>
        </el-table-column>
        <el-table-column min-width="200">
          <template #header>
            <el-tooltip content="根据聊天记录规则自动判断，非微信好友标签" placement="top">
              <span class="warn-head">预警</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <el-tag v-if="row.risk" type="danger" size="small">风险</el-tag>
            <el-tag v-if="row.precursor" type="danger" size="small" style="margin-left: 4px">退费前兆</el-tag>
            <el-tag v-if="row.timeout" type="warning" size="small" style="margin-left: 4px">超时未回</el-tag>
            <el-tag v-if="row.quoted" type="warning" size="small" style="margin-left: 4px">已发未回</el-tag>
            <el-tag v-if="row.promise" type="warning" size="small" style="margin-left: 4px">承诺未兑</el-tag>
            <el-tag v-if="row.decision" size="small" style="margin-left: 4px">决策中</el-tag>
            <el-tag v-if="row.forbidden" type="danger" size="small" style="margin-left: 4px">禁用词</el-tag>
            <el-tag v-if="row.returning" type="info" size="small" style="margin-left: 4px">老客</el-tag>
            <span
              v-if="!row.risk && !row.precursor && !row.timeout && !row.quoted && !row.promise && !row.decision && !row.forbidden && !row.returning"
              class="t"
            >—</span>
          </template>
        </el-table-column>
        <el-table-column label="最近消息" min-width="210">
          <template #default="{ row }">{{ formatTime(row.last_msg_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api";
import { formatTime } from "../formatTime";

const filter = inject("filter");
const router = useRouter();
const summary = ref({});
const rows = ref([]);
const status = ref({});
const focus = ref("");

const cards = computed(() => [
  { key: "", label: "好友", value: summary.value.customers ?? 0 },
  { key: "pending", label: "待回复", value: summary.value.pending ?? 0, accent: true },
  { key: "quoted", label: "已发未回", value: summary.value.quoted ?? 0 },
  { key: "risk", label: "风险", value: summary.value.risk ?? 0 },
  { key: "quiet", label: "沉寂", value: summary.value.quiet ?? 0 },
]);

const hint = computed(() => status.value.hint || "");
const syncHint = computed(() => {
  const s = overviewSync.value;
  if (!s) return "";
  const map = { succeeded: "成功", failed: "失败", running: "进行中", queued: "排队中" };
  return `上次同步 ${formatTime(s.at)} · ${map[s.status] || s.status} · 写入 ${s.written ?? 0} 条`;
});
const overviewSync = ref(null);

function statusType(code) {
  return { pending: "warning", new: "", active: "success", quiet: "info" }[code] || "info";
}

function setFocus(key) {
  focus.value = focus.value === key ? "" : key;
  loadRadar();
}

function openRow(row) {
  if (!row?.conversation_id) return;
  router.push({ path: "/conversations", query: { id: String(row.conversation_id) } });
}

async function loadRadar() {
  const data = await api.radar({
    start_date: filter.value.start_date,
    end_date: filter.value.end_date,
    status: focus.value,
  });
  summary.value = data.summary || {};
  rows.value = data.items || [];
}

async function load() {
  await loadRadar();
  try {
    const overview = await api.overview({
      start_date: filter.value.start_date,
      end_date: filter.value.end_date,
    });
    overviewSync.value = overview.last_sync || null;
  } catch {
    overviewSync.value = null;
  }
  status.value = await api.readerStatus();
}

onMounted(load);
watch(filter, load, { deep: true });
</script>

<style scoped>
.page {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }
.kpi {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 20px;
  cursor: pointer;
}
.kpi:hover, .kpi.on { border-color: var(--accent); }
.k-label { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
.k-num { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; }
.kpi.accent .k-num { color: var(--accent); }
.t { color: var(--muted); font-size: 12px; }
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.radar {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.radar :deep(.el-card__body) {
  flex: 1;
  min-height: 280px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.warn-head { cursor: help; border-bottom: 1px dashed var(--muted); }
.sub { color: var(--muted); font-size: 12px; margin-top: 2px; line-height: 1.35; word-break: break-word; }
.intent { font-weight: 600; }
.snip { color: var(--muted); font-size: 12px; margin-top: 2px; word-break: break-word; }
@media (max-width: 900px) {
  .page { height: auto; }
  .kpis { grid-template-columns: 1fr 1fr; }
  .radar :deep(.el-card__body) { min-height: 360px; }
}
</style>
