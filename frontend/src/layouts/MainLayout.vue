<template>
  <el-container class="shell">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <div class="name">Judy</div>
        <div class="tagline">本机微信会话分析</div>
      </div>
      <el-menu :router="true" :default-active="$route.path">
        <el-menu-item index="/">客户雷达</el-menu-item>
        <el-menu-item index="/sync">微信同步</el-menu-item>
        <el-menu-item index="/conversations">会话明细</el-menu-item>
        <el-menu-item index="/metrics">效率统计</el-menu-item>
        <el-menu-item index="/analysis">诊断报告</el-menu-item>
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
      </el-header>
      <el-main class="main" :class="{ fill: $route.path === '/conversations' || $route.path === '/' || $route.path === '/groups' }">
        <router-view />
      </el-main>
    </el-container>
    <div v-if="licenseBlock" class="license-mask">
      <div class="license-panel">
        <div class="eyebrow">Judy</div>
        <h2>未授权</h2>
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
import { computed, onMounted, provide, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { formatDate } from "../formatTime";
import { api } from "../api";

const route = useRoute();
const range = ref(null);
const filter = ref({ start_date: "", end_date: "" });
const license = ref({ ok: true, mode: "development", message: "", customer: "" });
const licenseBlock = computed(() => (license.value?.ok ? null : license.value));

async function loadLicense() {
  try {
    license.value = await api.license();
  } catch (err) {
    license.value = { ok: false, mode: "invalid", message: err.message || "无法读取授权", customer: "" };
  }
}

onMounted(loadLicense);
provide("filter", filter);
provide("setDateRange", (start, end) => {
  range.value = start && end ? [start, end] : null;
});

const showRange = computed(() => !["/sync", "/settings", "/prompts"].includes(route.path));
const pageHint = computed(() => {
  if (route.path === "/sync") return "只同步这些人、排除名单对全部同步生效；定时间隔自动同步，不能按库体积实时解密";
  if (route.path === "/prompts") return "提示词只在本机保存。诊断报告、群画像、群报各用各的场景。";
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
.aside { background: var(--bg2); color: var(--ink); border-right: 1px solid var(--line); }
.brand {
  padding: 22px 16px 18px;
  text-align: center;
  line-height: 1.35;
}
.brand .name {
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
  line-height: 1.4;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.22em;
  color: var(--warn);
  font-weight: 600;
  margin-bottom: 8px;
}
.license-panel .tagline { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
.aside :deep(.el-menu) { border-right: none; background: transparent; }
.aside :deep(.el-menu-item.is-active) { background: var(--accent); color: #fff; }
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
