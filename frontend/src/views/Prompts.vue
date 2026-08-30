<template>
  <el-card>
    <template #header>
      <div class="head">
        <span>提示词</span>
        <el-button type="primary" @click="openNew">新增场景</el-button>
      </div>
    </template>
    <p class="hint">
      诊断报告、群画像、群日报/周报是三套提示词。系统预置客服/销售/社交诊断，销售加好友、客服家长群、社交关系三种群画像，以及群日报和群周报。也可自己新增。新增时可先写一句大白话，点「一键生成」再改。
    </p>
    <el-table :data="rows">
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">{{ kindLabel(row.kind) }}</template>
      </el-table-column>
      <el-table-column label="默认" width="80">
        <template #default="{ row }">{{ row.is_default ? "是" : "" }}</template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" :disabled="row.is_default" @change="(v) => toggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="!row.is_default" link type="primary" @click="makeDefault(row)">设为默认</el-button>
          <el-button v-if="!row.is_default" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
  <el-dialog v-model="visible" :title="form.id ? '编辑提示词' : '新增场景'" width="720px" destroy-on-close>
    <el-form label-width="100px">
      <el-form-item label="名称">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="类型">
        <el-select v-model="form.kind" style="width: 200px">
          <el-option label="诊断报告" value="report" />
          <el-option label="分析场景" value="scene" />
          <el-option label="群画像" value="group" />
          <el-option label="群日报/周报" value="group_digest" />
        </el-select>
      </el-form-item>
      <el-form-item label="一句话需求">
        <div class="brief">
          <el-input v-model="form.brief" :placeholder="briefPlaceholder" />
          <el-button type="primary" :loading="generating" @click="generate">一键生成</el-button>
        </div>
      </el-form-item>
      <el-form-item label="提示词">
        <el-input v-model="form.body" type="textarea" :rows="16" placeholder="给模型的系统提示词，可用上面的一句话生成后再改" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "../api";

const rows = ref([]);
const visible = ref(false);
const generating = ref(false);
const form = reactive({ id: 0, name: "", kind: "report", body: "", brief: "" });
const briefPlaceholder = computed(() => {
  if (form.kind === "group") return "例如：销售要看群里谁活跃、值不值得加好友";
  if (form.kind === "group_digest") return "例如：帮我写家长群日报，重点看作业和投诉";
  return "例如：帮我看销售跟进里谁在犹豫";
});

function kindLabel(kind) {
  if (kind === "group") return "群画像";
  if (kind === "group_digest") return "群报";
  if (kind === "report") return "诊断报告";
  return "分析场景";
}

async function load() {
  rows.value = await api.prompts();
}

function openNew() {
  form.id = 0;
  form.name = "";
  form.kind = "report";
  form.body = "";
  form.brief = "";
  visible.value = true;
}

function openEdit(row) {
  form.id = row.id;
  form.name = row.name;
  form.kind = row.kind;
  form.body = row.body;
  form.brief = "";
  visible.value = true;
}

async function generate() {
  if (!form.brief.trim()) {
    ElMessage.warning("请先写一句大白话需求");
    return;
  }
  generating.value = true;
  try {
    const data = await api.generatePrompt({ brief: form.brief.trim(), kind: form.kind });
    form.body = data.body || "";
    ElMessage.success("已生成，请检查后保存");
  } catch (e) {
    ElMessage.error(e.message);
  } finally {
    generating.value = false;
  }
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning("请填写名称");
    return;
  }
  if (form.id) {
    await api.patchPrompt(form.id, { name: form.name.trim(), kind: form.kind, body: form.body });
  } else {
    await api.addPrompt({ name: form.name.trim(), kind: form.kind, body: form.body, enabled: true });
  }
  ElMessage.success("已保存");
  visible.value = false;
  load();
}

async function toggle(row, enabled) {
  await api.patchPrompt(row.id, { enabled });
  row.enabled = enabled;
}

async function makeDefault(row) {
  await api.patchPrompt(row.id, { is_default: true });
  ElMessage.success("已设为默认");
  load();
}

async function remove(row) {
  await ElMessageBox.confirm(`删除「${row.name}」？`, "确认", { type: "warning" });
  await api.deletePrompt(row.id);
  load();
}

onMounted(load);
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.hint { color: var(--muted); font-size: 13px; margin: 0 0 16px; }
.brief { display: flex; gap: 8px; width: 100%; }
</style>
