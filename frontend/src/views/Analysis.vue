<template>
  <div ref="shareRoot" class="report">
    <header class="hero">
      <div class="eyebrow">Diagnostic Report</div>
      <h1>{{ currentPromptName || "诊断报告" }}</h1>
      <p class="sub no-export">
        诊断报告是通用基座。客服、销售、社交都是场景，选一个提示词后发起分析。数字来自本机聊天，结论会按日期留存，不会覆盖以前的报告。
      </p>
      <p v-if="selectedTitle" class="share-only sub">{{ selectedTitle }} · {{ rangeLabel }}</p>
      <div class="meta">
        <span>样本：<b>{{ stats.conversation_count || 0 }} 段会话 / {{ stats.msg_count || 0 }} 条消息</b></span>
        <span>范围：<b>{{ rangeLabel }}</b></span>
        <span>提示词：<b>{{ currentPromptName || "默认" }}</b></span>
        <span class="no-export meta-actions">
          <el-button link type="primary" @click="goPrompts">管理提示词</el-button>
          <el-button type="primary" :loading="busy" @click="run">发起分析</el-button>
          <el-button :loading="exporting" :disabled="!canExport || busy" @click="exportImage">导出图片</el-button>
        </span>
      </div>
      <div v-if="job" class="progress-wrap no-export">
        <el-progress
          :percentage="displayPercent"
          :status="progressStatus"
          :indeterminate="analyzing && displayPercent < 12"
          striped
          :striped-flow="analyzing"
          :stroke-width="12"
          :show-text="false"
        />
        <p class="job">{{ progressText }}{{ job.error_message ? " · " + job.error_message : "" }}</p>
      </div>
      <p v-if="viewingHistory" class="job no-export">
        正在查看历史：{{ selectedTitle }}
        <el-button link type="primary" @click="loadResult">回到最新</el-button>
      </p>
    </header>

    <section class="history-panel no-export">
      <div class="sec-head">
        <div class="sec-no">00 / HISTORY</div>
        <div class="sec-title">
          本场景分析记录
          <span v-if="history.length" class="sec-count">{{ history.length }}</span>
        </div>
        <div class="sec-desc">只显示当前提示词场景留下的报告。按日期留存，点开查看当时的完整内容。</div>
      </div>
      <p v-if="!history.length" class="empty-history">本场景还没有分析记录。发起分析后会出现在这里。</p>
      <div v-else class="history-scroll" :class="{ expanded: historyExpanded }">
        <div v-for="g in historyGroups" :key="g.day" class="h-group">
          <div class="h-day">{{ g.label }} · {{ g.items.length }}</div>
          <button
            v-for="item in g.items"
            :key="item.id"
            type="button"
            class="h-item"
            :class="{ active: selectedResultId === item.id }"
            @click="openHistory(item)"
          >
            {{ item.title }}
          </button>
        </div>
        <button
          v-if="historyHiddenCount > 0 || historyExpanded"
          type="button"
          class="h-more"
          @click="historyExpanded = !historyExpanded"
        >
          {{ historyMoreLabel }}
        </button>
      </div>
    </section>

    <div v-if="profile" class="fighter">
      <span class="tag">{{ profile.style || "待判断风格" }}</span>
      <h2>{{ profile.title || "诊断画像" }}</h2>
      <p class="desc">{{ profile.summary }}</p>
      <div class="traits">
        <span v-for="t in profile.tags || []" :key="t">{{ t }}</span>
      </div>
    </div>

    <section>
      <div class="sec-head">
        <div class="sec-no">01 / RESPONSE</div>
        <div class="sec-title">{{ payload?.headline || "响应速度" }}</div>
        <div class="sec-desc">以客户消息到客服下一条回复的间隔计算。中位值看日常节奏，平均值容易被超长等待拉高。</div>
      </div>
      <div class="kpis">
        <div class="kpi accent">
          <div class="k-label"><i class="dot"></i>中位回复</div>
          <div class="k-num">{{ stats.median_label || "—" }}</div>
          <div class="k-sub">平均 {{ stats.avg_label || "—" }}</div>
        </div>
        <div class="kpi cyan">
          <div class="k-label"><i class="dot"></i>5 分钟内回复</div>
          <div class="k-num">{{ pct(stats.within_5min_pct) }}</div>
          <div class="k-sub">1 小时内 {{ pct(stats.within_1h_pct) }}</div>
        </div>
        <div class="kpi">
          <div class="k-label"><i class="dot"></i>可统计回复</div>
          <div class="k-num">{{ stats.reply_count || 0 }}<small>次</small></div>
          <div class="k-sub">超时未回应看客户雷达</div>
        </div>
      </div>
    </section>

    <section>
      <div class="sec-head">
        <div class="sec-no">02 / AFTER 17:00</div>
        <div class="sec-title">下班后的投入</div>
        <div class="sec-desc">按本机发出的消息统计小时分布。高亮区为 17 点后。</div>
      </div>
      <div class="band-block">
        <div class="band-label">
          <span>本机发出消息 24h 分布</span>
          <span>晚间占比 {{ pct(stats.evening_share_pct) }}</span>
        </div>
        <div class="band">
          <div
            v-for="(n, h) in hours"
            :key="h"
            class="bar"
            :class="{ evening: h >= 17 }"
          >
            <div class="fill" :style="{ height: barHeight(n) }" />
          </div>
        </div>
        <div class="band-x">
          <span v-for="h in 24" :key="h">{{ h - 1 }}</span>
        </div>
      </div>
      <div class="cutline"><span>17:00 下班线 · 高亮区为下班后时段</span></div>
      <div class="kpis">
        <div class="kpi accent">
          <div class="k-label"><i class="dot"></i>晚间对方消息回复率</div>
          <div class="k-num">{{ pct(stats.evening_reply_pct) }}</div>
          <div class="k-sub">17 点后对方发来 {{ stats.evening_customer || 0 }} 条</div>
        </div>
        <div class="kpi cyan">
          <div class="k-label"><i class="dot"></i>深夜(0–8点)工作量</div>
          <div class="k-num">{{ pct(stats.night_share_pct) }}</div>
          <div class="k-sub">发出消息 {{ stats.cs_total || 0 }} 条里的占比</div>
        </div>
      </div>
    </section>

    <section v-if="(payload?.dimensions || []).length">
      <div class="sec-head">
        <div class="sec-no">03 / DIMENSIONS</div>
        <div class="sec-title">六个维度</div>
        <div class="sec-desc">基于代表性对话的定性评分（0–100），不是系统自动打分，每项应有原话支撑。</div>
      </div>
      <div class="dims">
        <div v-for="d in payload.dimensions" :key="d.name" class="dim">
          <div class="d-top">
            <span class="d-name">{{ d.name }}</span>
            <span class="d-score">{{ d.score }}/100</span>
          </div>
          <div class="d-bar">
            <div class="d-track"><div class="d-fill" :style="{ width: (d.score || 0) + '%' }" /></div>
          </div>
          <div class="d-note">{{ d.note }}</div>
        </div>
      </div>
    </section>

    <section v-if="(payload?.strengths || []).length || (payload?.risks || []).length">
      <div class="sec-head">
        <div class="sec-no">04 / STRENGTHS & RISKS</div>
        <div class="sec-title">强项与踩过的坑</div>
      </div>
      <div class="split">
        <div class="card good">
          <h3>▲ 值得保留</h3>
          <ul>
            <li v-for="(x, i) in payload.strengths || []" :key="'s'+i">
              <b>
                <a v-if="itemId(x)" href="#" @click.prevent="goConv(itemId(x))">{{ x.title }}</a>
                <span v-else>{{ x.title }}</span>
              </b>
              <span>{{ x.contact ? x.contact + " · " : "" }}{{ x.detail }}</span>
              <em v-if="x.quote">“{{ x.quote }}”</em>
            </li>
          </ul>
        </div>
        <div class="card bad">
          <h3>▼ 踩过的坑</h3>
          <ul>
            <li v-for="(x, i) in payload.risks || []" :key="'r'+i">
              <b>
                <a v-if="itemId(x)" href="#" @click.prevent="goConv(itemId(x))">{{ x.title }}</a>
                <span v-else>{{ x.title }}</span>
              </b>
              <span>{{ x.contact ? x.contact + " · " : "" }}{{ x.detail }}</span>
              <em v-if="x.quote">“{{ x.quote }}”</em>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section v-if="payload?.conclusion">
      <div class="sec-head">
        <div class="sec-no">05 / CONCLUSION</div>
        <div class="sec-title">{{ payload.conclusion.verdict || "结论" }}</div>
      </div>
      <div class="takeaway">
        <p class="tc">{{ payload.conclusion.playbook }}</p>
        <div v-for="(line, i) in payload.conclusion.red_lines || []" :key="'rl'+i" class="rule">{{ line }}</div>
      </div>
    </section>

    <section>
      <div class="sec-head">
        <div class="sec-no">06 / FOLLOW-UPS</div>
        <div class="sec-title">还需要跟进的会话</div>
        <div class="sec-desc">点客户名进入原聊天。没有分析结果时，先看禁用词命中。</div>
      </div>
      <el-alert v-if="!payload && !busy" class="no-export" :title="emptyTitle" type="info" :closable="false" />
      <div v-if="payload" class="follow">
        <div>
          <h4>高频问题</h4>
          <el-table :data="payload.topics || []" empty-text="暂无">
            <el-table-column prop="name" label="问题" />
            <el-table-column prop="count" label="频次" width="90" />
          </el-table>
        </div>
        <div>
          <h4>未解决 / 追问 / 关注</h4>
          <ul class="links">
            <li v-for="(x, i) in followItems" :key="'f'+i">
              <a v-if="itemId(x)" href="#" @click.prevent="goConv(itemId(x))">{{ itemText(x) }}</a>
              <span v-else>{{ itemText(x) }}</span>
            </li>
          </ul>
        </div>
      </div>
      <h4>禁用词命中</h4>
      <el-table :data="hits" empty-text="当前范围没有命中" @row-click="openHit">
        <el-table-column prop="contact" label="客户" />
        <el-table-column prop="term" label="词条" width="100" />
        <el-table-column prop="snippet" label="摘录" />
        <el-table-column label="时间" min-width="210">
          <template #default="{ row }">{{ formatTime(row.msg_time) }}</template>
        </el-table-column>
      </el-table>
    </section>
    <footer class="share-footer">Judy · 诊断报告</footer>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api";
