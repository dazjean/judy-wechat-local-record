<template>
  <el-container class="shell">
    <el-aside width="224px" class="aside">
      <div class="brand">
        <div class="name">Judy</div>
        <div class="tagline">本机微信会话分析</div>
      </div>
      <el-menu
        class="nav"
        :key="menuKey"
        :router="true"
        :default-active="activeMenu"
        :default-openeds="defaultOpeneds"
      >
        <el-menu-item index="/">客户雷达</el-menu-item>
        <el-menu-item index="/sync">微信同步</el-menu-item>
        <el-menu-item index="/conversations">会话明细</el-menu-item>
        <el-menu-item index="/metrics">效率统计</el-menu-item>
        <el-sub-menu index="analysis">
          <template #title>诊断报告</template>
          <el-menu-item
            v-for="scene in reportScenes"
            :key="scene.id"
            :index="`/analysis/${scene.id}`"
          >{{ scene.name }}</el-menu-item>
          <el-menu-item v-if="!reportScenes.length" index="/prompts" disabled>暂无场景</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/groups">群画像</el-menu-item>
        <el-menu-item index="/prompts">提示词</el-menu-item>
        <el-menu-item index="/settings">系统设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <template v-if="showRange">
          <span class="label">查看范围</span>
          <el-date-picker
            v-model="range"
            type="daterange"
            unlink-panels
            clearable
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
          />
          <span class="hint">{{ rangeHint }}</span>
        </template>
        <span v-else class="hint">{{ pageHint }}</span>
        <span v-if="viewingOther" class="hint view-other">
          正在查看历史微信号 {{ viewingLabel }}，同步仍写入当前登录号。
          <el-button link type="primary" @click="setViewing(null)">回到当前登录号</el-button>
        </span>
      </el-header>
      <el-main class="main" :class="{ fill: isFillPage }">
        <router-view />
      </el-main>
    </el-container>
    <div v-if="licenseBlock" class="license-mask">
      <div class="license-panel">
        <div class="eyebrow">Judy</div>
        <h2>{{ overlayTitle }}</h2>
        <p class="tagline">本机微信会话分析</p>
        <p>{{ licenseBlock.message }}</p>
        <p v-if="licenseBlock.customer" class="meta">授权客户：{{ licenseBlock.customer }}</p>
        <p v-if="licenseBlock.mode === 'pending_wechat'" class="meta">请先登录约定微信，并以管理员运行「微信读取初始化」，然后点重试。</p>
        <el-button type="primary" @click="loadLicense">重试</el-button>
      </div>
    </div>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, provide, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { formatDate } from "../formatTime";
import { api } from "../api";
import { getViewingAccountId, setViewingAccountId } from "../accountScope";

const route = useRoute();
const range = ref(null);
const filter = ref({ start_date: "", end_date: "" });
const license = ref({ ok: true, mode: "development", message: "", customer: "" });
const licenseBlock = computed(() => (license.value?.ok ? null : license.value));
const overlayTitle = computed(() => (license.value?.mode === "offline" ? "本机服务未连接" : "未授权"));
const reportScenes = ref([]);
const accounts = ref([]);
const viewingAccountId = ref(getViewingAccountId());
const currentAccount = computed(() => accounts.value.find((a) => a.is_current) || accounts.value[0] || null);
const viewingAccount = computed(() => {
  if (!viewingAccountId.value) return currentAccount.value;
  return accounts.value.find((a) => a.id === viewingAccountId.value) || currentAccount.value;
});
const viewingOther = computed(() => {
  const cur = currentAccount.value;
  const view = viewingAccount.value;
  return Boolean(cur && view && cur.id !== view.id);
});
const viewingLabel = computed(() => {
  const acc = viewingAccount.value;
  if (!acc) return "";
  return acc.display_name && acc.display_name !== acc.account_key
    ? `${acc.display_name}（${acc.account_key}）`
    : acc.account_key;
});

function setViewing(id) {
  const cur = currentAccount.value;
  if (!id || (cur && Number(id) === Number(cur.id))) {
    setViewingAccountId(null);
    viewingAccountId.value = null;
  } else {
    setViewingAccountId(id);
    viewingAccountId.value = id;
  }
  filter.value = { ...filter.value };
}

async function loadAccounts() {
  try {
    accounts.value = await api.accounts();
    const ids = new Set(accounts.value.map((a) => a.id));
    if (viewingAccountId.value && !ids.has(viewingAccountId.value)) {
      setViewing(null);
    }
  } catch {
    accounts.value = [];
  }
}
const analysisOpen = computed(() => route.path.startsWith("/analysis"));
const activeMenu = computed(() => route.path);
const defaultOpeneds = computed(() => (analysisOpen.value ? ["analysis"] : []));
const menuKey = computed(() => (analysisOpen.value ? "open" : "shut"));
const isFillPage = computed(() => ["/", "/conversations", "/groups"].includes(route.path));

async function loadReportScenes() {
  try {
    const rows = await api.prompts();
    reportScenes.value = rows.filter((p) => p.enabled && p.kind !== "group" && p.kind !== "group_digest");
  } catch {
    reportScenes.value = [];
  }
}

let licenseRetry = 0;
let licenseTimer = 0;

