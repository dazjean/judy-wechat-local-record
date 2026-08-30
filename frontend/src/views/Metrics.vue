<template>
  <div>
    <el-card>
      <template #header>
        <div class="head">
          <span>效率统计</span>
          <el-button @click="rescan">重新统计</el-button>
        </div>
      </template>
      <el-table :data="rows" class="days" empty-text="当前范围没有统计" @row-click="openDay">
        <el-table-column label="日期" min-width="140">
          <template #default="{ row }">{{ formatDate(row.day) }}</template>
        </el-table-column>
        <el-table-column prop="conversation_count" label="会话" />
        <el-table-column prop="msg_count" label="消息" />
        <el-table-column label="首次响应">
          <template #default="{ row }">{{ row.first_response_label || "—" }}</template>
        </el-table-column>
        <el-table-column label="平均响应">
          <template #default="{ row }">{{ row.avg_response_label || "—" }}</template>
        </el-table-column>
        <el-table-column prop="timeout_count" label="超时" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { inject, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api";
import { formatDate, toIsoDate } from "../formatTime";

const filter = inject("filter");
const setDateRange = inject("setDateRange");
const router = useRouter();
const rows = ref([]);

async function load() {
  rows.value = await api.daily({
    start_date: filter.value.start_date,
    end_date: filter.value.end_date,
  });
}

function openDay(row) {
  const day = toIsoDate(row?.day);
  if (!day) return;
  setDateRange?.(day, day);
  router.push({ path: "/conversations" });
}

async function rescan() {
  await api.ruleScan();
  ElMessage.success("已重新统计");
  load();
}

onMounted(load);
watch(filter, load, { deep: true });
</script>

<style scoped>
.head { display: flex; justify-content: space-between; }
.days { cursor: pointer; }
</style>