import { exportSharePng, shareFilename } from "../exportImage";
import { formatDate, formatTime } from "../formatTime";

const filter = inject("filter");
const route = useRoute();
const router = useRouter();
const loading = ref(false);
const job = ref(null);
const displayPercent = ref(0);
const payload = ref(null);
const stats = ref({});
const hits = ref([]);
const prompts = ref([]);
const promptId = computed(() => {
  const n = Number(route.params.promptId);
  return Number.isFinite(n) && n > 0 ? n : null;
});
const HISTORY_PREVIEW = 10;
const history = ref([]);
const historyExpanded = ref(false);
const selectedResultId = ref(null);
const latestResultId = ref(null);
const selectedTitle = ref("");
const shareRoot = ref(null);
const exporting = ref(false);
let timer = null;
let tickTimer = null;

const STATUS = { queued: "排队中", running: "分析中", succeeded: "已完成", failed: "失败" };
const statusLabel = computed(() => STATUS[job.value?.status] || job.value?.status || "");
const analyzing = computed(() => ["queued", "running"].includes(job.value?.status || ""));
const busy = computed(() => loading.value || analyzing.value);
const progressStatus = computed(() => {
  if (job.value?.status === "failed") return "exception";
  if (job.value?.status === "succeeded") return "success";
  return undefined;
});
const progressText = computed(() => {
  const label = job.value?.progress_label || statusLabel.value;
  return label ? `${label} ${displayPercent.value}%` : `${displayPercent.value}%`;
});
const profile = computed(() => payload.value?.profile || null);
const hours = computed(() => stats.value.hour_cs || Array(24).fill(0));
const rangeLabel = computed(() => {
  if (filter.value.start_date && filter.value.end_date) {
    return `${formatTime(filter.value.start_date)} 至 ${formatTime(filter.value.end_date)}`;
  }
  return "全部已同步";
});
const currentPromptName = computed(() => {
  const hit = prompts.value.find((p) => p.id === promptId.value);
  return hit?.name || "";
});
const emptyTitle = computed(() => {
  if (filter.value.start_date || filter.value.end_date) {
    return "当前查看范围还没有诊断结论，请点「发起分析」。响应数字已按当前范围算好。";
  }
  return "配置模型 API 并完成微信同步后，点「发起分析」生成强项、踩坑和结论。";
});
const canExport = computed(() => Boolean(payload.value) || Number(stats.value.msg_count || 0) > 0);
const viewingHistory = computed(() => {
  return Boolean(selectedResultId.value && latestResultId.value && selectedResultId.value !== latestResultId.value);
});
const visibleHistory = computed(() => {
  if (historyExpanded.value || history.value.length <= HISTORY_PREVIEW) return history.value;
  return history.value.slice(0, HISTORY_PREVIEW);
});
const historyHiddenCount = computed(() => Math.max(0, history.value.length - HISTORY_PREVIEW));
const historyMoreLabel = computed(() => {
  if (historyExpanded.value) return "收起较早记录";
  return `还有 ${historyHiddenCount.value} 条更早的记录`;
});
const historyGroups = computed(() => {
  const groups = [];
  const map = {};
  for (const item of visibleHistory.value) {
    const day = (item.created_at || "").slice(0, 10) || "未标注日期";
    if (!map[day]) {
      map[day] = { day, label: day === "未标注日期" ? day : formatDate(day), items: [] };
      groups.push(map[day]);
    }
    map[day].items.push(item);
  }
  return groups;
});
const followItems = computed(() => {
  const p = payload.value || {};
  return [...(p.unresolved || []), ...(p.repeated || []), ...(p.attention || [])];
});