function isNetworkFailure(err) {
  return Boolean(err?.network) || /network error/i.test(err?.message || "");
}

async function loadLicense() {
  try {
    license.value = await api.license();
    licenseRetry = 0;
  } catch (err) {
    if (isNetworkFailure(err)) {
      license.value = {
        ok: false,
        mode: "offline",
        message: "无法连接本机服务。请确认已运行 scripts/start.sh，或 8090 端口上的 Judy 已启动。",
        customer: "",
      };
      if (licenseTimer) window.clearTimeout(licenseTimer);
      const delay = Math.min(1500 * (licenseRetry + 1), 5000);
      licenseRetry += 1;
      licenseTimer = window.setTimeout(loadLicense, delay);
      return;
    }
    license.value = { ok: false, mode: "invalid", message: err.message || "无法读取授权", customer: "" };
  }
}

onMounted(() => {
  loadLicense();
  loadReportScenes();
  loadAccounts();
});
onUnmounted(() => {
  if (licenseTimer) window.clearTimeout(licenseTimer);
});
watch(
  () => route.path,
  (path, prev) => {
    if (path === "/prompts" || prev === "/prompts") loadReportScenes();
    if (path === "/settings" || prev === "/settings" || path === "/sync") loadAccounts();
  }
);
provide("filter", filter);
provide("setDateRange", (start, end) => {
  range.value = start && end ? [start, end] : null;
});
provide("setViewingAccount", setViewing);
provide("accounts", accounts);
provide("currentAccount", currentAccount);
provide("viewingAccount", viewingAccount);

const showRange = computed(() => !["/sync", "/settings", "/prompts"].includes(route.path));
const pageHint = computed(() => {
  if (route.path === "/sync") return "只同步这些人、排除名单对全部同步生效；定时间隔自动同步，不能按库体积实时解密";
  if (route.path === "/prompts") return "提示词只在本机保存。诊断报告、群画像、群报各用各的场景。";
  if (analysisOpen.value) return "先选一个提示词场景，再看该场景留下的分析记录。";
  return "词表和模型配置对全部数据生效";
});

watch(
  range,
  (val) => {
    const start = Array.isArray(val) ? val[0] || "" : "";
    const end = Array.isArray(val) ? val[1] || "" : "";
    filter.value = { start_date: start, end_date: end };
  },
  { deep: true }
);

const rangeHint = computed(() => {
  if (filter.value.start_date && filter.value.end_date) {
    return `已筛选 ${formatDate(filter.value.start_date)} 至 ${formatDate(filter.value.end_date)}`;
  }
  return "未选日期时显示全部已同步数据";
});
</script>

<style scoped>
.shell { height: 100%; position: relative; }
.aside {
  display: flex;
  flex-direction: column;
  background: var(--bg2);
  color: var(--ink);
  border-right: 1px solid var(--line);
}
.brand {
  flex-shrink: 0;
  padding: 22px 20px 16px;
  text-align: left;
  line-height: 1.35;
  border-bottom: 1px solid var(--line);
}
.brand .name {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--warn);
}
.brand .tagline {
  margin-top: 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  letter-spacing: 0;
  line-height: 1.45;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.22em;
  color: var(--warn);
  font-weight: 600;
  margin-bottom: 8px;
}
.license-panel .tagline { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
.aside :deep(.nav) {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 10px 16px;
  border-right: none;
  background: transparent;
  --el-menu-item-height: 44px;
  --el-menu-sub-item-height: 40px;
}
.aside :deep(.el-menu) { border-right: none; background: transparent; }
.aside :deep(.el-menu-item),
.aside :deep(.el-sub-menu__title) {
  justify-content: flex-start;
  text-align: left;
  margin: 2px 0;
  padding: 0 10px !important;
  border-radius: 10px;
}
.aside :deep(.el-sub-menu .el-menu) {
  padding: 0 0 4px;
  background: transparent;
}
.aside :deep(.el-sub-menu .el-menu-item) {
  padding-left: 22px !important;
  padding-right: 10px !important;
  white-space: normal;
  line-height: 1.35;
  height: auto;
  min-height: 40px;
}
.aside :deep(.el-sub-menu__icon-arrow) {
  right: 12px;
  margin-top: 0;
}
.aside :deep(.el-menu-item.is-active) {
  background: var(--accent);
  color: #fff;
}
.aside :deep(.el-sub-menu.is-active > .el-sub-menu__title) { color: var(--accent); }
.header {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}
.main { background: var(--bg); }
.main.fill { overflow: hidden; display: flex; flex-direction: column; }
.main.fill :deep(> *) { flex: 1; min-height: 0; }
.label { color: var(--muted); white-space: nowrap; }
.hint { color: var(--muted); font-size: 13px; }
.view-other { display: inline-flex; align-items: center; gap: 4px; }
.license-mask {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(14, 17, 22, 0.86);
}
.license-panel {
  width: min(460px, calc(100% - 48px));
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 28px 24px;
}
.license-panel h2 { margin: 0 0 12px; font-size: 20px; }
.license-panel p { color: var(--muted); line-height: 1.6; margin: 0 0 10px; }
.license-panel .meta { font-size: 13px; }
</style>