function pct(v) {
  return v == null ? "—" : `${v}%`;
}

function barHeight(n) {
  const max = stats.value.hour_max || 1;
  if (!n) return "0%";
  return `${Math.max(8, Math.round((n / max) * 100))}%`;
}

function itemId(x) {
  if (!x || typeof x === "string") return 0;
  return Number(x.conversation_id) || 0;
}

function itemText(x) {
  if (!x) return "";
  if (typeof x === "string") return x;
  const name = x.contact ? `${x.contact}：` : "";
  const extra = x.reason ? `（${x.reason}）` : "";
  return `${name}${x.summary || x.title || ""}${extra}`;
}

function goConv(id) {
  router.push({ path: "/conversations", query: { id: String(id) } });
}

function openHit(row) {
  if (!row?.conversation_id) return;
  goConv(row.conversation_id);
}

function goPrompts() {
  router.push("/prompts");
}

async function exportImage() {
  if (!shareRoot.value || exporting.value) return;
  exporting.value = true;
  try {
    const title = selectedTitle.value || currentPromptName.value || "诊断报告";
    const result = await exportSharePng(shareRoot.value, {
      filename: shareFilename(title, "诊断报告"),
      title,
    });
    if (result === "shared") ElMessage.success("已打开分享");
    else if (result === "downloaded") ElMessage.success("已导出图片，可直接转发分享");
  } catch {
    ElMessage.error("导出失败，请稍后重试");
  } finally {
    exporting.value = false;
  }
}

async function loadPrompts() {
  const rows = (await api.prompts()).filter((p) => p.enabled && p.kind !== "group" && p.kind !== "group_digest");
  prompts.value = rows;
  if (promptId.value) return true;
  const def = rows.find((p) => p.is_default) || rows[0];
  if (def) {
    await router.replace(`/analysis/${def.id}`);
    return false;
  }
  return true;
}

async function loadHits() {
  hits.value = await api.hits({
    kind: "forbidden",
    start_date: filter.value.start_date,
    end_date: filter.value.end_date,
  });
}

function sceneHistory(rows) {
  const pid = promptId.value;
  if (!pid) return [];
  return (rows || []).filter((item) => Number(item.prompt_id) === Number(pid));
}

async function loadResult() {
  if (!promptId.value) return;
  const data = await api.analysisResults({
    start_date: filter.value.start_date,
    end_date: filter.value.end_date,
    prompt_id: promptId.value || undefined,
  });
  payload.value = data.payload;
  stats.value = data.stats || {};
  history.value = sceneHistory(data.history);
  historyExpanded.value = false;
  selectedResultId.value = data.result_id || null;
  latestResultId.value = data.result_id || null;
  selectedTitle.value = data.title || "";
}

async function openHistory(item) {
  const data = await api.analysisResult(item.id);
  payload.value = data.payload;
  if (data.history) history.value = sceneHistory(data.history);
  selectedResultId.value = data.result_id || item.id;
  selectedTitle.value = data.title || item.title || "";
}

async function run() {
  if (analyzing.value) return;
  displayPercent.value = 5;
  loading.value = true;
  try {
    const created = await api.startAnalysis({
      start_date: filter.value.start_date,
      end_date: filter.value.end_date,
      prompt_id: promptId.value || undefined,
      kind: "report",
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
    if (displayPercent.value < cap) {
      displayPercent.value = Math.min(cap, displayPercent.value + 1);
    }
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
      if (job.value.status === "succeeded") loadResult();
    }
  }, 1500);
}

function stop() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

onMounted(async () => {
  const ready = await loadPrompts();
  loadHits();
  if (ready && promptId.value) loadResult();
});
watch(filter, () => {
  loadHits();
  if (promptId.value) loadResult();
}, { deep: true });
watch(
  () => route.params.promptId,
  (id, prev) => {
    if (id === prev) return;
    stop();
    stopTick();
    job.value = null;
    displayPercent.value = 0;
    if (promptId.value) loadResult();
  }
);
onUnmounted(() => {
  stop();
  stopTick();
});
</script>

<style scoped>
.report { max-width: 1080px; margin: 0 auto; color: var(--ink); }
.report.exporting {
  padding: 28px 40px 24px;
  overflow: visible;
  height: auto;
  max-height: none;
  max-width: none;
}
.report.exporting :deep(.el-table),
.report.exporting :deep(.el-table__inner-wrapper),
.report.exporting :deep(.el-table__body-wrapper),
.report.exporting :deep(.el-table__header-wrapper),
.report.exporting :deep(.el-scrollbar),
.report.exporting :deep(.el-scrollbar__wrap),
.report.exporting :deep(.el-scrollbar__view) {
  height: auto !important;
  max-height: none !important;
  max-width: none !important;
  overflow: visible !important;
}
.share-only { display: none; }
.report.exporting .no-export { display: none !important; }
.report.exporting .share-only { display: block; }
.share-footer { display: none; }
.report.exporting .share-footer {
  display: block;
  margin-top: 28px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 0.12em;
}
.meta-actions { display: inline-flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.hero { padding: 12px 0 28px; border-bottom: 1px solid var(--line); }
.eyebrow { font-size: 12px; letter-spacing: 0.22em; color: var(--warn); font-weight: 600; text-transform: uppercase; margin-bottom: 14px; }
h1 { font-size: clamp(28px, 5vw, 48px); font-weight: 800; letter-spacing: -0.02em; line-height: 1.12; margin: 0; }
.sub { margin-top: 14px; color: var(--muted); max-width: 720px; }
.meta { margin-top: 18px; display: flex; gap: 18px; flex-wrap: wrap; align-items: center; color: var(--muted); font-size: 13px; }
.meta b { color: var(--ink); }
.job { margin-top: 10px; color: var(--muted); font-size: 13px; }
.progress-wrap { margin-top: 16px; max-width: 560px; }
.progress-wrap :deep(.el-progress-bar__outer) { background: var(--bg2); }
.progress-wrap :deep(.el-progress-bar__inner) { background: linear-gradient(90deg, var(--accent), #ff9a6a); }
.history-panel { padding-top: 28px; }
.empty-history { color: var(--muted); font-size: 13px; margin: 12px 0 0; }
.sec-count {
  margin-left: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--muted);
}
.history-scroll {
  margin-top: 16px;
  max-height: 420px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
}
.history-scroll.expanded { max-height: 560px; }
.h-more {
  appearance: none;
  width: calc(100% - 16px);
  margin: 0 8px 10px;
  padding: 8px 12px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
}
.h-more:hover { color: var(--accent); border-color: var(--accent); }
.h-day {
  position: sticky;
  top: 0;
  z-index: 1;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--muted);
  background: var(--panel);
  padding: 8px 12px 6px;
}
.h-group { display: flex; flex-direction: column; padding: 0 8px 8px; }
.h-item {
  appearance: none;
  width: 100%;
  background: transparent;
  border: 1px solid transparent;
  color: var(--ink);
  border-radius: 8px;
  padding: 7px 10px;
  cursor: pointer;
  font-size: 13px;
  text-align: left;
  line-height: 1.4;
}
.h-item:hover { background: var(--panel2); }
.h-item.active { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
.fighter { margin: 28px 0 0; padding: 28px; background: var(--bg2); border: 1px solid var(--line); }
.tag { display: inline-block; font-size: 11px; letter-spacing: 0.14em; padding: 4px 10px; border-radius: 100px; font-weight: 600; margin-bottom: 14px; background: var(--accent-dim); color: var(--accent); }
.fighter h2 { font-size: 26px; font-weight: 800; margin: 0; }
.desc { margin-top: 12px; color: #cfd6df; }
.traits { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px; }
.traits span { font-size: 12px; padding: 4px 10px; border-radius: 8px; border: 1px solid rgba(255, 106, 61, 0.35); color: #ffb39a; }
section { padding: 40px 0; border-bottom: 1px solid var(--line); }
.sec-no { font-size: 12px; letter-spacing: 0.2em; color: var(--muted); font-weight: 600; }
.sec-title { font-size: clamp(22px, 3.4vw, 30px); font-weight: 800; margin-top: 6px; letter-spacing: -0.01em; }
.sec-desc { color: var(--muted); font-size: 14px; margin-top: 8px; max-width: 720px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
.kpi { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px; }
.k-label { font-size: 12px; color: var(--muted); margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); display: inline-block; }
.k-num { font-size: 30px; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.k-num small { font-size: 14px; color: var(--muted); font-weight: 500; margin-left: 2px; }
.k-sub { font-size: 12px; color: var(--muted); margin-top: 6px; }
.kpi.accent .k-num { color: var(--accent); }
.kpi.accent .dot { background: var(--accent); }
.kpi.cyan .k-num { color: var(--cyan); }
.kpi.cyan .dot { background: var(--cyan); }
.band-block { margin-bottom: 18px; }
.band-label { display: flex; justify-content: space-between; color: var(--muted); font-size: 13px; margin-bottom: 10px; }
.band { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; height: 56px; align-items: end; }
.bar { background: var(--line); border-radius: 3px 3px 0 0; position: relative; min-height: 2px; }
.bar.evening { background: rgba(255, 201, 74, 0.28); }
.fill { position: absolute; bottom: 0; left: 0; right: 0; border-radius: 3px 3px 0 0; background: var(--accent); }
.band-x { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; margin-top: 6px; }
.band-x span { font-size: 9px; color: var(--muted); text-align: center; }
.cutline { margin: 16px 0 22px; border-top: 1px dashed var(--line); position: relative; }
.cutline span { position: absolute; right: 0; top: -9px; background: var(--bg); padding: 0 8px; font-size: 11px; color: var(--warn); }
.dims { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.dim { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 18px 20px; }
.d-top { display: flex; justify-content: space-between; margin-bottom: 12px; }
.d-name { font-weight: 700; }
.d-score { font-size: 12px; color: var(--muted); }
.d-track { height: 8px; background: var(--bg2); border-radius: 6px; overflow: hidden; }
.d-fill { height: 100%; border-radius: 6px; background: linear-gradient(90deg, var(--accent), #ff9a6a); }
.d-note { font-size: 12px; color: var(--muted); margin-top: 10px; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 22px; }
.card h3 { font-size: 16px; font-weight: 800; margin: 0 0 16px; }
.card.good h3 { color: var(--good); }
.card.bad h3 { color: var(--bad); }
.card ul { list-style: none; padding: 0; margin: 0; }
.card li { padding: 10px 0; border-bottom: 1px solid var(--bg2); font-size: 14px; color: #d6dce3; }
.card li:last-child { border-bottom: none; }
.card li b { display: block; color: var(--ink); margin-bottom: 2px; }
.card li span, .card li em { color: var(--muted); font-size: 13px; font-style: normal; display: block; }
.takeaway { background: linear-gradient(135deg, var(--bg2), var(--panel)); border: 1px solid var(--line); border-radius: 16px; padding: 30px; }
.tc { font-size: 15px; margin: 0 0 16px; }
.rule { background: var(--bg); border-left: 3px solid var(--warn); padding: 12px 16px; border-radius: 0 10px 10px 0; font-size: 14px; color: #e8e3d8; margin-bottom: 10px; }
.follow { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 16px 0; }
h4 { margin: 18px 0 10px; }
.links { list-style: none; padding: 0; }
.links li { padding: 8px 0; border-bottom: 1px solid var(--line); }
@media (max-width: 760px) {
  .dims, .split, .follow { grid-template-columns: 1fr; }
}
</style>
